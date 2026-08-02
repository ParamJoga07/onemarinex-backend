#!/usr/bin/env python
"""Send test messages via WebSocket and capture server traces."""

import asyncio
import websockets
import json
import sys
from datetime import datetime

# Test messages to send
TEST_MESSAGES = [
    "modi is idiot",
    "all indians are idiots",
    "DRUGS ARE INJURIOUS",
    "porn!!!!",
]

async def send_message(message: str):
    """Send a single message via WebSocket."""
    try:
        uri = "ws://127.0.0.1:8000/api/v1/chat/1/ws?token=test"

        async with websockets.connect(uri, ping_interval=None) as websocket:
            print(f"\n{'='*80}")
            print(f"SENDING: '{message}'")
            print(f"{'='*80}")

            # Send message
            await websocket.send(json.dumps({"message": message}))

            # Wait for response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                print(f"RESPONSE: {response}")
            except asyncio.TimeoutError:
                print("TIMEOUT - no response")

    except Exception as e:
        print(f"ERROR: {e}")


async def main():
    print("NOTE: These WebSocket connections require authentication.")
    print("Server will likely reject them with 403 Unauthorized.")
    print("But tracing should still appear in server logs.\n")

    for msg in TEST_MESSAGES:
        await send_message(msg)
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
