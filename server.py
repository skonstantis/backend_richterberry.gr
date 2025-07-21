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
        "mode": "Testing",
        "type": "Broadband Seismic Station",
        "connected": False
    }
]

dummy_station = {
    "name": "dummy",
    "id": "DUMMY",
    "location": "N/A",
    "mode": "Idle",
    "type": "Dummy Station",
    "connected": False,
}

valid_station_ids = {s["id"] for s in stations}
station_name_to_id = {s["name"]: s["id"] for s in stations}
stations_max = {s["name"]: 0 for s in stations}
stations_lock = asyncio.Lock()

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

# === CONNECTED USERS: ===

connected_users = {}
connected_users_lock = asyncio.Lock()

broadcast_queue = asyncio.Queue(maxsize=100)

shutdown_event = asyncio.Event()

stations_max_lock = asyncio.Lock()

# === HTTP HANDLERS ===

async def send_stations_max_periodically():
    while not shutdown_event.is_set():
        await asyncio.sleep(1) 

        async with stations_max_lock:  
            highs_copy = stations_max.copy()

        message = json.dumps({
            "type": "stations_max",
            "stations_max": highs_copy
        })

        async with connected_users_lock:
            users_copy = list(connected_users.keys())

        coros = [safe_send(ws, message) for ws in users_copy]
        await asyncio.gather(*coros, return_exceptions=True)
        
async def handle_station_buffer(request):
    station_name = request.match_info['station_name']
    buffer_type = request.match_info['buffer_type']

    station = next((s for s in stations if s["name"] == station_name), None)
    if not station:
        return web.json_response({"error": "Station not found"}, status=404)

    station_id = station["id"]

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

async def broadcast_station_status(station_id: str, connected: bool):
    async with connected_users_lock:
        users_copy = list(connected_users.keys())
    message = json.dumps({
        "type": "station_status",
        "station_id": station_id,
        "connected": connected
    })
    for ws in users_copy:
        asyncio.create_task(safe_send(ws, message))

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
        station_id = packet["station_id"]
        if station_id not in valid_station_ids:
            print(f"Unknown station_id '{station_id}' from {websocket.remote_address}", flush=True)
            await websocket.close(code=1008, reason="Invalid station_id")
            return
    except Exception as e:
        print(f"Failed to get station_id: {e}", flush=True)
        await websocket.close(code=1008, reason="Missing or invalid station_id")
        return

    async with stations_lock:
        for station in stations:
            if station["id"] == station_id:
                station["connected"] = True
                print(f"Station '{station_id}' marked as connected.", flush=True)
                break
    await broadcast_station_status(station_id, True)


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
            await broadcast_station_status(station_id, False)

    watchdog_task = asyncio.create_task(watchdog())
            
    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                await websocket.send("Echo station: OK") 
                
                try:
                    packet = json.loads(message)
                    samples = packet.get("samples", [])
                    station_id = packet.get("station_id")

                    station_name = next((s["name"] for s in stations if s["id"] == station_id), None)

                    if station_name and samples:
                        async with stations_max_lock:
                            stations_max[station_name] = max(samples)

                except Exception as e:
                    print(f"[WARN] Failed to update stations_max: {e}")

                try:
                    broadcast_queue.put_nowait(message)
                except asyncio.QueueFull:
                    try:
                        _ = broadcast_queue.get_nowait()   
                        await broadcast_queue.put(message) 
                        print("[WARNING] Broadcast queue full — dropped oldest to make room")
                    except asyncio.QueueEmpty:
                        print("[WARNING] Queue full but nothing to drop?!")

            except asyncio.TimeoutError:
                print(f"Inactivity timeout. Closing connection {websocket.remote_address}", flush=True)
                await websocket.close(code=1000, reason="Inactivity timeout")
                break
    except websockets.exceptions.ConnectionClosedOK:
        print("Station client disconnected cleanly", flush=True)
    finally:
        await watchdog_task

async def user_handler(websocket):
    print(f"New user connection from {websocket.remote_address}", flush=True)

    try:
        init_message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
        packet = json.loads(init_message)
        station_name = packet["station_name"]

        station_id = station_name_to_id.get(station_name)
        if not station_id or station_id not in valid_station_ids:
            dummy_station_id = "DUMMY"
            station_id = dummy_station_id
            print(f"Assigned dummy station_id '{station_id}' for unknown station_name '{station_name}' from user {websocket.remote_address}", flush=True)
    except Exception as e:
        print(f"Failed to get station_id from user: {e}", flush=True)
        await websocket.close(code=1008, reason="Missing or invalid station_id")
        return


    async with connected_users_lock:
        connected_users[websocket] = station_id

    async with stations_lock:
        stations_copy = list(stations)  
    try:
        await websocket.send(json.dumps({
            "type": "stations",
            "stations": stations_copy
        }))
    except Exception as e:
        print(f"Failed to send stations list to user {websocket.remote_address}: {e}", flush=True)

    async def watchdog():
        try:
            await websocket.wait_closed()
        finally:
            print(f"User connection closed {websocket.remote_address}", flush=True)
            async with connected_users_lock:
                if websocket in connected_users:
                    del connected_users[websocket]

            station_name = next((s["name"] for s in stations if s["id"] == station_id), None)
            if station_name:
                async with stations_max_lock:
                    stations_max[station_name] = 0
            
    watchdog_task = asyncio.create_task(watchdog())

    try:
        async for message in websocket:
            await websocket.send(f"Echo user: {message}")
    finally:
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass

        async with connected_users_lock:
            if websocket in connected_users:
                del connected_users[websocket]

# === MAIN ===
def handle_shutdown_signal():
    print("Shutting down...", flush=True)
    shutdown_event.set()

async def main():
    signal.signal(signal.SIGINT, lambda s, f: handle_shutdown_signal())
    signal.signal(signal.SIGTERM, lambda s, f: handle_shutdown_signal())

    station_server = websockets.serve(station_handler, "127.0.0.1", 8765, ping_interval=None)
    user_server = websockets.serve(user_handler, "127.0.0.1", 8766, ping_interval=20, ping_timeout=10)

    app = web.Application()
    app.router.add_get(
        r"/{station_name:[a-zA-Z0-9_-]+}{buffer_type:(30|300)}",
        handle_station_buffer
    )
    runner = web.AppRunner(app)
    await runner.setup()
    http_site = web.TCPSite(runner, "127.0.0.1", 8080)
    await http_site.start()

    async with station_server, user_server:
        print("Servers running on ports 8765 (stations WS), 8766 (users WS), 8080 (HTTP)", flush=True)

        broadcaster_task = asyncio.create_task(broadcaster())
        clock_task = asyncio.create_task(virtual_clock_loop())
        highs_task = asyncio.create_task(send_stations_max_periodically())

        await shutdown_event.wait()
        await runner.cleanup()
        broadcaster_task.cancel()
        clock_task.cancel()
        highs_task.cancel()
        try:
            await highs_task
        except asyncio.CancelledError:
            pass
        await asyncio.gather(broadcaster_task, clock_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())