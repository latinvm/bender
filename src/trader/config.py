import os
from typing import NamedTuple
from pathlib import Path
from dotenv import load_dotenv

class BitvavoConfig(NamedTuple):
    api_key: str
    api_secret: str

class DatabaseConfig(NamedTuple):
    db_path: str

def get_project_root() -> Path:
    """Get project root directory (2 levels up from this file)"""
    return Path(__file__).parent.parent.parent

# Initialize PROJECT_ROOT lazily
PROJECT_ROOT = None

def get_config(load_env: bool = True) -> tuple[BitvavoConfig, DatabaseConfig]:
    """Get application configuration
    
    Args:
        load_env: Whether to load environment variables from .env file
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
    db_path = os.getenv('TRADER_DB_PATH', str(data_dir / 'trades.db'))
    
    return BitvavoConfig(api_key, api_secret), DatabaseConfig(db_path)