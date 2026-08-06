import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Optional
from trader.config import get_config

logger = logging.getLogger('trader.database')

def adapt_datetime(dt: datetime) -> str:
    """Convert datetime to SQLite-compatible ISO format string"""
    return dt.isoformat()

def convert_datetime(s: bytes) -> datetime:
    """Convert SQLite datetime string back to Python datetime"""
    return datetime.fromisoformat(s.decode())

class TradeDatabase:
    def __init__(self, db_path: str = None):
        """Initialize the trade database"""
        # Register datetime adapter and converter
        sqlite3.register_adapter(datetime, adapt_datetime)
        sqlite3.register_converter("timestamp", convert_datetime)
        
        # Use provided path or get from config
        if db_path is None:
            _, db_config, _, _ = get_config()
            self.db_path = db_config.db_path
        else:
            self.db_path = db_path
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with proper datetime handling"""
        return sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)

    def _init_database(self) -> None:
        """Initialize the database schema"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Create trades table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    amount REAL NOT NULL,
                    entry_time TIMESTAMP NOT NULL,
                    exit_time TIMESTAMP,
                    status TEXT NOT NULL,
                    profit_loss REAL
                )
            ''')
            
            # Create positions table for tracking active positions
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market TEXT NOT NULL,
                    amount REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    entry_time TIMESTAMP NOT NULL,
                    status TEXT NOT NULL
                )
            ''')

            # Additive migrations for databases created before these columns existed
            self._add_column_if_missing(cursor, 'trades', 'fee', 'REAL DEFAULT 0.0')
            self._add_column_if_missing(cursor, 'trades', 'entry_order_id', 'TEXT')
            self._add_column_if_missing(cursor, 'trades', 'exit_order_id', 'TEXT')
            self._add_column_if_missing(cursor, 'positions', 'trade_id', 'INTEGER')

            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _add_column_if_missing(cursor: sqlite3.Cursor, table: str, column: str, definition: str) -> None:
        cursor.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cursor.fetchall()}
        if column not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def record_trade_entry(self, market: str, entry_price: float, amount: float,
                           fee: float = 0.0, order_id: Optional[str] = None) -> int:
        """Record a new trade entry"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO trades (market, entry_price, amount, entry_time, status, fee, entry_order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (market, entry_price, amount, datetime.now(), 'ACTIVE', fee, order_id))

            trade_id = cursor.lastrowid

            # Record position, linked to its trade row so the exit can match
            # it unambiguously (market+amount+price matching is ambiguous for
            # duplicate entries)
            cursor.execute('''
                INSERT INTO positions (market, amount, entry_price, entry_time, status, trade_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (market, amount, entry_price, datetime.now(), 'ACTIVE', trade_id))

            conn.commit()
            return trade_id
        finally:
            conn.close()

    def record_trade_exit(self, market: str, exit_price: float,
                          fee: float = 0.0, order_id: Optional[str] = None) -> None:
        """Record a trade exit and calculate profit/loss (net of recorded fees)"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Get oldest active trade for this market. Prefer the explicit
            # trade_id link; fall back to attribute matching for positions
            # recorded before the trade_id column existed.
            cursor.execute('''
                SELECT t.id, t.entry_price, t.amount, t.fee, p.id as position_id
                FROM trades t
                JOIN positions p ON (p.trade_id = t.id)
                    OR (p.trade_id IS NULL
                        AND p.market = t.market
                        AND p.amount = t.amount
                        AND p.entry_price = t.entry_price)
                WHERE t.market = ? AND t.status = 'ACTIVE'
                ORDER BY t.entry_time ASC
                LIMIT 1
            ''', (market,))

            trade = cursor.fetchone()
            if trade:
                trade_id, entry_price, amount, entry_fee, position_id = trade

                # Calculate profit/loss net of entry and exit fees
                total_fees = (entry_fee or 0.0) + fee
                profit_loss = (exit_price - entry_price) * amount - total_fees

                # Update trade record
                cursor.execute('''
                    UPDATE trades
                    SET exit_price = ?, exit_time = ?, status = ?, profit_loss = ?,
                        fee = ?, exit_order_id = ?
                    WHERE id = ?
                ''', (exit_price, datetime.now(), 'CLOSED', profit_loss, total_fees, order_id, trade_id))
                
                # Remove specific position
                cursor.execute('''
                    DELETE FROM positions
                    WHERE id = ?
                ''', (position_id,))
                
                conn.commit()
        finally:
            conn.close()

    def get_active_positions(self) -> List[Dict[str, float]]:
        """Get all active positions"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT market, amount, entry_price FROM positions
                WHERE status = 'ACTIVE'
            ''')
            
            positions = []
            for row in cursor.fetchall():
                positions.append({
                    'market': row[0],
                    'amount': row[1],
                    'entry_price': row[2]
                })
            
            return positions
        finally:
            conn.close()

    def get_total_profit_loss(self) -> float:
        """Calculate total profit/loss from all closed trades"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COALESCE(SUM(profit_loss), 0.0) FROM trades
                WHERE status = 'CLOSED'
            ''')

            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_profit_loss_since(self, since: datetime) -> float:
        """Realized profit/loss from trades closed at or after `since`"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COALESCE(SUM(profit_loss), 0.0) FROM trades
                WHERE status = 'CLOSED' AND exit_time >= ?
            ''', (since,))
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_total_costs(self) -> float:
        """Get total costs (fees) from active trades only.

        Closed trade fees are already included in realized P/L, so only
        fees on open positions are returned (mirrors VirtualWallet).
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COALESCE(SUM(fee), 0.0) FROM trades
                WHERE status = 'ACTIVE'
            ''')
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_trade_history(self) -> List[Dict]:
        """Get history of all trades"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT market, entry_price, exit_price, amount,
                       entry_time, exit_time, status, profit_loss
                FROM trades
                ORDER BY entry_time DESC
            ''')

            trades = []
            for row in cursor.fetchall():
                trades.append({
                    'market': row[0],
                    'entry_price': row[1],
                    'exit_price': row[2],
                    'amount': row[3],
                    'entry_time': row[4],
                    'exit_time': row[5],
                    'status': row[6],
                    'profit_loss': row[7]
                })

            return trades
        finally:
            conn.close()

    def get_trade_statistics(self) -> Dict:
        """Get trading statistics summary

        Returns:
            Dict with keys: total_trades, winning_trades, losing_trades,
            win_rate, avg_profit_loss, max_profit, max_loss
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Get closed trades statistics
            cursor.execute('''
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN profit_loss < 0 THEN 1 ELSE 0 END) as losses,
                    AVG(profit_loss) as avg_pl,
                    MAX(profit_loss) as max_profit,
                    MIN(profit_loss) as min_loss
                FROM trades
                WHERE status = 'CLOSED'
            ''')

            row = cursor.fetchone()

            total_trades = row[0] or 0
            winning_trades = row[1] or 0
            losing_trades = row[2] or 0
            avg_pl = row[3] or 0.0
            max_profit = row[4] or 0.0
            max_loss = row[5] or 0.0

            # Calculate win rate
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

            return {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': losing_trades,
                'win_rate': win_rate,
                'avg_profit_loss': avg_pl,
                'max_profit': max_profit,
                'max_loss': max_loss
            }
        finally:
            conn.close()