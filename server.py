import asyncio
import websockets

async def handler(websocket, path):
    if path == "/ws/station":
        async for message in websocket:
            print("Received:", message)
            await websocket.send("Echo: " + message)
    else:
        # Close connection if path does not match
        await websocket.close(code=1008, reason="Invalid path")

start_server = websockets.serve(handler, "localhost", 5000)

asyncio.get_event_loop().run_until_complete(start_server)
print("WebSocket server running on ws://localhost:5000/ws/station")
asyncio.get_event_loop().run_forever()

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

