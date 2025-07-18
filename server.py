import asyncio
import websockets
from datetime import datetime, timedelta, timezone
from collections import deque
import json
import time
import signal
from aiohttp import web

# === CONFIG ===

BUFFER_250HZ_DURATION_SECONDS = 30
BUFFER_50HZ_DURATION_SECONDS = 300

stations = [
    {
        "name": "prometheus",
        "id": "GR000",
        "location": "Athens Central",
        "mode": "Testing",
        "type": "High-Resolution Real-Time Seismic Station",
        "connected": False
    },
    {
        "name": "gaia",
        "id": "GR001",
        "location": "Thessaloniki",
        "mode": "Operational",
        "type": "Broadband Seismic Station",
        "connected": False
    },
]

# Create mappings for fast lookup without locking stations list every time
station_name_to_id = {s["name"]: s["id"] for s in stations}
station_id_to_name = {s["id"]: s["name"] for s in stations}

valid_station_ids = set(station_id_to_name.keys())

stations_lock = asyncio.Lock()  # For marking connected state

# === PER-STATION STATE ===

station_state = {}

for s in stations:
    station_id = s["id"]
    station_state[station_id] = {
        "buffer_250hz": deque(),
        "buffer_50hz": deque(),
        "buffer_250hz_lock": asyncio.Lock(),
        "buffer_50hz_lock": asyncio.Lock(),
        "virtual_time_base": None,
        "last_gps_sync_monotonic": None,
    }

# === CONNECTED USERS ===

connected_users = {}
connected_users_lock = asyncio.Lock()

broadcast_queue = asyncio.Queue()

shutdown_event = asyncio.Event()

# === HTTP HANDLERS ===

async def handle_station_buffer(request):
    station_name = request.match_info['station_name']
    buffer_type = request.match_info['buffer_type']

    station_id = station_name_to_id.get(station_name)
    if not station_id:
        return web.json_response({"error": "Station not found"}, status=404)

    if buffer_type == "30":
        buffer_key = "buffer_250hz"
    elif buffer_type == "300":
        buffer_key = "buffer_50hz"
    else:
        return web.json_response({"error": "Invalid buffer type"}, status=400)

    lock = station_state[station_id][buffer_key + "_lock"]
    async with lock:
        buffer_copy = list(station_state[station_id][buffer_key])

    samples = [
        {"timestamp": ts, "value": value}
        for ts, value in buffer_copy
    ]

    return web.json_response({"samples": samples})

async def handle_stations(request):
    return web.json_response({"stations": list(stations)})

# === SAFE SEND ===

async def safe_send(ws, message):
    try:
        await asyncio.wait_for(ws.send(message), timeout=0.1)
    except Exception as e:
        print(f"Client send failed: {ws.remote_address} ({e})", flush=True)
        async with connected_users_lock:
            if ws in connected_users:
                del connected_users[ws]
        try:
            await ws.close(code=1011, reason="Too slow to keep up")
        except Exception as close_err:
            print(f"Error closing socket for {ws.remote_address}: {close_err}", flush=True)

# === VIRTUAL CLOCK LOOP ===

async def virtual_clock_loop():
    while not shutdown_event.is_set():
        await asyncio.sleep(1)

        for station_id in valid_station_ids:
            state = station_state[station_id]
            vt_base = state["virtual_time_base"]
            last_sync = state["last_gps_sync_monotonic"]

            if vt_base and last_sync is not None:
                virtual_time_now = vt_base + timedelta(seconds=(time.monotonic() - last_sync))

                cutoff_ts_250hz = (virtual_time_now - timedelta(seconds=BUFFER_250HZ_DURATION_SECONDS)).timestamp()
                cutoff_ts_50hz = (virtual_time_now - timedelta(seconds=BUFFER_50HZ_DURATION_SECONDS)).timestamp()

                async with state["buffer_250hz_lock"]:
                    while state["buffer_250hz"] and state["buffer_250hz"][0][0] < cutoff_ts_250hz:
                        state["buffer_250hz"].popleft()

                async with state["buffer_50hz_lock"]:
                    while state["buffer_50hz"] and state["buffer_50hz"][0][0] < cutoff_ts_50hz:
                        state["buffer_50hz"].popleft()

# === BROADCASTER ===

