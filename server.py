import asyncio
import ssl
import websockets

user_clients = set()

async def station_handler(websocket):
    print("[Station] Connected")
    try:
        async for message in websocket:
            print(f"[Station] Received: {message}")
            disconnected = set()
            for user in user_clients:
                try:
                    await user.send(message)
                except websockets.ConnectionClosed:
                    disconnected.add(user)
            user_clients.difference_update(disconnected)
    except websockets.ConnectionClosed:
        print("[Station] Disconnected")

async def user_handler(websocket):
    print("[User] Connected")
    user_clients.add(websocket)
    try:
        async for _ in websocket:
            pass  # users don't send messages
    except websockets.ConnectionClosed:
        print("[User] Disconnected")
    finally:
        user_clients.remove(websocket)

async def handler(websocket, path):
    if path == "/ws/station":
        await station_handler(websocket)
    elif path == "/ws/user":
        await user_handler(websocket)
    else:
        print(f"[Server] Unknown path: {path}")
        await websocket.close()

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ssl_context.load_cert_chain(
    certfile="/etc/letsencrypt/live/seismologos.shop/fullchain.pem",
    keyfile="/etc/letsencrypt/live/seismologos.shop/privkey.pem"
)

async def main():
    async with websockets.serve(
        ws_handler=handler,
        host="0.0.0.0",
        port=443,
        ssl=ssl_context,
    ):
        print("WebSocket server started on wss://0.0.0.0:443")
        await asyncio.Future()  # run forever

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

