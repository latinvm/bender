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

def get_project_root() -> Path:
    """Get project root directory (2 levels up from this file)"""
    return Path(__file__).parent.parent.parent

# Initialize PROJECT_ROOT lazily
PROJECT_ROOT = None

def get_config(load_env: bool = True) -> tuple[BitvavoConfig, DatabaseConfig, VirtualTradingConfig]:
    """Get application configuration

    Args:
        load_env: Whether to load environment variables from .env file

    Returns:
        Tuple of (BitvavoConfig, DatabaseConfig, VirtualTradingConfig)
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

    return (
        BitvavoConfig(api_key, api_secret, operator_id),
        DatabaseConfig(db_path),
        VirtualTradingConfig(virtual_enabled, virtual_db_path, virtual_initial_balance, virtual_trading_fee)
    )