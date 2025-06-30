import asyncio
import websockets

async def station_handler(websocket):
    print(f"New station connection from {websocket.remote_address}", flush=True)
    
    async def watchdog():
        try:
            await websocket.wait_closed()
        finally:
            print(f"Station connection closed (finally) {websocket.remote_address}", flush=True)
    
    watchdog_task = asyncio.create_task(watchdog())
    
    try:
        async for message in websocket:
            # You can uncomment to debug message content:
            # print(f"Station received: {message}", flush=True)
            await websocket.send(f"Echo station: {message}")
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
    
    async def watchdog():
        try:
            await websocket.wait_closed()
        finally:
            print(f"User connection closed (finally) {websocket.remote_address}", flush=True)
    
    watchdog_task = asyncio.create_task(watchdog())
    
    try:
        async for message in websocket:
            # print(f"User received: {message}", flush=True)
            await websocket.send(f"Echo user: {message}")
    except websockets.exceptions.ConnectionClosedOK:
        print("User client disconnected cleanly", flush=True)
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"User client disconnected with error: {e}", flush=True)
    except Exception as e:
        print(f"Unexpected error in user handler: {e}", flush=True)
    finally:
        watchdog_task.cancel()

async def main():
    station_server = websockets.serve(station_handler, "127.0.0.1", 8765)
    user_server = websockets.serve(user_handler, "127.0.0.1", 8766, ping_interval=20, ping_timeout=10)
    
    async with station_server, user_server:
        print("Both WebSocket servers running on ports 8765 and 8766", flush=True)
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
