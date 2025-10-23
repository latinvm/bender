import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger('trader.virtual_wallet')

def adapt_datetime(dt: datetime) -> str:
    """Convert datetime to SQLite-compatible ISO format string"""
    return dt.isoformat()

def convert_datetime(s: bytes) -> datetime:
    """Convert SQLite datetime string back to Python datetime"""
    return datetime.fromisoformat(s.decode())

class VirtualWallet:
    """Virtual wallet for paper trading with real market data"""

    def __init__(self, db_path: str = "virtual_trades.db", initial_balance: float = 1000.0):
        """Initialize virtual wallet

        Args:
            db_path: Path to virtual trading database
            initial_balance: Starting balance in EUR (default: €1000)
        """
        # Register datetime adapter and converter
        sqlite3.register_adapter(datetime, adapt_datetime)
        sqlite3.register_converter("timestamp", convert_datetime)

        self.db_path = db_path
        self.initial_balance = initial_balance
        self._init_database()
        logger.info(f"Virtual wallet initialized at {db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with proper datetime handling"""
        return sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)

    def _init_database(self) -> None:
        """Initialize the virtual wallet database schema"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Create wallet balance table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS wallet (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    balance REAL NOT NULL,
                    initial_balance REAL NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            ''')

            # Create virtual trades table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS virtual_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    amount REAL NOT NULL,
                    entry_time TIMESTAMP NOT NULL,
                    exit_time TIMESTAMP,
                    status TEXT NOT NULL,
                    profit_loss REAL,
                    profit_loss_pct REAL,
                    entry_value REAL NOT NULL,
                    exit_value REAL,
                    fees REAL DEFAULT 0.0
                )
            ''')

            # Create virtual positions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS virtual_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market TEXT NOT NULL UNIQUE,
                    amount REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    entry_time TIMESTAMP NOT NULL,
                    entry_value REAL NOT NULL,
                    status TEXT NOT NULL
                )
            ''')

            # Create transaction log
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    balance_before REAL NOT NULL,
                    balance_after REAL NOT NULL,
                    description TEXT,
                    timestamp TIMESTAMP NOT NULL
                )
            ''')

            # Initialize wallet if it doesn't exist
            cursor.execute('SELECT COUNT(*) FROM wallet')
            if cursor.fetchone()[0] == 0:
                cursor.execute('''
                    INSERT INTO wallet (id, balance, initial_balance, created_at, updated_at)
                    VALUES (1, ?, ?, ?, ?)
                ''', (self.initial_balance, self.initial_balance, datetime.now(), datetime.now()))

                # Log initial deposit
                cursor.execute('''
                    INSERT INTO transactions (transaction_type, amount, balance_before, balance_after, description, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', ('DEPOSIT', self.initial_balance, 0.0, self.initial_balance, 'Initial balance', datetime.now()))

            conn.commit()
            logger.info(f"Virtual wallet database initialized")
        finally:
            conn.close()

    def get_balance(self) -> float:
        """Get current wallet balance"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT balance FROM wallet WHERE id = 1')
            result = cursor.fetchone()
            return result[0] if result else 0.0
        finally:
            conn.close()

    def get_initial_balance(self) -> float:
        """Get initial wallet balance"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT initial_balance FROM wallet WHERE id = 1')
            result = cursor.fetchone()
            return result[0] if result else 0.0
        finally:
            conn.close()

    def _update_balance(self, new_balance: float, conn: sqlite3.Connection) -> None:
        """Update wallet balance"""
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE wallet
            SET balance = ?, updated_at = ?
            WHERE id = 1
        ''', (new_balance, datetime.now()))

    def record_buy(self, market: str, price: float, amount: float, fee: float = 0.0) -> Tuple[bool, str]:
        """Record a virtual buy order

        Args:
            market: Market symbol (e.g., 'BTC-EUR')
            price: Buy price
            amount: Amount to buy
            fee: Trading fee (default: 0.0)

        Returns:
            Tuple of (success: bool, message: str)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Calculate total cost
            total_cost = (price * amount) + fee

            # Check if we have enough balance
            balance = self.get_balance()
            if balance < total_cost:
                return False, f"Insufficient balance. Need €{total_cost:.2f}, have €{balance:.2f}"

            # Check if we already have a position in this market
            cursor.execute('SELECT COUNT(*) FROM virtual_positions WHERE market = ? AND status = ?', (market, 'ACTIVE'))
            if cursor.fetchone()[0] > 0:
                return False, f"Already have an active position in {market}"

            # Deduct from balance
            new_balance = balance - total_cost
            self._update_balance(new_balance, conn)

            # Record transaction
            cursor.execute('''
                INSERT INTO transactions (transaction_type, amount, balance_before, balance_after, description, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', ('BUY', -total_cost, balance, new_balance, f'Buy {amount:.8f} {market} @ €{price:.6f}', datetime.now()))

            # Record trade
            cursor.execute('''
                INSERT INTO virtual_trades (market, side, entry_price, amount, entry_time, status, entry_value, fees)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (market, 'BUY', price, amount, datetime.now(), 'ACTIVE', price * amount, fee))

            # Create position
            cursor.execute('''
                INSERT INTO virtual_positions (market, amount, entry_price, entry_time, entry_value, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (market, amount, price, datetime.now(), price * amount, 'ACTIVE'))

            conn.commit()
            logger.info(f"Virtual BUY: {amount:.8f} {market} @ €{price:.6f} (Total: €{total_cost:.2f})")
            return True, f"Buy successful: {amount:.8f} {market} @ €{price:.6f}"

        except Exception as e:
            conn.rollback()
            logger.error(f"Error recording buy: {str(e)}")
            return False, f"Error: {str(e)}"
        finally:
            conn.close()

    def record_sell(self, market: str, price: float, amount: float = None, fee: float = 0.0) -> Tuple[bool, str]:
        """Record a virtual sell order

        Args:
            market: Market symbol (e.g., 'BTC-EUR')
            price: Sell price
            amount: Amount to sell (if None, sells entire position)
            fee: Trading fee (default: 0.0)

        Returns:
            Tuple of (success: bool, message: str)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Get active position
            cursor.execute('''
                SELECT id, amount, entry_price, entry_value FROM virtual_positions
                WHERE market = ? AND status = 'ACTIVE'
            ''', (market,))

            position = cursor.fetchone()
            if not position:
                return False, f"No active position in {market}"

            position_id, position_amount, entry_price, entry_value = position

            # Use full position amount if not specified
            if amount is None:
                amount = position_amount

            # Verify we have enough
            if amount > position_amount:
                return False, f"Trying to sell {amount:.8f} but only have {position_amount:.8f}"

            # Calculate proceeds
            total_proceeds = (price * amount) - fee

            # Add to balance
            balance = self.get_balance()
            new_balance = balance + total_proceeds
            self._update_balance(new_balance, conn)

            # Calculate profit/loss
            position_entry_value = entry_price * amount
            profit_loss = total_proceeds - position_entry_value
            profit_loss_pct = (profit_loss / position_entry_value) * 100

            # Record transaction
            cursor.execute('''
                INSERT INTO transactions (transaction_type, amount, balance_before, balance_after, description, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', ('SELL', total_proceeds, balance, new_balance,
                  f'Sell {amount:.8f} {market} @ €{price:.6f} (P/L: €{profit_loss:+.2f})', datetime.now()))

            # Get current buy fee from the trade
            cursor.execute('''
                SELECT fees FROM virtual_trades
                WHERE market = ? AND status = 'ACTIVE'
                ORDER BY entry_time ASC
                LIMIT 1
            ''', (market,))
            buy_fee = cursor.fetchone()[0] or 0.0

            # Update trade record with combined fees (buy fee + sell fee)
            total_fees = buy_fee + fee
            cursor.execute('''
                UPDATE virtual_trades
                SET exit_price = ?, exit_time = ?, status = ?, profit_loss = ?,
                    profit_loss_pct = ?, exit_value = ?, fees = ?
                WHERE market = ? AND status = 'ACTIVE'
                ORDER BY entry_time ASC
                LIMIT 1
            ''', (price, datetime.now(), 'CLOSED', profit_loss, profit_loss_pct, price * amount, total_fees, market))

            # Remove or update position
            if amount >= position_amount:
                # Sell entire position
                cursor.execute('DELETE FROM virtual_positions WHERE id = ?', (position_id,))
            else:
                # Partial sell - update position
                new_amount = position_amount - amount
                cursor.execute('''
                    UPDATE virtual_positions
                    SET amount = ?, entry_value = ?
                    WHERE id = ?
                ''', (new_amount, entry_price * new_amount, position_id))

            conn.commit()
            logger.info(f"Virtual SELL: {amount:.8f} {market} @ €{price:.6f} | P/L: €{profit_loss:+.2f} ({profit_loss_pct:+.2f}%)")
            return True, f"Sell successful: {amount:.8f} {market} @ €{price:.6f} | P/L: €{profit_loss:+.2f} ({profit_loss_pct:+.2f}%)"

        except Exception as e:
            conn.rollback()
            logger.error(f"Error recording sell: {str(e)}")
            return False, f"Error: {str(e)}"
        finally:
            conn.close()

    def get_active_positions(self) -> List[Dict]:
        """Get all active positions"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT market, amount, entry_price, entry_time, entry_value
                FROM virtual_positions
                WHERE status = 'ACTIVE'
                ORDER BY entry_time DESC
            ''')

            positions = []
            for row in cursor.fetchall():
                positions.append({
                    'market': row[0],
                    'amount': row[1],
                    'entry_price': row[2],
                    'entry_time': row[3],
                    'entry_value': row[4]
                })

            return positions
        finally:
            conn.close()

    def get_position_summary(self, current_prices: Dict[str, float]) -> Dict:
        """Get summary of all positions with current P/L

        Args:
            current_prices: Dict mapping market -> current price

        Returns:
            Dict with position summaries and totals
        """
        positions = self.get_active_positions()

        total_entry_value = 0.0
        total_current_value = 0.0
        position_details = []

        for pos in positions:
            market = pos['market']
            amount = pos['amount']
            entry_price = pos['entry_price']
            entry_value = pos['entry_value']

            current_price = current_prices.get(market, entry_price)
            current_value = amount * current_price
            unrealized_pl = current_value - entry_value
            unrealized_pl_pct = (unrealized_pl / entry_value * 100) if entry_value > 0 else 0.0

            total_entry_value += entry_value
            total_current_value += current_value

            position_details.append({
                'market': market,
                'amount': amount,
                'entry_price': entry_price,
                'current_price': current_price,
                'entry_value': entry_value,
                'current_value': current_value,
                'unrealized_pl': unrealized_pl,
                'unrealized_pl_pct': unrealized_pl_pct,
                'entry_time': pos['entry_time']
            })

        total_unrealized_pl = total_current_value - total_entry_value

        return {
            'positions': position_details,
            'total_entry_value': total_entry_value,
            'total_current_value': total_current_value,
            'total_unrealized_pl': total_unrealized_pl,
            'position_count': len(positions)
        }

    def get_total_profit_loss(self) -> float:
        """Get total realized profit/loss from closed trades"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COALESCE(SUM(profit_loss), 0.0) FROM virtual_trades
                WHERE status = 'CLOSED'
            ''')
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_total_costs(self) -> float:
        """Get total costs (fees) from all trades

        Returns:
            Total costs/fees paid across all trades (both active and closed)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COALESCE(SUM(fees), 0.0) FROM virtual_trades
            ''')
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_trade_history(self, limit: int = None) -> List[Dict]:
        """Get history of all trades

        Args:
            limit: Maximum number of trades to return (None for all)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = '''
                SELECT market, side, entry_price, exit_price, amount,
                       entry_time, exit_time, status, profit_loss, profit_loss_pct,
                       entry_value, exit_value, fees
                FROM virtual_trades
                ORDER BY entry_time DESC
            '''
            if limit:
                query += f' LIMIT {limit}'

            cursor.execute(query)

            trades = []
            for row in cursor.fetchall():
                trades.append({
                    'market': row[0],
                    'side': row[1],
                    'entry_price': row[2],
                    'exit_price': row[3],
                    'amount': row[4],
                    'entry_time': row[5],
                    'exit_time': row[6],
                    'status': row[7],
                    'profit_loss': row[8],
                    'profit_loss_pct': row[9],
                    'entry_value': row[10],
                    'exit_value': row[11],
                    'fees': row[12]
                })

            return trades
        finally:
            conn.close()

    def get_statistics(self) -> Dict:
        """Get trading statistics"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Get closed trade stats
            cursor.execute('''
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as winning_trades,
                    SUM(CASE WHEN profit_loss < 0 THEN 1 ELSE 0 END) as losing_trades,
                    AVG(profit_loss) as avg_profit_loss,
                    MAX(profit_loss) as max_profit,
                    MIN(profit_loss) as max_loss,
                    SUM(profit_loss) as total_pl
                FROM virtual_trades
                WHERE status = 'CLOSED'
            ''')

            stats = cursor.fetchone()
            total_trades, winning, losing, avg_pl, max_profit, max_loss, total_pl = stats

            win_rate = (winning / total_trades * 100) if total_trades > 0 else 0.0

            # Get current balance info
            balance = self.get_balance()
            initial_balance = self.get_initial_balance()
            total_return = balance - initial_balance
            total_return_pct = (total_return / initial_balance * 100) if initial_balance > 0 else 0.0

            return {
                'balance': balance,
                'initial_balance': initial_balance,
                'total_return': total_return,
                'total_return_pct': total_return_pct,
                'total_trades': total_trades or 0,
                'winning_trades': winning or 0,
                'losing_trades': losing or 0,
                'win_rate': win_rate,
                'avg_profit_loss': avg_pl or 0.0,
                'max_profit': max_profit or 0.0,
                'max_loss': max_loss or 0.0,
                'total_realized_pl': total_pl or 0.0
            }
        finally:
            conn.close()

    def reset_wallet(self, new_balance: float = None) -> None:
        """Reset wallet to initial state

        Args:
            new_balance: New starting balance (uses current initial_balance if None)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Get current initial balance if not provided
            if new_balance is None:
                new_balance = self.get_initial_balance()

            # Clear all data
            cursor.execute('DELETE FROM virtual_trades')
            cursor.execute('DELETE FROM virtual_positions')
            cursor.execute('DELETE FROM transactions')

            # Reset wallet
            cursor.execute('''
                UPDATE wallet
                SET balance = ?, initial_balance = ?, updated_at = ?
                WHERE id = 1
            ''', (new_balance, new_balance, datetime.now()))

            # Log reset
            cursor.execute('''
                INSERT INTO transactions (transaction_type, amount, balance_before, balance_after, description, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', ('RESET', new_balance, 0.0, new_balance, 'Wallet reset', datetime.now()))

            conn.commit()
            logger.info(f"Virtual wallet reset to €{new_balance:.2f}")
        finally:
            conn.close()
