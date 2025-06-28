import asyncio
import websockets

# Path your clients will connect to
PATH = "/ws/station"

async def handler(websocket, path):
    if path != PATH:
        # Reject connections to other paths
        await websocket.close(code=1008, reason="Invalid path")
        return
    
    print(f"Client connected: {websocket.remote_address}")
    try:
        async for message in websocket:
            print(f"Received: {message}")
            response = f"Echo: {message}"
            await websocket.send(response)
    except websockets.exceptions.ConnectionClosed as e:
        print(f"Connection closed: {e}")

async def main():
    # Listen only on localhost because nginx reverse proxy will forward external requests
    async with websockets.serve(handler, "127.0.0.1", 5000):
        print("WebSocket server listening on ws://127.0.0.1:5000")
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

