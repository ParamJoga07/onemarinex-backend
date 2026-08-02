#!/usr/bin/env python
"""Test the moderation function directly to capture detailed logs."""

import asyncio
import logging
import sys

# Set up detailed logging to see DEBUG messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)-8s [%(name)s] %(message)s',
    stream=sys.stdout
)

# Now import the moderation function
from app.db.session import SessionLocal
from app.services.chat_moderation import moderate_message

async def test_message(raw_text):
    """Test a single message."""
    print(f"\n{'=' * 80}")
    print(f"TESTING: '{raw_text}'")
    print(f"{'=' * 80}\n")

    db = SessionLocal()
    try:
        result = await moderate_message(
            db=db,
            user_id=1,
            port_id=1,
            raw_text=raw_text
        )

        print(f"\n{'=' * 80}")
        print(f"RESULT:")
        print(f"  rejected: {result.rejected}")
        print(f"  code: {result.code}")
        print(f"  reason_code: {result.reason_code}")
        print(f"  rejected_by: {result.rejected_by}")
        print(f"  matched_term: {result.matched_term}")
        print(f"  ai_route: {result.ai_route}")
        print(f"{'=' * 80}\n")
    finally:
        db.close()

async def main():
    test_messages = [
        "modi is idiot",
        "all indians are idiots",
        "DRUGS ARE INJURIOUS",
        "pakistanis are dumb ass",
    ]

    for msg in test_messages:
        await test_message(msg)

if __name__ == "__main__":
    asyncio.run(main())
