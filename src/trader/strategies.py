from typing import Dict, List
import logging
from datetime import datetime
import time
from trader.market import MarketOperations
from trader.exceptions import APIConnectionError

logger = logging.getLogger('trader.strategies')

class SimpleMAStrategy:
    def __init__(self, market_ops: MarketOperations, market: str, 
                 investment_amount: float = 5.0,   # Reduced to 5 EUR
                 short_window: int = 5,            # 5-minute short MA
                 long_window: int = 15):           # 15-minute long MA
        self.market_ops = market_ops
        self.market = market
        self.investment_amount = investment_amount
        self.short_window = short_window
        self.long_window = long_window
        self.prices: List[float] = []
        self.position_open = False
        self.entry_price = 0.0

    def calculate_moving_average(self, window: int) -> float:
        """Calculate moving average from recent prices"""
        if len(self.prices) < window:
            return 0.0
        return sum(self.prices[-window:]) / window

    def should_buy(self) -> bool:
        """Determine if we should buy based on strategy"""
        if len(self.prices) < self.long_window:
            return False
            
        short_ma = self.calculate_moving_average(self.short_window)
        long_ma = self.calculate_moving_average(self.long_window)
        
        # Buy if short MA crosses above long MA
        return short_ma > long_ma and not self.position_open

    def should_sell(self) -> bool:
        """Determine if we should sell based on strategy"""
        if not self.position_open or len(self.prices) < self.long_window:
            return False
            
        current_price = self.prices[-1]
        
        # Adjusted profit target to 3% and stop loss to -1.5%
        profit_percentage = ((current_price - self.entry_price) / self.entry_price) * 100
        return profit_percentage >= 3.0 or profit_percentage <= -1.5

    def execute_trade(self) -> None:
        """Execute the trading strategy"""
        try:
            # Get current price
            ticker = self.market_ops.get_ticker(self.market)
            current_price = float(ticker['price'])
            self.prices.append(current_price)
            
            # Keep only needed price history
            if len(self.prices) > self.long_window:
                self.prices.pop(0)
            
            logger.info(f"Current price: €{current_price:.6f}")
            
            if self.should_buy():
                amount = self.investment_amount / current_price
                logger.info(f"Placing buy order for {amount:.2f} {self.market}")
                order = self.market_ops.place_market_order(self.market, 'buy', amount)
                self.position_open = True
                self.entry_price = current_price
                logger.info(f"Buy order placed at €{current_price:.6f}")
                
            elif self.should_sell() and self.position_open:
                # Get current position amount
                balance = self.market_ops.get_available_balance('VET')
                logger.info(f"Placing sell order for {balance:.2f} {self.market}")
                order = self.market_ops.place_market_order(self.market, 'sell', balance)
                self.position_open = False
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