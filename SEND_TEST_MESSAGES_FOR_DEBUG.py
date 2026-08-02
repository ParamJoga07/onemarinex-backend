#!/usr/bin/env python
"""Send test messages via WebSocket and print debug output."""

import asyncio
import websockets
import json
import sys

async def send_message(message_text: str, jwt_token: str):
    """Send a message via WebSocket."""
    uri = "ws://127.0.0.1:8000/api/v1/ws?token=" + jwt_token
    print(f"\n{'='*80}")
    print(f"SENDING: {repr(message_text)}")
    print(f"{'='*80}")

    try:
        async with websockets.connect(uri) as websocket:
            msg = {
                "type": "message",
                "port_id": 1,
                "text": message_text
            }
            await websocket.send(json.dumps(msg))

            # Wait for response
            response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
            print(f"Response: {response[:200]}")
    except asyncio.TimeoutError:
        print("No response (timeout)")
    except Exception as e:
        print(f"Error: {e}")

async def main():
    # Use the test JWT token
    jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJqYWdhZGVlc2gucGFkYWxhMjAyMGRuc0BnbWFpbC5jb20iLCJpZCI6MSwicG9ydHMiOltdLCJpc19zdXBlcmFkbWluIjpmYWxzZSwiaWF0IjoxNzIzMTAwNDAwLCJleHAiOjk5OTk5OTk5OTl9.t1234567890"

    test_messages = [
        "jagadeesh",
        "jagadeesh is good",
        "hello jagadeesh",
        "raju",
        "raju is good",
        "hello world",
    ]

    for msg in test_messages:
        await send_message(msg, jwt_token)
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
