#!/usr/bin/env python3
"""
Script to verify that current prices are correctly retrieved from Bitvavo API
for all active positions.
"""

import sys
import logging
from trader.bitvavo import BitvavoClient
from trader.config import get_config
from trader.virtual_wallet import VirtualWallet
from trader.virtual_market import VirtualMarketOperations
from trader.market import MarketOperations

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('price_check')

def check_virtual_mode():
    """Check price retrieval in virtual mode"""
    logger.info("="*80)
    logger.info("CHECKING VIRTUAL MODE PRICE RETRIEVAL")
    logger.info("="*80)

    # Load config
    bitvavo_config, _, virtual_config = get_config()

    # Initialize client
    client = BitvavoClient(api_key=bitvavo_config.api_key, api_secret=bitvavo_config.api_secret)

    # Initialize virtual wallet
    virtual_wallet = VirtualWallet(
        db_path=virtual_config.virtual_db_path,
        initial_balance=virtual_config.initial_balance
    )

    # Initialize virtual market operations
    market_ops = VirtualMarketOperations(
        client=client,
        virtual_wallet=virtual_wallet,
        operator_id=bitvavo_config.operator_id,
        trading_fee_pct=virtual_config.trading_fee_pct
    )

    # Get active positions
    positions = virtual_wallet.get_active_positions()

    if not positions:
        logger.info("\n❌ No active positions found in virtual wallet")
        return False

    logger.info(f"\n✓ Found {len(positions)} active position(s)")
    logger.info("\n" + "-"*80)

    all_successful = True

    # For each position, verify we can get current price
    for i, pos in enumerate(positions, 1):
        market = pos['market']
        entry_price = pos['entry_price']
        amount = pos['amount']

        logger.info(f"\nPosition {i}: {market}")
        logger.info(f"  Entry Price: €{entry_price:.6f}")
        logger.info(f"  Amount: {amount:.8f}")

        try:
            # Method 1: Using get_ticker (used by virtual_market.py:225)
            logger.info(f"\n  Testing get_ticker()...")
            ticker = market_ops.get_ticker(market)
            current_price_ticker = float(ticker['price'])
            logger.info(f"  ✓ get_ticker() -> €{current_price_ticker:.6f}")

            # Verify ticker has expected fields
            expected_fields = ['price', 'bid', 'ask', 'timestamp']
            missing_fields = [f for f in expected_fields if f not in ticker]
            if missing_fields:
                logger.warning(f"  ⚠️  Ticker missing fields: {missing_fields}")
            else:
                logger.info(f"  ✓ Ticker has all expected fields")
                logger.info(f"    - bid: €{float(ticker.get('bid', 0)):.6f}")
                logger.info(f"    - ask: €{float(ticker.get('ask', 0)):.6f}")

            # Method 2: Direct client call (fallback)
            logger.info(f"\n  Testing direct client.tickerPrice()...")
            ticker_direct = client.tickerPrice({'market': market})
            current_price_direct = float(ticker_direct['price'])
            logger.info(f"  ✓ client.tickerPrice() -> €{current_price_direct:.6f}")

            # Verify prices match
            if abs(current_price_ticker - current_price_direct) < 0.000001:
                logger.info(f"  ✓ Both methods return same price")
            else:
                logger.warning(f"  ⚠️  Price mismatch: {current_price_ticker:.6f} vs {current_price_direct:.6f}")
                all_successful = False

            # Calculate P/L
            pl_pct = ((current_price_ticker - entry_price) / entry_price) * 100
            pl_eur = (current_price_ticker - entry_price) * amount

            logger.info(f"\n  Current Position Value:")
            logger.info(f"    Current Price: €{current_price_ticker:.6f}")
            logger.info(f"    P/L: {pl_pct:+.2f}% (€{pl_eur:+.2f})")

        except Exception as e:
            logger.error(f"  ❌ Error retrieving price for {market}: {str(e)}")
            all_successful = False
            import traceback
            traceback.print_exc()

    logger.info("\n" + "="*80)

    # Test the portfolio summary function (tui.py uses this)
    logger.info("\nTesting portfolio summary (used by TUI)...")
    try:
        prices = {}
        for pos in positions:
            market = pos['market']
            ticker = market_ops.get_ticker(market)
            prices[market] = float(ticker['price'])
            logger.info(f"  {market}: €{prices[market]:.6f}")

        summary = virtual_wallet.get_position_summary(prices)
        logger.info(f"\n✓ Portfolio summary generated successfully")
        logger.info(f"  Position count: {summary['position_count']}")
        logger.info(f"  Total current value: €{summary['total_current_value']:.2f}")
        logger.info(f"  Total unrealized P/L: €{summary['total_unrealized_pl']:+.2f}")

    except Exception as e:
        logger.error(f"❌ Error generating portfolio summary: {str(e)}")
        all_successful = False
        import traceback
        traceback.print_exc()

    logger.info("="*80)

    return all_successful


def check_real_mode():
    """Check price retrieval in real trading mode"""
    logger.info("\n" + "="*80)
    logger.info("CHECKING REAL MODE PRICE RETRIEVAL")
    logger.info("="*80)

    # Load config
    bitvavo_config, db_config, _ = get_config()

    # Initialize client
    client = BitvavoClient(api_key=bitvavo_config.api_key, api_secret=bitvavo_config.api_secret)

    # Initialize market operations
    market_ops = MarketOperations(client, operator_id=bitvavo_config.operator_id)

    # Get database
    from trader.database import TradeDatabase
    db = TradeDatabase(db_config.db_path)

    # Get active positions
    positions = db.get_active_positions()

    if not positions:
        logger.info("\n❌ No active positions found in database")
        return True  # Not an error if no positions

    logger.info(f"\n✓ Found {len(positions)} active position(s)")
    logger.info("\n" + "-"*80)

    all_successful = True

    # For each position, verify we can get current price
    for i, pos in enumerate(positions, 1):
        market = pos['market']
        entry_price = pos['entry_price']
        amount = pos['amount']

        logger.info(f"\nPosition {i}: {market}")
        logger.info(f"  Entry Price: €{entry_price:.6f}")
        logger.info(f"  Amount: {amount:.8f}")

        try:
            # Get current price
            ticker = market_ops.get_ticker(market)
            current_price = float(ticker['price'])
            logger.info(f"  ✓ Current Price: €{current_price:.6f}")

            # Calculate P/L
            pl_pct = ((current_price - entry_price) / entry_price) * 100
            pl_eur = (current_price - entry_price) * amount

            logger.info(f"  P/L: {pl_pct:+.2f}% (€{pl_eur:+.2f})")

        except Exception as e:
            logger.error(f"  ❌ Error retrieving price for {market}: {str(e)}")
            all_successful = False
            import traceback
            traceback.print_exc()

    logger.info("\n" + "="*80)
    return all_successful


def main():
    """Main entry point"""
    print("\n🔍 Checking if current prices are correctly retrieved from Bitvavo API\n")

    # Check both modes
    virtual_success = check_virtual_mode()
    real_success = check_real_mode()

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    if virtual_success:
        print("✓ Virtual mode: Price retrieval working correctly")
    else:
        print("❌ Virtual mode: Issues detected")

    if real_success:
        print("✓ Real mode: Price retrieval working correctly")
    else:
        print("❌ Real mode: Issues detected")

    print("="*80)

    # Exit code
    sys.exit(0 if (virtual_success and real_success) else 1)


if __name__ == "__main__":
    main()
