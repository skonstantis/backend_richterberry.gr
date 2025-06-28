import asyncio
import websockets
import json
import logging
#test
HOST = "0.0.0.0"
PORT = 8765

connected_clients = set()

logging.basicConfig(
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
    level=logging.INFO
)

async def handle_client(ws):
    client_ip = ws.remote_address[0]
    logging.info(f"New connection from {client_ip}")
    connected_clients.add(ws)

    try:
        while True:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=2)
            except asyncio.TimeoutError:
                logging.warning(f"Timeout (2s) from {client_ip} - closing connection")
                await ws.close()
                break
            except websockets.exceptions.ConnectionClosedOK:
                logging.info(f"Client {client_ip} closed connection normally")
                break
            except websockets.exceptions.ConnectionClosedError as e:
                logging.error(f"Unexpected disconnect from {client_ip}: {e}")
                break

            try:
                data = json.loads(message)
                station_id = data.get("station_id", "UNKNOWN")
                samples = data.get("samples", [])
                ts_start = data.get("timestamp_start")  # ISO8601 string or None
                gps_synced = data.get("gps_synced", None)
                sample_rate = data.get("sample_rate", None)
                max_jitter = data.get("max_jitter_ms", None)

                logging.info(
                    f"Station {station_id} | samples: {len(samples)} | "
                    f"timestamp_start: {ts_start or 'None'} | "
                    f"gps_synced: {gps_synced} | sample_rate: {sample_rate} | max_jitter_ms: {max_jitter}"
                )

            except json.JSONDecodeError:
                logging.warning(f"Invalid JSON from {client_ip}")

    except Exception as e:
        logging.error(f"Unexpected error with connection from {client_ip}: {e}")
    finally:
        connected_clients.discard(ws)
        logging.info(f"Disconnected from {client_ip}")

async def main():
    logging.info(f"WebSocket server starting on ws://{HOST}:{PORT}")
    try:
        async with websockets.serve(handle_client, HOST, PORT):
            await asyncio.Future()  # Run forever
    except asyncio.CancelledError:
        logging.info("Server stopped internally")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Server stopped by user (Ctrl+C)")
