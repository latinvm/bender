import pytest
import sqlite3
from datetime import datetime
from pathlib import Path
import tempfile
import os
from trader.database import TradeDatabase

@pytest.fixture
def temp_db():
    """Create a temporary database file"""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, 'test.db')
    yield db_path
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)
    os.rmdir(temp_dir)

@pytest.fixture
def db(temp_db):
    """Create a database instance with temporary file"""
    return TradeDatabase(temp_db)

def test_database_initialization(temp_db):
    """Test database creation and schema initialization"""
    db = TradeDatabase(temp_db)
    
    # Verify tables were created
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    
    # Check trades table
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='trades'
    """)
    assert cursor.fetchone() is not None
    
    # Check positions table
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='positions'
    """)
    assert cursor.fetchone() is not None
    
    # Verify trades table schema
    cursor.execute('PRAGMA table_info(trades)')
    columns = {row[1] for row in cursor.fetchall()}
    expected_columns = {
        'id', 'market', 'entry_price', 'exit_price', 'amount',
        'entry_time', 'exit_time', 'status', 'profit_loss',
        'fee', 'entry_order_id', 'exit_order_id'
    }
    assert columns == expected_columns
    
    # Verify positions table schema
    cursor.execute('PRAGMA table_info(positions)')
    columns = {row[1] for row in cursor.fetchall()}
    expected_columns = {
        'id', 'market', 'amount', 'entry_price', 'entry_time', 'status'
    }
    assert columns == expected_columns
    
    conn.close()

def test_record_trade_entry(db):
    """Test recording a new trade entry"""
    trade_id = db.record_trade_entry('BTC-EUR', 30000.0, 1.0)
    
    # Verify trade was recorded
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    
    # Check trades table
    cursor.execute('SELECT market, entry_price, amount, status FROM trades WHERE id = ?', (trade_id,))
    trade = cursor.fetchone()
    assert trade[0] == 'BTC-EUR'
    assert trade[1] == 30000.0
    assert trade[2] == 1.0
    assert trade[3] == 'ACTIVE'
    
    # Check positions table
    cursor.execute('SELECT market, amount, entry_price, status FROM positions')
    position = cursor.fetchone()
    assert position[0] == 'BTC-EUR'
    assert position[1] == 1.0
    assert position[2] == 30000.0
    assert position[3] == 'ACTIVE'
    
    conn.close()

def test_record_trade_exit(db):
    """Test recording a trade exit"""
    # Create a trade first
    trade_id = db.record_trade_entry('BTC-EUR', 30000.0, 1.0)
    
    # Record exit
    db.record_trade_exit('BTC-EUR', 35000.0)
    
    # Verify trade was updated
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    
    # Check trade status and profit
    cursor.execute('''
        SELECT status, exit_price, profit_loss 
        FROM trades WHERE id = ?
    ''', (trade_id,))
    trade = cursor.fetchone()
    assert trade[0] == 'CLOSED'
    assert trade[1] == 35000.0
    assert trade[2] == 5000.0  # (35000 - 30000) * 1.0
    
    # Verify position was removed
    cursor.execute('SELECT COUNT(*) FROM positions WHERE market = ?', ('BTC-EUR',))
    assert cursor.fetchone()[0] == 0
    
    conn.close()

def test_get_active_positions(db):
    """Test retrieving active positions"""
    # Create multiple positions
    db.record_trade_entry('BTC-EUR', 30000.0, 1.0)
    db.record_trade_entry('ETH-EUR', 2000.0, 10.0)
    
    positions = db.get_active_positions()
    
    assert len(positions) == 2
    
    btc_position = next(p for p in positions if p['market'] == 'BTC-EUR')
    eth_position = next(p for p in positions if p['market'] == 'ETH-EUR')
    
    assert btc_position['amount'] == 1.0
    assert btc_position['entry_price'] == 30000.0
    
    assert eth_position['amount'] == 10.0
    assert eth_position['entry_price'] == 2000.0

def test_get_total_profit_loss(db):
    """Test calculating total profit/loss"""
    # Create and close multiple trades
    db.record_trade_entry('BTC-EUR', 30000.0, 1.0)
    db.record_trade_exit('BTC-EUR', 35000.0)  # +5000 profit
    
    db.record_trade_entry('ETH-EUR', 2000.0, 10.0)
    db.record_trade_exit('ETH-EUR', 1800.0)  # -2000 loss
    
    total_pl = db.get_total_profit_loss()
    assert total_pl == 3000.0  # 5000 - 2000

def test_get_trade_history(db):
    """Test retrieving trade history"""
    # Create and close multiple trades
    db.record_trade_entry('BTC-EUR', 30000.0, 1.0)
    db.record_trade_exit('BTC-EUR', 35000.0)
    
    db.record_trade_entry('ETH-EUR', 2000.0, 10.0)
    # Leave one trade open
    
    trades = db.get_trade_history()
    
    assert len(trades) == 2
    
    # Most recent trade first
    assert trades[0]['market'] == 'ETH-EUR'
    assert trades[0]['status'] == 'ACTIVE'
    assert trades[0]['exit_price'] is None
    
    assert trades[1]['market'] == 'BTC-EUR'
    assert trades[1]['status'] == 'CLOSED'
    assert trades[1]['entry_price'] == 30000.0
    assert trades[1]['exit_price'] == 35000.0
    assert trades[1]['profit_loss'] == 5000.0

def test_multiple_positions_same_market(db):
    """Test handling multiple positions in the same market"""
    # Create first position
    db.record_trade_entry('BTC-EUR', 30000.0, 1.0)
    # Create second position
    db.record_trade_entry('BTC-EUR', 31000.0, 0.5)
    
    positions = db.get_active_positions()
    assert len(positions) == 2
    
    # Close one position
    db.record_trade_exit('BTC-EUR', 32000.0)
    
    positions = db.get_active_positions()
    assert len(positions) == 1

def test_empty_database_queries(db):
    """Test queries on empty database"""
    assert db.get_active_positions() == []
    assert db.get_total_profit_loss() == 0.0
    assert db.get_trade_history() == []

def test_database_path_handling(temp_db):
    """Test database path handling"""
    # Test with string path
    db1 = TradeDatabase(temp_db)
    assert os.path.exists(temp_db)
    
    # Test with Path object
    path_obj = Path(temp_db)
    db2 = TradeDatabase(str(path_obj))
    assert os.path.exists(path_obj)