from typing import Dict, List
import logging
from datetime import datetime
import time
from trader.market import MarketOperations
from trader.exceptions import APIConnectionError

logger = logging.getLogger('trader.strategies')

class SimpleMAStrategy:
    def __init__(self, market_ops: MarketOperations, market: str, 
                 investment_amount: float = 10.0,  # Full €10 investment
                 short_window: int = 1,            # 1-minute short MA for quick entries
                 long_window: int = 3):            # 3-minute long MA for quick entries
        self.market_ops = market_ops
        self.market = market
        self.investment_amount = investment_amount
        self.short_window = short_window
        self.long_window = long_window
        self.prices: List[float] = []
        self.volumes: List[float] = []  # Track volume for better entries
        self.positions: Dict[str, float] = {}  # Track multiple positions
        self.entry_prices: Dict[str, float] = {}  # Track entry prices per position

    def calculate_moving_average(self, window: int) -> float:
        """Calculate moving average from recent prices"""
        if len(self.prices) < window:
            return 0.0
        return sum(self.prices[-window:]) / window

    def should_buy(self) -> bool:
        """Determine if we should buy based on strategy"""
        if len(self.prices) < self.long_window or self.market in self.positions:
            return False
            
        short_ma = self.calculate_moving_average(self.short_window)
        long_ma = self.calculate_moving_average(self.long_window)
        
        # Buy if short MA crosses above long MA and we don't have this position
        return short_ma > long_ma

    def should_sell(self) -> bool:
        """Determine if we should sell based on strategy"""
        if not self.positions or len(self.prices) < self.long_window:
            return False
            
        current_price = self.prices[-1]
        
        # More aggressive targets: 15% profit or -5% stop loss
        for market, entry_price in self.entry_prices.items():
            profit_percentage = ((current_price - entry_price) / entry_price) * 100
            if profit_percentage >= 15.0 or profit_percentage <= -5.0:
                return True
        return False

    def execute_trade(self) -> None:
        """Execute the trading strategy with portfolio approach"""
        try:
            # Get current price and volume
            ticker = self.market_ops.get_ticker(self.market)
            current_price = float(ticker['price'])
            volume_24h = float(self.market_ops.get_detailed_market_info(self.market)['volume'])
            
            self.prices.append(current_price)
            self.volumes.append(volume_24h)
            
            # Keep only needed history
            if len(self.prices) > self.long_window:
                self.prices.pop(0)
                self.volumes.pop(0)
            
            logger.info(f"Current price: €{current_price:.6f}, 24h Volume: {volume_24h:.2f}")
            
            # Check if volume is increasing (potential momentum)
            volume_increasing = len(self.volumes) > 1 and self.volumes[-1] > self.volumes[-2]
            
            if self.should_buy() and volume_increasing and len(self.positions) < 3:  # Max 3 positions
                # Get market minimums
                market_info = self.market_ops.get_market_info(self.market)
                min_base = float(market_info.get('minOrderInBaseAsset', '0'))
                min_quote = float(market_info.get('minOrderInQuoteAsset', '0'))
                
                # Calculate minimum amount that satisfies both base and quote requirements
                quote_min_amount = min_quote / current_price
                min_required = max(min_base, quote_min_amount)
                
                # Calculate our desired position size
                position_size = self.investment_amount / 3  # Split investment
                amount = position_size / current_price
                
                # Ensure we meet minimum requirements
                if amount < min_required:
                    logger.info(f"Adjusting order amount to meet minimum requirements")
                    amount = min_required * 1.1  # Add 10% to ensure we clear minimums
                    
                logger.info(f"Placing buy order for {amount:.8f} {self.market}")
                logger.info(f"Estimated value: €{(amount * current_price):.2f}")
                
                order = self.market_ops.place_market_order(self.market, 'buy', amount)
                self.positions[self.market] = amount
                self.entry_prices[self.market] = current_price
                logger.info(f"Buy order placed at €{current_price:.6f}")
                
            elif self.should_sell():
                for market in list(self.positions.keys()):  # Use list to avoid runtime modification
                    balance = self.positions[market]
                    logger.info(f"Placing sell order for {balance:.2f} {market}")
                    order = self.market_ops.place_market_order(market, 'sell', balance)
                    del self.positions[market]
                    del self.entry_prices[market]
                    logger.info(f"Sell order placed at €{current_price:.6f}")
                
        except Exception as e:
            logger.error(f"Error executing trade: {str(e)}")

    def run(self, interval: int = 60) -> None:
        """Run the trading strategy"""
        logger.info(f"Starting trading strategy for {self.market}")
        logger.info(f"Investment amount: €{self.investment_amount}")
        
        try:
            while True:
                self.execute_trade()
                time.sleep(interval)
                
        except KeyboardInterrupt:
            logger.info("Strategy stopped by user")