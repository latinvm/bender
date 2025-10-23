from python_bitvavo_api.bitvavo import Bitvavo
import logging
import time

logger = logging.getLogger('trader.bitvavo')

def _patch_bitvavo_rate_limit():
    """
    Monkey patch the Bitvavo library to fix the negative sleep bug.

    The library's rateLimitThread can calculate negative wait times when:
    - Current time > rateLimitReset (ban already expired)
    - This causes ValueError: sleep length must be non-negative

    This patch ensures waitTime is always non-negative before sleeping.
    """
    try:
        from python_bitvavo_api.bitvavo import rateLimitThread

        # Save original method
        original_wait = rateLimitThread.waitForReset

        def patched_wait_for_reset(self, waitTime):
            """Fixed version that ensures non-negative sleep time"""
            if waitTime < 0:
                logger.warning(
                    f"Bitvavo rate limit: Negative wait time detected ({waitTime:.2f}s). "
                    f"Ban likely already expired. Setting to 0."
                )
                waitTime = 0

            # Log rate limit waits for monitoring
            if waitTime > 0:
                logger.info(f"Bitvavo rate limit: Waiting {waitTime:.2f}s for rate limit reset")

            time.sleep(waitTime)

            if time.time() < self.bitvavo.rateLimitReset:
                self.bitvavo.rateLimitRemaining = 1000
                logger.info('Bitvavo rate limit: Ban lifted, reset to 1000 requests')
            else:
                # Calculate new wait time and ensure it's non-negative
                timeToWait = max(0, (self.bitvavo.rateLimitReset / 1000) - time.time())
                if timeToWait > 0:
                    logger.warning(f'Bitvavo rate limit: Ban took longer, sleeping {timeToWait:.2f}s more')
                    self.waitForReset(timeToWait)
                else:
                    logger.info('Bitvavo rate limit: Ban expired, continuing')

        # Apply the patch
        rateLimitThread.waitForReset = patched_wait_for_reset
        logger.debug("Applied Bitvavo rate limit fix (negative sleep bug)")

    except Exception as e:
        logger.error(f"Failed to patch Bitvavo rate limit handler: {e}")
        logger.warning("Rate limit errors may still occur")

# Apply the patch when module is imported
_patch_bitvavo_rate_limit()

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
        logger.info("BitvavoClient initialized with rate limit protection")
    
    def get_time(self):
        """Test API connection by getting server time"""
        return self.bitvavo.time()
    
    def get_markets(self):
        """Get all available markets"""
        return self.bitvavo.markets({})
    
    def get_ticker_price(self, market: str):
        """Get current price for a market (e.g., 'BTC-EUR')"""
        return self.bitvavo.tickerPrice({'market': market})