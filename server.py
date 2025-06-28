import asyncio
import websockets

# Connected user clients
user_clients = set()

async def station_handler(websocket):
    print("[Station] Connected")
    try:
        async for message in websocket:
            print(f"[Station] Received: {message}")
            await broadcast_to_users(message)
    except websockets.exceptions.ConnectionClosed:
        print("[Station] Disconnected")

async def user_handler(websocket):
    print("[User] Connected")
    user_clients.add(websocket)
    try:
        async for _ in websocket:
            pass  # Users don't send anything
    except websockets.exceptions.ConnectionClosed:
        print("[User] Disconnected")
    finally:
        user_clients.remove(websocket)

async def broadcast_to_users(data):
    disconnected = set()
    for user in user_clients:
        try:
            await user.send(data)
        except websockets.exceptions.ConnectionClosed:
            disconnected.add(user)
    user_clients.difference_update(disconnected)

async def main_handler(websocket, path):
    if path == "/ws/station":
        await station_handler(websocket)
    elif path == "/ws/user":
        await user_handler(websocket)
    else:
        print(f"[Server] Unknown path: {path}")
        await websocket.close()

async def main():
    server = await websockets.serve(main_handler, "0.0.0.0", 8765)
    print("WebSocket server listening on port 8765...")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())
# import asyncio
# import ssl
# import websockets

# ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
# ssl_context.load_cert_chain(
#     certfile="/etc/letsencrypt/live/seismologos.shop/fullchain.pem",
#     keyfile="/etc/letsencrypt/live/seismologos.shop/privkey.pem"
# )

# async def handler(websocket):
#     print("Client connected")
#     async for message in websocket:
#         print(f"Received: {message}")
#         await websocket.send("Echo: " + message)

# async def main():
#     async with websockets.serve(handler, "0.0.0.0", 443, ssl=ssl_context):
#         print("WSS server running on port 443...")
#         await asyncio.Future()  # Run forever

# # Proper asyncio entry point
# if __name__ == "__main__":
#     asyncio.run(main())

