#!/usr/bin/env python3
"""Run the EVE Sentinel Discord bot."""

import asyncio
import sys

from backend.discord_bot import run_bot
from backend.logging_config import setup_logging


def main() -> None:
    """Entry point for the Discord bot."""
    setup_logging("INFO")

    print("Starting EVE Sentinel Discord Bot...")
    print("Press Ctrl+C to stop")

    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\nBot stopped")
        sys.exit(0)
    except Exception as e:
        print(f"Bot error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
