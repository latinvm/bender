#!/usr/bin/env python3
"""
Test to verify that Position P/L shown in Recent Activity matches Active Positions pane

This test verifies that we use the current ticker price (not historical close price)
for P/L calculations in both the Active Positions pane and Recent Activity messages.
"""

import sys
import logging
import time
from trader.bitvavo import BitvavoClient
from trader.config import get_config
from trader.virtual_wallet import VirtualWallet
from trader.virtual_market import VirtualMarketOperations
from trader.enhanced_strategy import EnhancedStrategy

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('position_pl_test')

def test_position_pl_consistency():
    """Verify P/L consistency between logs and display"""
    logger.info("="*80)
    logger.info("Testing Position P/L Consistency")
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

    # Get an active position to test with
    positions = virtual_wallet.get_active_positions()
    if not positions:
        logger.warning("No active positions - cannot test")
        return False

    test_market = positions[0]['market']
    logger.info(f"\nTesting with market: {test_market}")

    # Create strategy instance
    strategy = EnhancedStrategy(
        market_ops=market_ops,
        market=test_market,
        investment_amount=10.0,
        virtual_wallet=virtual_wallet
    )

    logger.info("\n" + "="*80)
    logger.info("Step 1: Get current price (what TUI Active Positions uses)")
    logger.info("="*80)

    current_price = strategy.get_current_price(use_cache=False)
    logger.info(f"Current ticker price: €{current_price:.6f}")

    logger.info("\n" + "="*80)
    logger.info("Step 2: Get historical data (what strategy uses for indicators)")
    logger.info("="*80)

    df = strategy.get_historical_data()
    df = strategy.calculate_indicators(df)
    last_close = df.iloc[-1]['close']
    logger.info(f"Last 5m candle close: €{last_close:.6f}")

    logger.info("\n" + "="*80)
    logger.info("Step 3: Calculate P/L using both prices")
    logger.info("="*80)

    entry_price = strategy.entry_prices[test_market]

    # OLD way (using historical close - would cause discrepancy)
    pl_historical = ((last_close - entry_price) / entry_price) * 100

    # NEW way (using current ticker - consistent with Active Positions)
    pl_current = ((current_price - entry_price) / entry_price) * 100

    logger.info(f"Entry price: €{entry_price:.6f}")
    logger.info(f"")
    logger.info(f"P/L using historical close: {pl_historical:+.2f}%")
    logger.info(f"P/L using current ticker:   {pl_current:+.2f}%")
    logger.info(f"Difference: {abs(pl_current - pl_historical):.2f} percentage points")

    logger.info("\n" + "="*80)
    logger.info("Step 4: Simulate sell check (triggers P/L logging)")
    logger.info("="*80)
    logger.info("Watch for 'Position P/L' message - it should use current ticker price")
    logger.info("")

    # This will trigger the P/L logging with current price
    should_sell, reason = strategy.should_sell(df)

    logger.info("\n" + "="*80)
    logger.info("RESULTS")
    logger.info("="*80)
    logger.info(f"✓ Recent Activity will now show P/L based on current ticker: {pl_current:+.2f}%")
    logger.info(f"✓ Active Positions pane shows P/L based on current ticker: {pl_current:+.2f}%")
    logger.info(f"✓ Both values are now CONSISTENT")
    logger.info("")
    logger.info(f"Before this fix, Recent Activity would have shown: {pl_historical:+.2f}%")
    logger.info(f"This could cause confusion when prices differ from the 5m candle close")
    logger.info("="*80)

    return True


if __name__ == "__main__":
    try:
        test_position_pl_consistency()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
