import asyncio
import websockets

async def station_handler(websocket):
    print(f"New station connection from {websocket.remote_address}")
    try:
        async for message in websocket:
            print(f"Station received: {message}")
            await websocket.send(f"Echo station: {message}")
    except websockets.exceptions.ConnectionClosed:
        print("Station client disconnected")

async def user_handler(websocket):
    print(f"New user connection from {websocket.remote_address}")
    try:
        async for message in websocket:
            print(f"User received: {message}")
            await websocket.send(f"Echo user: {message}")
    except websockets.exceptions.ConnectionClosed:
        print("User client disconnected")

async def main():
    station_server = websockets.serve(station_handler, "127.0.0.1", 8765)
    user_server = websockets.serve(user_handler, "127.0.0.1", 8766)
    
    async with station_server, user_server:
        print("Both WebSocket servers running on ports 8765 and 8766")
        await asyncio.Future()  

if __name__ == "__main__":
    asyncio.run(main())
