#!/usr/bin/env python3
"""
Test script to verify TUI debugging and price update logic
"""

import sys
import logging
from trader.bitvavo import BitvavoClient
from trader.config import get_config
from trader.virtual_wallet import VirtualWallet
from trader.virtual_market import VirtualMarketOperations
from trader.multi_market_strategy import MultiMarketStrategy

# Setup logging with DEBUG level to see all messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('tui_debug_test')

def test_price_fetch_with_logging():
    """Test that price fetches show the actual price values in logs"""
    logger.info("="*80)
    logger.info("Testing Price Fetch Logging")
    logger.info("="*80)

    # Load config
    bitvavo_config, _, virtual_config = get_config()

    # Initialize client and virtual wallet
    client = BitvavoClient(api_key=bitvavo_config.api_key, api_secret=bitvavo_config.api_secret)
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

    # Get active positions to determine markets
    positions = virtual_wallet.get_active_positions()
    if not positions:
        logger.warning("No active positions - using default markets")
        markets = ['VET-EUR']
    else:
        markets = [pos['market'] for pos in positions[:3]]

    logger.info(f"\nTesting with markets: {', '.join(markets)}")

    # Create multi-market strategy
    multi_strategy = MultiMarketStrategy(
        market_ops=market_ops,
        markets=markets,
        investment_per_market=10.0,
        virtual_wallet=virtual_wallet
    )

    logger.info("\n" + "="*80)
    logger.info("Fetching prices - you should see price values in the logs")
    logger.info("="*80)

    # Fetch prices (should show "→ Price: €X.XXXXXX" in logs)
    prices = multi_strategy.get_current_prices(use_cache=False)

    logger.info("\n" + "="*80)
    logger.info("RESULTS")
    logger.info("="*80)

    for market, price in prices.items():
        logger.info(f"{market}: €{price:.6f}")

    logger.info("\nCheck the logs above - you should see:")
    logger.info("  1. 'Fetching ticker for <MARKET>'")
    logger.info("  2. '  → Price: €X.XXXXXX' (this is the new debug info)")
    logger.info("\n" + "="*80)

    return True


if __name__ == "__main__":
    try:
        test_price_fetch_with_logging()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
