from typing import Dict
import logging
from datetime import datetime
from trader.market import MarketOperations

logger = logging.getLogger('trader.strategy')

class TradingStrategy:
    def __init__(self, market_ops: MarketOperations, market: str):
        self.market_ops = market_ops
        self.market = market
        self.is_running = False
    
    def analyze_market(self) -> Dict:
        """Analyze current market conditions"""
        try:
            ticker = self.market_ops.get_ticker(self.market)
            current_price = float(ticker['price'])
            
            book = self.market_ops.get_book(self.market, 5)
            best_bid = float(book['bids'][0][0])
            best_ask = float(book['asks'][0][0])
            
            return {
                'current_price': current_price,
                'best_bid': best_bid,
                'best_ask': best_ask,
                'spread': best_ask - best_bid,
                'timestamp': datetime.now()
            }
        except Exception as e:
            logger.error(f"Error analyzing market: {str(e)}")
            raise