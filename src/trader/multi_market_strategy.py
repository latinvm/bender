import logging
import time
import pandas as pd
from typing import List, Dict
from trader.enhanced_strategy import EnhancedStrategy
from trader.market import MarketOperations

logger = logging.getLogger('trader.multi_market')

class MultiMarketStrategy:
    """Run trading strategies across multiple markets simultaneously"""

    def __init__(self, market_ops: MarketOperations, markets: List[str], investment_per_market: float = 10.0, virtual_wallet=None):
        """Initialize multi-market strategy

        Args:
            market_ops: Market operations instance
            markets: List of market symbols to trade (e.g., ['FLOKI-EUR', 'PEPE-EUR'])
            investment_per_market: Investment amount per market (default: €10)
            virtual_wallet: Optional VirtualWallet instance for paper trading
        """
        self.market_ops = market_ops
        self.investment_per_market = investment_per_market
        self.virtual_wallet = virtual_wallet

        # Check for existing positions (orphaned positions from previous runs)
        if virtual_wallet is not None:
            active_positions = virtual_wallet.get_active_positions()
        else:
            from trader.database import TradeDatabase
            db = TradeDatabase()
            active_positions = db.get_active_positions()

        # Add any markets with existing positions that aren't in the markets list
        orphaned_markets = [pos['market'] for pos in active_positions if pos['market'] not in markets]
        if orphaned_markets:
            logger.info(f"Found {len(orphaned_markets)} orphaned position(s) from previous runs: {', '.join(orphaned_markets)}")
            logger.info("Adding these markets to continue managing existing positions")
            markets = list(markets) + orphaned_markets

        self.markets = markets

        # Create a strategy instance for each market
        self.strategies: Dict[str, EnhancedStrategy] = {}
        for market in markets:
            logger.info(f"Initializing strategy for {market}")
            self.strategies[market] = EnhancedStrategy(
                market_ops=market_ops,
                market=market,
                investment_amount=investment_per_market,
                virtual_wallet=virtual_wallet
            )

        logger.info(f"MultiMarketStrategy initialized with {len(markets)} markets")
        logger.info(f"Markets: {', '.join(markets)}")
        logger.info(f"Total capital allocation: €{investment_per_market * len(markets):.2f}")

    def execute_all_trades(self):
        """Execute trading logic for all markets"""
        logger.info(f"\n{'='*80}")
        logger.info(f"Checking {len(self.markets)} markets...")
        logger.info(f"{'='*80}")

        for market in self.markets:
            try:
                logger.info(f"\n--- {market} ---")
                self.strategies[market].execute_trade()
            except Exception as e:
                logger.error(f"Error executing trade for {market}: {str(e)}")

        logger.info(f"\n{'='*80}\n")

    def get_portfolio_summary(self) -> Dict:
        """Get summary of all positions across all markets"""
        total_positions = 0
        total_value = 0.0
        active_markets = []

        for market, strategy in self.strategies.items():
            if market in strategy.positions:
                total_positions += 1
                active_markets.append(market)

        return {
            'total_markets': len(self.markets),
            'active_positions': total_positions,
            'active_markets': active_markets,
            'max_capital': self.investment_per_market * len(self.markets)
        }

    def run(self, interval: int = 60):
        """Run the multi-market trading strategy

        Args:
            interval: Check interval in seconds (default: 60)
        """
        logger.info(f"Starting multi-market strategy")
        logger.info(f"Checking {len(self.markets)} markets every {interval} seconds")

        try:
            while True:
                self.execute_all_trades()

                # Show summary
                summary = self.get_portfolio_summary()
                logger.info(f"Portfolio Summary: {summary['active_positions']}/{summary['total_markets']} markets active")
                if summary['active_markets']:
                    logger.info(f"Active markets: {', '.join(summary['active_markets'])}")

                time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("Multi-market strategy stopped by user")
            logger.info("\n=== Final Portfolio Summary ===")
            summary = self.get_portfolio_summary()
            logger.info(f"Total markets tracked: {summary['total_markets']}")
            logger.info(f"Active positions: {summary['active_positions']}")
            if summary['active_markets']:
                logger.info(f"Active in: {', '.join(summary['active_markets'])}")
