from python_bitvavo_api.bitvavo import Bitvavo
import logging
import time

from trader.exceptions import AuthenticationError, BitvavoError, MarketNotFoundError, RateLimitError

logger = logging.getLogger('trader.bitvavo')


def check_bitvavo_response(response, context: str = ''):
    """Validate a Bitvavo API response and raise typed exceptions on errors.

    The Bitvavo client library does not raise on API errors - it returns an
    error dict ({'errorCode': ..., 'error': ...}) where a list or data dict
    was expected. Every API call must pass its response through this check,
    otherwise errors surface later as confusing KeyErrors.

    Returns the response unchanged when it is not an error.
    """
    if isinstance(response, dict) and ('errorCode' in response or 'error' in response):
        code = response.get('errorCode')
        message = response.get('error', str(response))
        prefix = f"{context}: " if context else ""

        if code in (105, 110) or 'rate limit' in str(message).lower():
            raise RateLimitError(f"{prefix}rate limit exceeded (code {code}): {message}")
        if (isinstance(code, int) and 300 <= code < 400) or 'UNAUTHORIZED' in str(message).upper():
            raise AuthenticationError(f"{prefix}authentication failed (code {code}): {message}")
        if code == 205 or 'market' in str(message).lower() and 'not' in str(message).lower():
            raise MarketNotFoundError(f"{prefix}{message}")
        raise BitvavoError(f"{prefix}API error (code {code}): {message}")
    return response

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