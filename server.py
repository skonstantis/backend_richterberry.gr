import asyncio
import websockets

PING_INTERVAL = 20  # seconds between pings
PING_TIMEOUT = 10   # seconds to wait pong before closing

async def connection_watchdog(websocket, peer_name):
    try:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            if websocket.closed:
                print(f"Watchdog: websocket {peer_name} already closed", flush=True)
                break
            print(f"Watchdog: sending ping to {peer_name}", flush=True)
            pong_waiter = await websocket.ping()
            try:
                await asyncio.wait_for(pong_waiter, timeout=PING_TIMEOUT)
                print(f"Watchdog: received pong from {peer_name}", flush=True)
            except asyncio.TimeoutError:
                print(f"Watchdog: pong timeout, closing websocket {peer_name}", flush=True)
                await websocket.close()
                break
    except asyncio.CancelledError:
        # Task cancelled on connection close
        pass

async def station_handler(websocket):
    peer_name = websocket.remote_address
    print(f"New station connection from {peer_name}", flush=True)

    watchdog_task = asyncio.create_task(connection_watchdog(websocket, peer_name))

    try:
        async for message in websocket:
            # You can enable this if you want to log messages
            # print(f"Station received: {message}", flush=True)
            await websocket.send(f"Echo station: {message}")
    except websockets.exceptions.ConnectionClosedOK:
        print(f"Station client disconnected cleanly {peer_name}", flush=True)
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"Station client disconnected with error: {e} {peer_name}", flush=True)
    except Exception as e:
        print(f"Unexpected error in station handler: {e} {peer_name}", flush=True)
    finally:
        watchdog_task.cancel()
        print(f"Station connection closed (finally) {peer_name}", flush=True)

async def user_handler(websocket):
    peer_name = websocket.remote_address
    print(f"New user connection from {peer_name}", flush=True)

    watchdog_task = asyncio.create_task(connection_watchdog(websocket, peer_name))

    try:
        async for message in websocket:
            # print(f"User received: {message}", flush=True)
            await websocket.send(f"Echo user: {message}")
    except websockets.exceptions.ConnectionClosedOK:
        print(f"User client disconnected cleanly {peer_name}", flush=True)
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"User client disconnected with error: {e} {peer_name}", flush=True)
    except Exception as e:
        print(f"Unexpected error in user handler: {e} {peer_name}", flush=True)
    finally:
        watchdog_task.cancel()
        print(f"User connection closed (finally) {peer_name}", flush=True)

async def main():
    station_server = websockets.serve(station_handler, "127.0.0.1", 8765)
    user_server = websockets.serve(user_handler, "127.0.0.1", 8766)
    
    async with station_server, user_server:
        print("Both WebSocket servers running on ports 8765 (station) and 8766 (user)", flush=True)
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