async def broadcaster():
    while not shutdown_event.is_set():
        raw_message = await broadcast_queue.get()
        try:
            packet = json.loads(raw_message)
            timestamp_start = datetime.fromisoformat(packet["timestamp_start"].replace("Z", "+00:00")).astimezone(timezone.utc)
            sample_rate = packet["sample_rate"]
            samples = packet["samples"]
            gps_synced = packet["gps_synced"]
            station_id = packet["station_id"]

            if station_id not in valid_station_ids:
                print(f"[WARNING] Unknown station_id '{station_id}' - discarding message", flush=True)
                continue
        except Exception as e:
            print(f"[ERROR] Invalid station packet: {e}", flush=True)
            continue

        state = station_state[station_id]

        if gps_synced and sample_rate > 0 and len(samples) > 0:
            duration = len(samples) / sample_rate
            new_virtual_time = timestamp_start + timedelta(seconds=duration)

            vt_base = state["virtual_time_base"]
            if vt_base and new_virtual_time < vt_base:
                print(f"[INFO] GPS time moved backward for station {station_id}: {vt_base} → {new_virtual_time}", flush=True)

            state["virtual_time_base"] = new_virtual_time
            state["last_gps_sync_monotonic"] = time.monotonic()

        if not (state["virtual_time_base"] and state["last_gps_sync_monotonic"] is not None):
            print(f"[WARNING] No GPS sync yet for station {station_id}; dropping data", flush=True)
            continue

        new_samples_250hz = []
        downsampled_50hz = []

        for i, value in enumerate(samples):
            ts = timestamp_start + timedelta(seconds=i / sample_rate)
            ts_float = ts.timestamp()
            new_samples_250hz.append((ts_float, value))

            if i == 0 or i == len(samples) - 1 or i % 5 == 0:
                downsampled_50hz.append((ts_float, value))

        async with state["buffer_250hz_lock"]:
            state["buffer_250hz"].extend(new_samples_250hz)

        async with state["buffer_50hz_lock"]:
            state["buffer_50hz"].extend(downsampled_50hz)

        packet_to_send = packet.copy()
        packet_to_send["type"] = "data"
        packet_to_send["samples"] = [
            {"timestamp": ts, "value": value}
            for ts, value in new_samples_250hz
        ]

        message_to_send = json.dumps(packet_to_send)

        async with connected_users_lock:
            users_copy = [(ws, sid) for ws, sid in connected_users.items()]

        coros = [safe_send(ws, message_to_send) for ws, sid in users_copy if sid == station_id]
        await asyncio.gather(*coros, return_exceptions=True)

# === WEBSOCKET HANDLERS ===

async def station_handler(websocket):
    print(f"New station connection from {websocket.remote_address}", flush=True)

    try:
        init_message = await asyncio.wait_for(websocket.recv(), timeout=600.0)
        packet = json.loads(init_message)
        station_name = packet.get("station_name")
        station_id = station_name_to_id.get(station_name)
        if not station_id:
            print(f"Unknown station_name '{station_name}' from {websocket.remote_address}", flush=True)
            await websocket.close(code=1008, reason="Invalid station_name")
            return
    except Exception as e:
        print(f"Failed to get station_name: {e}", flush=True)
        await websocket.close(code=1008, reason="Missing or invalid station_name")
        return

    async with stations_lock:
        for station in stations:
            if station["id"] == station_id:
                station["connected"] = True
                print(f"Station '{station_id}' marked as connected.", flush=True)
                break

    async def watchdog():
        try:
            await websocket.wait_closed()
        finally:
            print(f"Station connection closed {websocket.remote_address}", flush=True)
            async with stations_lock:
                for station in stations:
                    if station["id"] == station_id:
                        station["connected"] = False
                        print(f"Station '{station_id}' marked as disconnected.", flush=True)
                        break

    watchdog_task = asyncio.create_task(watchdog())

    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                await websocket.send("Echo station: OK")
                await broadcast_queue.put(message)
            except asyncio.TimeoutError:
                print(f"Inactivity timeout. Closing connection {websocket.remote_address}", flush=True)
                await websocket.close(code=1000, reason="Inactivity timeout")
                break
    except websockets.exceptions.ConnectionClosedOK:
        print("Station client disconnected cleanly", flush=True)
    finally:
        watchdog_task.cancel()

async def user_handler(websocket):
    print(f"New user connection from {websocket.remote_address}", flush=True)

    try:
        init_message = await asyncio.wait_for(websocket.recv(), timeout=600.0)
        packet = json.loads(init_message)
        station_name = packet.get("station_name")
        station_id = station_name_to_id.get(station_name)
        if not station_id:
            print(f"Invalid station_name '{station_name}' from user {websocket.remote_address}", flush=True)
            await websocket.close(code=1008, reason="Invalid station_name")
            return
    except Exception as e:
        print(f"Failed to get station_name from user: {e}", flush=True)
        await websocket.close(code=1008, reason="Missing or invalid station_name")
        return

    async with connected_users_lock:
        connected_users[websocket] = station_id

    try:
        while True:
            await asyncio.sleep(3600)  
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        async with connected_users_lock:
            if websocket in connected_users:
                del connected_users[websocket]

# === SHUTDOWN HANDLER ===

def shutdown():
    print("Shutdown signal received, stopping server...", flush=True)
    shutdown_event.set()

# === MAIN ===

async def main():
    signal.signal(signal.SIGINT, lambda s, f: shutdown())
    signal.signal(signal.SIGTERM, lambda s, f: shutdown())

    app = web.Application()
    app.router.add_get("/api/stations", handle_stations)
    app.router.add_get("/api/stations/{station_name}/buffer/{buffer_type}", handle_station_buffer)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8000)
    await site.start()

    print("HTTP Server started on port 8000", flush=True)

    station_server = await websockets.serve(station_handler, "0.0.0.0", 8001, max_size=None)
    user_server = await websockets.serve(user_handler, "0.0.0.0", 8002, max_size=None)

    print("WebSocket Servers started on ports 8001 (stations) and 8002 (users)", flush=True)

    await asyncio.gather(
        virtual_clock_loop(),
        broadcaster(),
        shutdown_event.wait()
    )

    await runner.cleanup()
    station_server.close()
    await station_server.wait_closed()
    user_server.close()
    await user_server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())
