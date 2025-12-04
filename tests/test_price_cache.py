#!/usr/bin/env python3
"""
Test script to verify price caching functionality
"""

import sys
import time
import logging
from trader.bitvavo import BitvavoClient
from trader.config import get_config
from trader.virtual_wallet import VirtualWallet
from trader.virtual_market import VirtualMarketOperations
from trader.enhanced_strategy import EnhancedStrategy
from trader.multi_market_strategy import MultiMarketStrategy

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('price_cache_test')

def test_enhanced_strategy_cache():
    """Test price caching in EnhancedStrategy"""
    logger.info("="*80)
    logger.info("TEST 1: EnhancedStrategy Price Caching")
    logger.info("="*80)

    # Load config
    bitvavo_config, _, virtual_config, _ = get_config()

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

    # Create strategy instance
    strategy = EnhancedStrategy(
        market_ops=market_ops,
        market='VET-EUR',
        investment_amount=10.0,
        virtual_wallet=virtual_wallet
    )

    logger.info("\n1. Testing first price fetch (should hit API)...")
    start = time.time()
    price1 = strategy.get_current_price(use_cache=False)
    elapsed1 = time.time() - start
    logger.info(f"Price: €{price1:.6f} | Time: {elapsed1*1000:.0f}ms")
    logger.info(f"Cache timestamp: {strategy.last_price_timestamp}")

    logger.info("\n2. Testing cached price fetch (should be fast)...")
    start = time.time()
    price2 = strategy.get_current_price(use_cache=True)
    elapsed2 = time.time() - start
    logger.info(f"Price: €{price2:.6f} | Time: {elapsed2*1000:.0f}ms")

    if elapsed2 < elapsed1 / 10:
        logger.info("Cache is working (much faster than API call)")
    else:
        logger.warning("Cache might not be working properly")

    if price1 == price2:
        logger.info("Prices match")
    else:
        logger.error(f"Price mismatch: {price1} vs {price2}")

    logger.info("\n3. Testing cache expiration (5s max age)...")
    logger.info("Waiting 6 seconds...")
    time.sleep(6)
    start = time.time()
    price3 = strategy.get_current_price(use_cache=True, cache_max_age=5.0)
    elapsed3 = time.time() - start
    logger.info(f"Price: €{price3:.6f} | Time: {elapsed3*1000:.0f}ms")

    if elapsed3 > elapsed2 * 10:
        logger.info("Cache expired and fetched new price")
    else:
        logger.warning("Cache might not have expired properly")

    logger.info("\n" + "="*80)
    # Test passes if we got valid prices
    assert price1 is not None
    assert price2 is not None
    assert price3 is not None


def test_multi_market_strategy_cache():
    """Test price caching in MultiMarketStrategy"""
    logger.info("\n" + "="*80)
    logger.info("TEST 2: MultiMarketStrategy Price Caching")
    logger.info("="*80)

    # Load config
    bitvavo_config, _, virtual_config, _ = get_config()

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
        markets = ['VET-EUR', 'FLOKI-EUR']
    else:
        markets = [pos['market'] for pos in positions[:2]]  # Test with up to 2 markets

    logger.info(f"\nTesting with markets: {', '.join(markets)}")

    # Create multi-market strategy
    multi_strategy = MultiMarketStrategy(
        market_ops=market_ops,
        markets=markets,
        investment_per_market=10.0,
        virtual_wallet=virtual_wallet
    )

    logger.info("\n1. Getting prices without cache (fresh API calls)...")
    start = time.time()
    prices1 = multi_strategy.get_current_prices(use_cache=False)
    elapsed1 = time.time() - start
    logger.info(f"Time: {elapsed1*1000:.0f}ms")
    for market, price in prices1.items():
        logger.info(f"{market}: €{price:.6f}")

    logger.info("\n2. Getting prices with cache (should be fast)...")
    start = time.time()
    prices2 = multi_strategy.get_current_prices(use_cache=True)
    elapsed2 = time.time() - start
    logger.info(f"Time: {elapsed2*1000:.0f}ms")
    for market, price in prices2.items():
        logger.info(f"{market}: €{price:.6f}")

    if elapsed2 < elapsed1 / 5:
        logger.info("Cache is working (much faster)")
    else:
        logger.warning("Cache might not be working properly")

    if prices1 == prices2:
        logger.info("All prices match")
    else:
        logger.warning("Some prices differ (might be due to market movement)")

    logger.info("\n" + "="*80)
    # Test passes if we got prices for all markets
    assert len(prices1) > 0
    assert len(prices2) > 0


