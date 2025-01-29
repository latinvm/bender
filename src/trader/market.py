from typing import Dict, List, Optional
from trader.bitvavo import BitvavoClient

class MarketOperations:
    def __init__(self, client: BitvavoClient):
        self.client = client

    def get_balance(self) -> List[Dict]:
        """Get balance for all assets"""
        return self.client.bitvavo.balance({})

    def get_market_info(self, market: str) -> Dict:
        """Get detailed market information"""
        all_markets = self.client.bitvavo.markets({})
        for market_info in all_markets:
            if market_info['market'] == market:
                return market_info
        raise ValueError(f"Market {market} not found")

    def get_book(self, market: str, depth: int = 10) -> Dict:
        """Get order book for a market"""
        # The API expects the market as first parameter and options as second
        return self.client.bitvavo.book(market, {'depth': depth})

    def get_trades(self, market: str, limit: int = 10) -> List[Dict]:
        """Get recent trades for a market"""
        return self.client.bitvavo.trades({'market': market, 'limit': limit})

    def get_candles(self, market: str, interval: str = '1h', limit: int = 24) -> List[List]:
        """Get candlestick data
        interval options: 1m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d
        """
        return self.client.bitvavo.candles(market, interval, {'limit': limit})