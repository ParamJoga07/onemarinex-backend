#!/usr/bin/env python
"""Send authenticated test messages via WebSocket to trigger moderation traces."""

import asyncio
import websockets
import json

AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJqYWdhZGVlc2gucGFkYWxhMjAyMGRuc0BnbWFpbC5jb20iLCJ0eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzg2ODI4NjI3fQ.dJ1RArytHuRJENS4Ec249DbVqVUNaeMLqDbicA6-FiI"
PORT_ID = 3  # Dubai port

TEST_MESSAGES = [
    "modi is idiot",
    "all indians are idiots",
    "DRUGS ARE INJURIOUS",
    "porn!!!!",
]

async def send_message(message: str):
    """Send a single message via WebSocket with auth."""
    uri = f"ws://127.0.0.1:8000/api/v1/chat/{PORT_ID}/ws?token={AUTH_TOKEN}"

    try:
        print(f"\nConnecting to: {uri[:80]}...")
        async with websockets.connect(uri) as websocket:
            print(f"Connected! Sending: '{message}'")

            # Send message
            await websocket.send(json.dumps({"message": message}))

            # Wait for response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                resp_data = json.loads(response)
                print(f"Response type: {resp_data.get('type')}")
                if resp_data.get('type') == 'error':
                    print(f"  Error: {resp_data.get('data', {}).get('message')}")
                elif resp_data.get('type') == 'chat_message':
                    print(f"  Message sent successfully!")
            except asyncio.TimeoutError:
                print("Timeout - no response")

    except Exception as e:
        print(f"Connection error: {e}")


async def main():
    print("=" * 80)
    print("SENDING AUTHENTICATED TEST MESSAGES")
    print("=" * 80)

    for msg in TEST_MESSAGES:
        await send_message(msg)
        await asyncio.sleep(1)

    print("\n" + "=" * 80)
    print("Waiting for server to process...")
    await asyncio.sleep(2)
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