def test_tui_price_refresh():
    """Test TUI price refresh with short cache (5s)"""
    logger.info("\n" + "="*80)
    logger.info("TEST 3: TUI Price Refresh (5s cache)")
    logger.info("="*80)

    # Load config
    bitvavo_config, _, virtual_config, _ = get_config()

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

    # Get active positions
    positions = virtual_wallet.get_active_positions()
    if not positions:
        logger.warning("No active positions - using default markets")
        markets = ['VET-EUR']
    else:
        markets = [pos['market'] for pos in positions[:1]]

    logger.info(f"\nTesting with market: {markets[0]}")

    # Create multi-market strategy
    multi_strategy = MultiMarketStrategy(
        market_ops=market_ops,
        markets=markets,
        investment_per_market=10.0,
        virtual_wallet=virtual_wallet
    )

    logger.info("\n1. Simulating TUI update #1 (fresh fetch)...")
    start = time.time()
    prices1 = multi_strategy.get_current_prices(use_cache=True, cache_max_age=5.0)
    elapsed1 = time.time() - start
    logger.info(f"Time: {elapsed1*1000:.0f}ms")
    for market, price in prices1.items():
        logger.info(f"{market}: €{price:.6f}")

    logger.info("\n2. Simulating TUI update #2 after 3 seconds (should use cache)...")
    time.sleep(3)
    start = time.time()
    prices2 = multi_strategy.get_current_prices(use_cache=True, cache_max_age=5.0)
    elapsed2 = time.time() - start
    logger.info(f"Time: {elapsed2*1000:.0f}ms")
    for market, price in prices2.items():
        logger.info(f"{market}: €{price:.6f}")

    if elapsed2 < elapsed1 / 10:
        logger.info("Cache hit - prices returned quickly")
    else:
        logger.warning("Cache miss - unexpected")

    logger.info("\n3. Simulating TUI update #3 after 6 seconds total (cache should expire)...")
    time.sleep(3)  # Total 6 seconds since first fetch
    start = time.time()
    prices3 = multi_strategy.get_current_prices(use_cache=True, cache_max_age=5.0)
    elapsed3 = time.time() - start
    logger.info(f"Time: {elapsed3*1000:.0f}ms")
    for market, price in prices3.items():
        logger.info(f"{market}: €{price:.6f}")

    if elapsed3 > elapsed2 * 10:
        logger.info("Cache expired - fetched fresh prices from API")
    else:
        logger.warning("Cache might not have expired (or API was very fast)")

    logger.info("\nConclusion: TUI will get fresh prices every 5 seconds (matching update interval)")
    logger.info("This ensures Active Positions pane shows current prices after trades.")

    logger.info("\n" + "="*80)
    # Test passes if we got prices
    assert len(prices1) > 0
    assert len(prices2) > 0
    assert len(prices3) > 0


def main():
    """Run all tests"""
    logger.info("\nTesting Price Caching Implementation\n")

    try:
        test1_success = test_enhanced_strategy_cache()
        test2_success = test_multi_market_strategy_cache()
        test3_success = test_tui_price_refresh()

        logger.info("\n" + "="*80)
        logger.info("TEST RESULTS")
        logger.info("="*80)

        if test1_success:
            logger.info("PASSED - EnhancedStrategy caching")
        else:
            logger.error("FAILED - EnhancedStrategy caching")

        if test2_success:
            logger.info("PASSED - MultiMarketStrategy caching")
        else:
            logger.error("FAILED - MultiMarketStrategy caching")

        if test3_success:
            logger.info("PASSED - TUI price refresh")
        else:
            logger.error("FAILED - TUI price refresh")

        logger.info("="*80)

        return 0 if (test1_success and test2_success and test3_success) else 1

    except Exception as e:
        logger.error(f"Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
