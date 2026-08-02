#!/usr/bin/env python
"""Test script to trigger dictionary lookup debug logging."""

import asyncio
import json
import logging
from app.db.session import SessionLocal
from app.services.chat_moderation import moderate_message

# Set up logging to see debug output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_moderation(message: str):
    """Test a message and print debug output."""
    print("\n" + "="*80)
    print(f"TESTING MESSAGE: {repr(message)}")
    print("="*80)

    db = SessionLocal()
    try:
        result = await moderate_message(
            db=db,
            user_id=1,
            port_id=1,
            raw_text=message
        )
        print(f"\nRESULT: rejected={result.rejected}, code={result.code}, by={result.rejected_by}")
        if result.matched_term:
            print(f"MATCHED_TERM: {result.matched_term}")
    finally:
        db.close()

async def main():
    """Run test cases."""
    test_cases = [
        "jagadeesh",
        "jagadeesh is good",
        "hello jagadeesh",
        "raju",
        "raju is good",
        "hello world",  # control - should pass
    ]

    for message in test_cases:
        await test_moderation(message)
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(main())
