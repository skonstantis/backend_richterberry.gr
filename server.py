import asyncio
import websockets

connected_users = set()
connected_users_lock = asyncio.Lock()
broadcast_queue = asyncio.Queue()


async def broadcaster():
    while True:
        message = await broadcast_queue.get()
        async with connected_users_lock:
            users_copy = list(connected_users)
        
        coros = []
        for user_ws in users_copy:
            async def safe_send(ws=user_ws):
                try:
                    await asyncio.wait_for(ws.send(message), timeout=0.1)
                except Exception as e:
                    print(f"Client send failed: {ws.remote_address} ({e})", flush=True)
                    async with connected_users_lock:
                        connected_users.discard(ws)
                    try:
                        await ws.close(code=1011, reason="Too slow to keep up")
                    except Exception as close_err:
                        print(f"Error closing socket for {ws.remote_address}: {close_err}", flush=True)

            coros.append(safe_send())

        await asyncio.gather(*coros, return_exceptions=True)


async def station_handler(websocket):
    print(f"New station connection from {websocket.remote_address}", flush=True)

    async def watchdog():
        try:
            await websocket.wait_closed()
        finally:
            print(f"Station connection closed (finally) {websocket.remote_address}", flush=True)

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
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"Station client disconnected with error: {e}", flush=True)
    except Exception as e:
        print(f"Unexpected error in station handler: {e}", flush=True)
    finally:
        watchdog_task.cancel()


async def user_handler(websocket):
    print(f"New user connection from {websocket.remote_address}", flush=True)

    async with connected_users_lock:
        connected_users.add(websocket)

    async def watchdog():
        try:
            await websocket.wait_closed()
        finally:
            print(f"User connection closed (finally) {websocket.remote_address}", flush=True)
            async with connected_users_lock:
                connected_users.discard(websocket)

    watchdog_task = asyncio.create_task(watchdog())

    try:
        async for message in websocket:
            await websocket.send(f"Echo user: {message}")
    except websockets.exceptions.ConnectionClosedOK:
        print("User client disconnected cleanly", flush=True)
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"User client disconnected with error: {e}", flush=True)
    except Exception as e:
        print(f"Unexpected error in user handler: {e}", flush=True)
    finally:
        watchdog_task.cancel()
        async with connected_users_lock:
            connected_users.discard(websocket)


async def main():
    station_server = websockets.serve(station_handler, "127.0.0.1", 8765, ping_interval=None)
    user_server = websockets.serve(user_handler, "127.0.0.1", 8766, ping_interval=20, ping_timeout=10)

    async with station_server, user_server:
        print("WebSocket servers running on ports 8765 (station) and 8766 (users)", flush=True)
        await broadcaster() 

if __name__ == "__main__":
    asyncio.run(main())
