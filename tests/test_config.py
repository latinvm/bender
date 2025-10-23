import os
import pytest
from pathlib import Path
import tempfile
import shutil
from dotenv import load_dotenv

# Import only the module to avoid name conflicts
import trader.config

@pytest.fixture
def clean_env():
    """Provide a clean environment for testing"""
    original_env = dict(os.environ)
    for key in list(os.environ.keys()):
        if key.startswith('BITVAVO_') or key == 'TRADER_DB_PATH':
            del os.environ[key]
    yield
    os.environ.clear()
    os.environ.update(original_env)

@pytest.fixture
def temp_project_root():
    """Create a temporary project root directory"""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)

def test_security_defaults(clean_env):
    """Test security-critical default values"""
    # Get config without loading any env file
    bitvavo_config, _, _, _ = trader.config.get_config(load_env=False)

    # Critical security check: ensure no default credentials
    assert bitvavo_config.api_key == ''
    assert bitvavo_config.api_secret == ''

def test_credential_loading(clean_env):
    """Test secure loading of trading credentials"""
    # Set test credentials
    test_key = 'test_key'
    test_secret = 'test_secret'
    os.environ['BITVAVO_API_KEY'] = test_key
    os.environ['BITVAVO_API_SECRET'] = test_secret

    # Verify credentials are loaded correctly
    bitvavo_config, _, _, _ = trader.config.get_config(load_env=False)
    assert bitvavo_config.api_key == test_key
    assert bitvavo_config.api_secret == test_secret

    # Verify configuration is immutable (security feature)
    with pytest.raises(AttributeError):
        bitvavo_config.api_key = 'new_value'

def test_trade_data_storage(clean_env, temp_project_root, monkeypatch):
    """Test trade data storage configuration"""
    # Configure test environment
    monkeypatch.setattr('trader.config.PROJECT_ROOT', temp_project_root)

    # Get config and verify data storage setup
    _, db_config, _, _ = trader.config.get_config(load_env=False)

    # Verify data directory exists and is properly configured
    data_dir = temp_project_root / 'data'
    assert data_dir.exists(), "Trade data directory must exist"
    assert data_dir.is_dir(), "Trade data location must be a directory"
    assert str(Path(db_config.db_path)) == str(data_dir / 'trades.db')

    # Verify database config is immutable
    with pytest.raises(AttributeError):
        db_config.db_path = 'new_path'

def test_trading_strategy_config(clean_env):
    """Test trading strategy configuration defaults"""
    # Get config without loading any env file
    _, _, _, strategy_config = trader.config.get_config(load_env=False)

    # Verify default values
    assert strategy_config.trade_amount == 10.0
    assert strategy_config.stop_loss_pct == 5.0
    assert strategy_config.take_profit_pct == 15.0
    assert strategy_config.max_coin_price == 10.0
    assert strategy_config.strategy_interval == 60
    assert strategy_config.market_cache_hours == 6
    assert strategy_config.max_candidates == 30

    # Verify configuration is immutable
    with pytest.raises(AttributeError):
        strategy_config.trade_amount = 20.0

def test_trading_strategy_config_custom_values(clean_env):
    """Test custom trading strategy configuration values"""
    # Set custom values
    os.environ['TRADE_AMOUNT'] = '25.0'
    os.environ['STOP_LOSS_PCT'] = '3.0'
    os.environ['TAKE_PROFIT_PCT'] = '20.0'
    os.environ['MAX_COIN_PRICE'] = '5.0'
    os.environ['STRATEGY_INTERVAL'] = '120'
    os.environ['MARKET_CACHE_HOURS'] = '12'
    os.environ['MAX_CANDIDATES'] = '50'

    # Get config and verify custom values are loaded
    _, _, _, strategy_config = trader.config.get_config(load_env=False)

    assert strategy_config.trade_amount == 25.0
    assert strategy_config.stop_loss_pct == 3.0
    assert strategy_config.take_profit_pct == 20.0
    assert strategy_config.max_coin_price == 5.0
    assert strategy_config.strategy_interval == 120
    assert strategy_config.market_cache_hours == 12
    assert strategy_config.max_candidates == 50