import os
from typing import NamedTuple
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

# Get project root directory (2 levels up from this file)
PROJECT_ROOT = Path(__file__).parent.parent.parent

class BitvavoConfig(NamedTuple):
    api_key: str = os.getenv('BITVAVO_API_KEY', '')
    api_secret: str = os.getenv('BITVAVO_API_SECRET', '')

class DatabaseConfig(NamedTuple):
    db_path: str = os.getenv('TRADER_DB_PATH', str(PROJECT_ROOT / 'data' / 'trades.db'))

def get_config() -> tuple[BitvavoConfig, DatabaseConfig]:
    """Get application configuration"""
    # Ensure data directory exists
    data_dir = PROJECT_ROOT / 'data'
    data_dir.mkdir(exist_ok=True)
    
    return BitvavoConfig(), DatabaseConfig()