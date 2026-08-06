import logging
import threading
from typing import List, Dict, Optional
from trader.enhanced_strategy import EnhancedStrategy
from trader.market import MarketOperations

logger = logging.getLogger('trader.multi_market')

class MultiMarketStrategy:
    """Run trading strategies across multiple markets simultaneously"""

    def __init__(self, market_ops: MarketOperations, markets: List[str], investment_per_market: float = 10.0, virtual_wallet=None, max_positions: int = 3, stop_loss_pct: float = 5.0, take_profit_pct: float = 15.0,
                 rsi_buy_strong: float = 40.0, rsi_buy_moderate: float = 50.0, rsi_sell: float = 60.0,
                 risk_manager=None):
        """Initialize multi-market strategy

        Args:
            market_ops: Market operations instance
            markets: List of market symbols to trade (e.g., ['FLOKI-EUR', 'PEPE-EUR'])
            investment_per_market: Investment amount per market (default: €10)
            virtual_wallet: Optional VirtualWallet instance for paper trading
            max_positions: Maximum number of concurrent positions allowed (default: 3)
            stop_loss_pct: Stop loss percentage (default: 5.0)
            take_profit_pct: Take profit percentage (default: 15.0)
            risk_manager: Optional RiskManager blocking new positions when tripped
        """
        self.market_ops = market_ops
        self.investment_per_market = investment_per_market
        self.virtual_wallet = virtual_wallet
        self.max_positions = max_positions
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.rsi_buy_strong = rsi_buy_strong
        self.rsi_buy_moderate = rsi_buy_moderate
        self.rsi_sell = rsi_sell
        self.risk_manager = risk_manager
        # Pending market re-selection, applied by the trading thread at the
        # start of the next cycle (see update_markets)
        self._pending_markets: Optional[List[str]] = None

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
            self.strategies[market] = self._create_strategy(market)

        logger.info(f"MultiMarketStrategy initialized with {len(markets)} markets")
        logger.info(f"Markets: {', '.join(markets)}")
        logger.info(f"Total capital allocation: €{investment_per_market * len(markets):.2f}")
        logger.info(f"Max concurrent positions: {max_positions}")

    def _create_strategy(self, market: str) -> EnhancedStrategy:
        return EnhancedStrategy(
            market_ops=self.market_ops,
            market=market,
            investment_amount=self.investment_per_market,
            virtual_wallet=self.virtual_wallet,
            max_positions=self.max_positions,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
            rsi_buy_strong=self.rsi_buy_strong,
            rsi_buy_moderate=self.rsi_buy_moderate,
            rsi_sell=self.rsi_sell,
            risk_manager=self.risk_manager
        )

    def update_markets(self, new_markets: List[str]) -> None:
        """Queue a new market selection (thread-safe).

        Called by the periodic rescan thread; the change is applied by the
        trading thread at the start of its next cycle so market rotation
        never races an in-flight trade. Markets holding an open position are
        never dropped - they stay managed until the position exits.
        """
        self._pending_markets = list(new_markets)
        logger.info(f"Market re-selection queued: {', '.join(new_markets)}")

    def _apply_pending_markets(self) -> None:
        pending = self._pending_markets
        if pending is None:
            return
        self._pending_markets = None

        # Keep markets that are still selected or hold an open position
        kept = [m for m in self.markets if m in pending or self.strategies[m].positions]
        dropped = [m for m in self.markets if m not in kept]
        added = [m for m in pending if m not in kept]

        for market in dropped:
            logger.info(f"Rotating out {market} (no open position, no longer selected)")
            del self.strategies[market]
        for market in added:
            logger.info(f"Rotating in {market}")
            self.strategies[market] = self._create_strategy(market)

        self.markets = kept + added
        if dropped or added:
            logger.info(f"Market rotation applied. Now trading: {', '.join(self.markets)}")
        else:
            logger.info("Market rotation: selection unchanged")

    def execute_all_trades(self):
        """Execute trading logic for all markets"""
        self._apply_pending_markets()
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

    def get_current_prices(self, use_cache: bool = True, cache_max_age: float = 30.0) -> Dict[str, float]:
        """Get current prices for all markets

        Args:
            use_cache: If True, use cached prices from strategies (default: True)
            cache_max_age: Maximum age of cache in seconds (default: 30s)

        Returns:
            Dict mapping market -> current price
        """
        prices = {}
        for market, strategy in self.strategies.items():
            price = strategy.get_current_price(use_cache=use_cache, cache_max_age=cache_max_age)
            if price is not None:
                prices[market] = price
        return prices

    def get_portfolio_summary(self) -> Dict:
        """Get summary of all positions across all markets"""
        total_positions = 0
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

    def run(self, interval: int = 60, stop_event: Optional[threading.Event] = None):
        """Run the multi-market trading strategy until stop_event is set

        Args:
            interval: Check interval in seconds (default: 60)
            stop_event: Optional event that stops the loop when set
        """
        logger.info("Starting multi-market strategy")
        logger.info(f"Checking {len(self.markets)} markets every {interval} seconds")
        stop = stop_event if stop_event is not None else threading.Event()

        try:
            while not stop.is_set():
                self.execute_all_trades()

                # Show summary
                summary = self.get_portfolio_summary()
                logger.info(f"Portfolio Summary: {summary['active_positions']}/{summary['total_markets']} markets active")
                if summary['active_markets']:
                    logger.info(f"Active markets: {', '.join(summary['active_markets'])}")

                stop.wait(interval)

            logger.info("Multi-market strategy stopped")

        except KeyboardInterrupt:
            logger.info("Multi-market strategy stopped by user")
            logger.info("\n=== Final Portfolio Summary ===")
            summary = self.get_portfolio_summary()
            logger.info(f"Total markets tracked: {summary['total_markets']}")
            logger.info(f"Active positions: {summary['active_positions']}")
            if summary['active_markets']:
                logger.info(f"Active in: {', '.join(summary['active_markets'])}")
