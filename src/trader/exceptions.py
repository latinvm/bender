class BitvavoError(Exception):
    """Base exception for Bitvavo API errors"""
    pass

class MarketNotFoundError(BitvavoError):
    """Raised when a market is not found"""
    pass

class APIConnectionError(BitvavoError):
    """Raised when there's an issue connecting to the API"""
    pass

class OrderError(BitvavoError):
    """Raised when there's an error with order operations"""
    pass

class AuthenticationError(BitvavoError):
    """Raised when there's an authentication issue"""
    pass