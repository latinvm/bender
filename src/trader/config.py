import os
from typing import NamedTuple, Optional
from pathlib import Path
from dotenv import load_dotenv

class BitvavoConfig(NamedTuple):
    api_key: str
    api_secret: str
    operator_id: Optional[int] = None

class DatabaseConfig(NamedTuple):
    db_path: str

class VirtualTradingConfig(NamedTuple):
    enabled: bool
    virtual_db_path: str
    initial_balance: float
    trading_fee_pct: float
    max_positions: int

class TradingStrategyConfig(NamedTuple):
    trade_amount: float
    stop_loss_pct: float
    take_profit_pct: float
    max_coin_price: float
    strategy_interval: int
    market_cache_hours: int
    max_candidates: int
    rsi_buy_strong: float = 40.0     # Signal 1: buy when RSI below this
    rsi_buy_moderate: float = 50.0   # Signal 2: buy when RSI below this AND MACD bullish
    rsi_sell: float = 60.0           # Sell when RSI above this AND MACD bearish
    max_daily_loss_pct: float = 10.0  # Halt new buys when today's realized loss exceeds this % of capital (0 disables)
    max_drawdown_pct: float = 25.0    # Halt new buys when total realized loss exceeds this % of capital (0 disables)

def get_project_root() -> Path:
    """Get project root directory (2 levels up from this file)"""
    return Path(__file__).parent.parent.parent

# Initialize PROJECT_ROOT lazily
PROJECT_ROOT = None

def get_config(load_env: bool = True) -> tuple[BitvavoConfig, DatabaseConfig, VirtualTradingConfig, TradingStrategyConfig]:
    """Get application configuration

    Args:
        load_env: Whether to load environment variables from .env file

    Returns:
        Tuple of (BitvavoConfig, DatabaseConfig, VirtualTradingConfig, TradingStrategyConfig)
    """
    global PROJECT_ROOT

    # Load environment variables if requested
    if load_env:
        load_dotenv()

    if PROJECT_ROOT is None:
        PROJECT_ROOT = get_project_root()

    # Ensure data directory exists
    data_dir = PROJECT_ROOT / 'data'
    data_dir.mkdir(exist_ok=True)

    # Get configuration from environment
    api_key = os.getenv('BITVAVO_API_KEY', '')
    api_secret = os.getenv('BITVAVO_API_SECRET', '')
    operator_id_str = os.getenv('BITVAVO_OPERATOR_ID')
    operator_id = None
    if operator_id_str and operator_id_str.isdigit():
        operator_id = int(operator_id_str)

    db_path = os.getenv('TRADER_DB_PATH', str(data_dir / 'trades.db'))

    # Virtual trading configuration
    virtual_enabled = os.getenv('VIRTUAL_TRADING', 'false').lower() in ('true', '1', 'yes')
    virtual_db_path = os.getenv('VIRTUAL_DB_PATH', str(data_dir / 'virtual_trades.db'))
    virtual_initial_balance = float(os.getenv('VIRTUAL_INITIAL_BALANCE', '1000.0'))
    virtual_trading_fee = float(os.getenv('VIRTUAL_TRADING_FEE', '0.25'))
    max_positions = int(os.getenv('MAX_POSITIONS', '3'))

    # Trading strategy configuration
    trade_amount = float(os.getenv('TRADE_AMOUNT', '10.0'))
    stop_loss_pct = float(os.getenv('STOP_LOSS_PCT', '5.0'))
    take_profit_pct = float(os.getenv('TAKE_PROFIT_PCT', '15.0'))
    max_coin_price = float(os.getenv('MAX_COIN_PRICE', '10.0'))
    strategy_interval = int(os.getenv('STRATEGY_INTERVAL', '60'))
    market_cache_hours = int(os.getenv('MARKET_CACHE_HOURS', '6'))
    max_candidates = int(os.getenv('MAX_CANDIDATES', '30'))
    rsi_buy_strong = float(os.getenv('RSI_BUY_STRONG', '40.0'))
    rsi_buy_moderate = float(os.getenv('RSI_BUY_MODERATE', '50.0'))
    rsi_sell = float(os.getenv('RSI_SELL', '60.0'))
    max_daily_loss_pct = float(os.getenv('MAX_DAILY_LOSS_PCT', '10.0'))
    max_drawdown_pct = float(os.getenv('MAX_DRAWDOWN_PCT', '25.0'))

    return (
        BitvavoConfig(api_key, api_secret, operator_id),
        DatabaseConfig(db_path),
        VirtualTradingConfig(virtual_enabled, virtual_db_path, virtual_initial_balance, virtual_trading_fee, max_positions),
        TradingStrategyConfig(trade_amount, stop_loss_pct, take_profit_pct, max_coin_price, strategy_interval,
                              market_cache_hours, max_candidates, rsi_buy_strong, rsi_buy_moderate, rsi_sell,
                              max_daily_loss_pct, max_drawdown_pct)
    )