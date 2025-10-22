#!/usr/bin/env python3
"""
Test script for TUI Activity Handler
"""

import sys
import logging
from trader.logger import TUIActivityHandler

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('trader.test')

def test_activity_handler():
    """Test that activity handler filters and formats trading events correctly"""

    print("\n" + "="*80)
    print("Testing TUI Activity Handler")
    print("="*80)

    # Collect messages
    captured_messages = []

    def capture_callback(msg: str):
        captured_messages.append(msg)
        print(f"  Captured: {msg}")

    # Create handler
    handler = TUIActivityHandler(capture_callback)
    logger.addHandler(handler)

    print("\n1. Testing BUY signal logging:")
    logger.info("  ✓ BUY SIGNAL TRIGGERED! (Strong Oversold)")

    print("\n2. Testing BUY order logging:")
    logger.info("Buy order placed for 150.12345678 VET-EUR at €0.014621")

    print("\n3. Testing SELL signal logging:")
    logger.info("  ✓ SELL SIGNAL TRIGGERED (Technical)")

    print("\n4. Testing SELL order logging:")
    logger.info("Sell order placed for 150.12345678 VET-EUR at €0.015000")

    print("\n5. Testing VIRTUAL order logging:")
    logger.info("[VIRTUAL] Order executed: buy 150.12345678 VET-EUR @ €0.014621")

    print("\n6. Testing stop loss/take profit logging:")
    logger.info("  ✓ SELL SIGNAL TRIGGERED (Take Profit: +15.2%)")
    logger.info("  ✓ SELL SIGNAL TRIGGERED (Stop Loss: -5.1%)")

    print("\n7. Testing position logging:")
    logger.info("Loaded active position: 150.12345678 VET-EUR @ €0.014621")
    logger.info("Resuming with 2 existing position(s) - skipping test trade")

    print("\n8. Testing error/warning logging:")
    logger.error("Cannot execute buy: price unavailable")
    logger.warning("Could not get price for FLOKI-EUR: API timeout")

    print("\n9. Testing messages that should NOT be captured:")
    logger.info("Fetching ticker for VET-EUR")  # Should not appear
    logger.info("Starting enhanced trading strategy")  # Should not appear
    logger.debug("Debug message")  # Should not appear

    print("\n" + "="*80)
    print(f"Results: {len(captured_messages)} messages captured")
    print("="*80)

    # Verify we captured the right number
    expected_count = 11  # 9 test messages that should be captured (steps 1-8)
    if len(captured_messages) == expected_count:
        print(f"✓ PASS: Captured exactly {expected_count} messages as expected")
        return True
    else:
        print(f"✗ FAIL: Expected {expected_count} messages, got {len(captured_messages)}")
        return False


def test_database_statistics():
    """Test that database statistics method works"""
    print("\n" + "="*80)
    print("Testing Database Statistics")
    print("="*80)

    try:
        from trader.database import TradeDatabase
        from trader.config import get_config

        _, db_config, _ = get_config()
        db = TradeDatabase(db_path=db_config.db_path)

        stats = db.get_trade_statistics()

        print(f"\nStatistics retrieved:")
        print(f"  Total trades: {stats['total_trades']}")
        print(f"  Winning trades: {stats['winning_trades']}")
        print(f"  Losing trades: {stats['losing_trades']}")
        print(f"  Win rate: {stats['win_rate']:.1f}%")
        print(f"  Avg P/L: €{stats['avg_profit_loss']:.2f}")
        print(f"  Max profit: €{stats['max_profit']:.2f}")
        print(f"  Max loss: €{stats['max_loss']:.2f}")

        print("\n✓ PASS: Database statistics method works")
        return True

    except Exception as e:
        print(f"\n✗ FAIL: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n🧪 Testing Enhanced Activity Logging\n")

    test1 = test_activity_handler()
    test2 = test_database_statistics()

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    if test1:
        print("✓ Activity handler: PASSED")
    else:
        print("✗ Activity handler: FAILED")

    if test2:
        print("✓ Database statistics: PASSED")
    else:
        print("✗ Database statistics: FAILED")

    print("="*80)

    return 0 if (test1 and test2) else 1


if __name__ == "__main__":
    sys.exit(main())
