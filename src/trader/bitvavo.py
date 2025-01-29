from python_bitvavo_api.bitvavo import Bitvavo

class BitvavoClient:
    def __init__(self, api_key: str = '', api_secret: str = ''):
        self.bitvavo = Bitvavo({
            'APIKEY': api_key,
            'APISECRET': api_secret,
            'RESTURL': 'https://api.bitvavo.com/v2',
            'WSURL': 'wss://ws.bitvavo.com/v2/',
            'ACCESSWINDOW': 10000,
            'DEBUGGING': False
        })
    
    def get_time(self):
        """Test API connection by getting server time"""
        return self.bitvavo.time()
    
    def get_markets(self):
        """Get all available markets"""
        return self.bitvavo.markets({})
    
    def get_ticker_price(self, market: str):
        """Get current price for a market (e.g., 'BTC-EUR')"""
        return self.bitvavo.tickerPrice({'market': market})