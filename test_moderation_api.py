#!/usr/bin/env python
"""Test moderation via WebSocket API."""
import asyncio
import json
import time
from datetime import datetime

# Test cases
TESTS = {
    "Normal Messages": [
        ("Hello", False),
        ("Good morning", False),
        ("I need a taxi", False),
    ],
    "Profanity": [
        ("sex", True),
        ("porn", True),
        ("fuck", True),
        ("shit", True),
    ],
    "Profanity in Sentences": [
        ("porn is good", True),
        ("I like sex", True),
        ("where can I find escorts?", True),
        ("are any prostitutes available?", True),
    ],
    "Obfuscated Profanity": [
        ("s.e.x", True),
        ("p0rn", True),
    ],
    "Hate Speech": [
        ("black people fuck off", True),
        ("chinese are idiots", True),
    ],
    "Harassment": [
        ("Joshan is idiot", True),
        ("You are stupid", True),
    ],
    "Violence": [
        ("lets kill him", True),
        ("I will murder you", True),
    ],
    "Spam": [
        ("hgfkguilhiojojiiojoihiuhnjnkjnb", True),
        ("@@4444#$%^@", True),
    ],
    "Language": [
        ("Hello", False),
        ("ela unnaru", True),
        ("dengutha bagunnara", True),
    ],
}

async def test_via_websocket():
    """Test via WebSocket connection."""
    import websockets

    token = "test-token"  # Mock token
    uri = f"ws://127.0.0.1:8000/api/v1/chat/ws/1?token={token}"

    results = []
    passed = 0
    failed = 0
    total = 0

    print("=" * 120)
    print("COMPREHENSIVE MODERATION TEST SUITE (via WebSocket)")
    print("=" * 120)
    print()

    try:
        async with websockets.connect(uri, ping_interval=None, ping_timeout=None) as ws:
            for suite_name, tests in TESTS.items():
                print(f"\n{suite_name}")
                print("-" * 120)

                for message, should_reject in tests:
                    total += 1

                    # Send message
                    payload = json.dumps({"message": message})
                    await ws.send(payload)

                    # Wait for response
                    try:
                        response_data = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        response = json.loads(response_data)

                        if response.get("type") == "error":
                            # Error frame means rejection
                            actual_reject = True
                            reason = response.get("data", {}).get("code", "unknown")
                        elif response.get("type") == "chat_message":
                            # Message was accepted
                            actual_reject = False
                            reason = "accepted"
                        else:
                            actual_reject = False
                            reason = response.get("type", "unknown")

                        test_pass = actual_reject == should_reject
                        if test_pass:
                            passed += 1
                            status = "✅ PASS"
                        else:
                            failed += 1
                            status = "❌ FAIL"

                        msg_display = message[:40] if len(message) <= 40 else message[:37] + "..."
                        expected = "Reject" if should_reject else "Allow"
                        actual = "Reject" if actual_reject else "Allow"

                        print(f"  {status} | {msg_display:43} | Expected: {expected:6} | Actual: {actual:6} | {reason}")

                        results.append({
                            "category": suite_name,
                            "message": message,
                            "expected": should_reject,
                            "actual": actual_reject,
                            "passed": test_pass,
                            "reason": reason
                        })

                    except asyncio.TimeoutError:
                        failed += 1
                        total += 1
                        print(f"  ❌ TIMEOUT | {message[:40]:43}")

    except ConnectionRefusedError:
        print("ERROR: Could not connect to WebSocket. Backend not running?")
        print("Make sure backend is running: python -m uvicorn app.main:app --reload")
        return None

    except Exception as e:
        print(f"ERROR: {e}")
        return None

    # Summary
    print("\n" + "=" * 120)
    print("TEST SUMMARY")
    print("=" * 120)
    print(f"Total Tests:    {total}")
    print(f"Passed:         {passed}")
    print(f"Failed:         {failed}")
    if total > 0:
        print(f"Pass Rate:      {(passed/total*100):.1f}%")
    print()

    return results, passed, failed, total


if __name__ == "__main__":
    result = asyncio.run(test_via_websocket())
    if result:
        results, passed, failed, total = result
        if failed > 0:
            print("\nFAILED TESTS:")
            print("-" * 120)
            for r in results:
                if not r["passed"]:
                    print(f"  {r['category']:30} | {r['message'][:40]:43} | Expected: {str(r['expected']):5} | Got: {str(r['actual']):5}")
