"""Terminal UI for Bender Trading Bot using Textual"""

import logging
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, DataTable, RichLog
from textual.reactive import reactive
from datetime import datetime
from typing import Dict, List, Optional, Union
from trader.virtual_wallet import VirtualWallet
from trader.database import TradeDatabase
from trader.config import get_config
from trader.logger import add_tui_handler, add_tui_activity_handler

logger = logging.getLogger('trader.tui')


class BalancePanel(Static):
    """Display current balance and overall P/L"""

    balance = reactive(0.0)
    initial_balance = reactive(0.0)
    total_pl = reactive(0.0)
    total_pl_pct = reactive(0.0)
    total_invested = reactive(0.0)

    def render(self) -> str:
        pl_sign = "+" if self.total_pl >= 0 else ""
        pl_color = "green" if self.total_pl >= 0 else "red"

        total_value = self.balance + self.total_invested

        return f"""[b]Balance:[/b] €{self.balance:.2f}  |  [b]Invested:[/b] €{self.total_invested:.2f}  |  [b]Total:[/b] €{total_value:.2f}
[b]Total P/L:[/b] [{pl_color}]{pl_sign}€{self.total_pl:.2f} ({pl_sign}{self.total_pl_pct:.2f}%)[/{pl_color}]  |  [b]Initial:[/b] €{self.initial_balance:.2f}"""


class PositionsPanel(Static):
    """Display active trading positions as formatted text"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.positions: List[Dict] = []
        self.prices: Dict[str, float] = {}

    def update_positions(self, positions: List[Dict], prices: Dict[str, float]) -> None:
        """Update positions data"""
        self.positions = positions
        self.prices = prices
        self.refresh()

    def render(self) -> str:
        header = "[b]Active Positions[/b]\n" + "─" * 76 + "\n"

        if not self.positions:
            return header + "[dim]No active positions[/dim]"

        lines = [header]
        lines.append("[b]Market      Amount        Entry         Current       P/L %        P/L €[/b]")
        lines.append("─" * 76)

        for pos in self.positions:
            market = pos['market']
            amount = pos['amount']
            entry_price = pos['entry_price']
            current_price = self.prices.get(market, entry_price)

            # Calculate P/L
            pl_pct = ((current_price - entry_price) / entry_price) * 100
            pl_eur = (current_price - entry_price) * amount

            # Color coding
            pl_color = "green" if pl_pct >= 0 else "red"
            pl_sign = "+" if pl_pct >= 0 else ""

            # Format market name (fixed width)
            market_short = market.replace('-EUR', '').ljust(8)

            line = f"{market_short}  {amount:>12.2f}  €{entry_price:>10.6f}  €{current_price:>10.6f}  [{pl_color}]{pl_sign}{pl_pct:>6.2f}%[/{pl_color}]  [{pl_color}]{pl_sign}€{pl_eur:>7.2f}[/{pl_color}]"
            lines.append(line)

        return "\n".join(lines)


class StatsPanel(Static):
    """Display trading statistics"""

    total_trades = reactive(0)
    winning_trades = reactive(0)
    losing_trades = reactive(0)
    win_rate = reactive(0.0)
    avg_pl = reactive(0.0)
    current_balance = reactive(0.0)
    active_trades = reactive(0)

    def render(self) -> str:
        win_color = "green" if self.win_rate >= 50 else "yellow" if self.win_rate >= 40 else "red"

        return f"""[b]Trading Statistics[/b]
{'─' * 30}
Current Balance:  €{self.current_balance:.2f}
Active Trades:    {self.active_trades}
Total Trades:     {self.total_trades}
Winning Trades:   [green]{self.winning_trades}[/green]
Losing Trades:    [red]{self.losing_trades}[/red]
Win Rate:         [{win_color}]{self.win_rate:.1f}%[/{win_color}]
Avg P/L:          €{self.avg_pl:.2f}"""


class ActivityPanel(Static):
    """Display recent trading activity using Static instead of RichLog"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.messages: List[str] = []
        self.max_messages = 10

    def add_message(self, message: str) -> None:
        """Add a new activity message"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.messages.append(f"[dim]{timestamp}[/dim] {message}")

        # Keep only last N messages
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

        self.refresh()

    def render(self) -> str:
        header = "[b]Recent Activity[/b]\n" + "─" * 30 + "\n"
        if not self.messages:
            return header + "[dim]No activity yet[/dim]"
        return header + "\n".join(self.messages)


class LogPanel(Static):
    """Display live log output from the trader"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_lines: List[str] = []
        self.max_lines = 15  # Show last 15 log lines

    def add_log(self, message: str) -> None:
        """Add a new log line"""
        # Strip ANSI codes and format for display
        clean_msg = message.strip()
        if clean_msg:
            self.log_lines.append(clean_msg)

            # Keep only last N lines
            if len(self.log_lines) > self.max_lines:
                self.log_lines = self.log_lines[-self.max_lines:]

            self.refresh()

    def render(self) -> str:
        header = "[b]Live Trader Log[/b]\n" + "─" * 80 + "\n"
        if not self.log_lines:
            return header + "[dim]Waiting for log messages...[/dim]"
        return header + "\n".join(self.log_lines[-self.max_lines:])


class BenderTUI(App):
    """Bender Trading Bot Terminal UI"""

    CSS = """
    Screen {
        background: $surface;
    }

    #title {
        height: 1;
        content-align: center middle;
        text-style: bold;
    }

    #balance-panel {
        height: 4;
        border: solid $primary;
        padding: 1;
        margin: 1;
        background: $surface;
    }

    #positions-panel {
        border: solid $accent;
        padding: 1;
        height: 1fr;
        min-height: 5;
        margin: 0 1 1 1;
        background: $surface;
        overflow-y: auto;
    }

    #middle-container {
        height: 14;
        margin: 0 1 1 1;
    }

    #stats-panel {
        border: solid $secondary;
        padding: 1;
        width: 50%;
        height: 100%;
        background: $surface;
    }

    #activity-panel {
        border: solid $success;
        padding: 1;
        width: 50%;
        height: 100%;
        background: $surface;
        overflow-y: auto;
    }

    #log-panel {
        height: 18;
        border: solid $warning;
        padding: 1;
        margin: 0 1 1 1;
        background: $surface;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, virtual_mode: bool = True, live_wallet=None, live_db=None, live_strategy=None):
        super().__init__()
        self.virtual_mode = virtual_mode
        self.wallet: Optional[VirtualWallet] = live_wallet
        self.db: Optional[TradeDatabase] = live_db
        self.strategy = live_strategy  # Live strategy instance (EnhancedStrategy or MultiMarketStrategy)
        self.update_interval = 5  # seconds

    def compose(self) -> ComposeResult:
        """Create child widgets"""
        mode = "VIRTUAL" if self.virtual_mode else "REAL"
        yield Header(show_clock=True)
        yield Static(f"🤖 Bender Trading Bot - {mode} MODE", id="title")
        yield BalancePanel(id="balance-panel")
        yield PositionsPanel(id="positions-panel")

        with Horizontal(id="middle-container"):
            yield StatsPanel(id="stats-panel")
            yield ActivityPanel(id="activity-panel")

        yield LogPanel(id="log-panel")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize when app starts"""
        # Initialize wallet or database if not provided (standalone mode)
        if self.virtual_mode and not self.wallet:
            _, _, virtual_config = get_config()
            self.wallet = VirtualWallet(
                db_path=virtual_config.virtual_db_path,
                initial_balance=virtual_config.initial_balance
            )
        elif not self.virtual_mode and not self.db:
            _, db_config, _ = get_config()
            self.db = TradeDatabase(db_path=db_config.db_path)

        # Set up log handlers to capture logs in the TUI
        if self.strategy:  # Only in live mode
            log_panel = self.query_one("#log-panel", LogPanel)
            add_tui_handler(log_panel.add_log)

            # Set up activity handler to capture important trading events
            activity_panel = self.query_one("#activity-panel", ActivityPanel)
            add_tui_activity_handler(activity_panel.add_message)

        # Log startup
        activity = self.query_one("#activity-panel", ActivityPanel)
        mode = "virtual" if self.virtual_mode else "real"
        live_label = "LIVE" if self.strategy else "standalone"
        activity.add_message(f"[green]✓[/green] Bender TUI started ({mode} mode, {live_label})")

        # Start update loop
        self.set_interval(self.update_interval, self.update_data)

        # Initial data load
        self.update_data()

    def update_data(self) -> None:
        """Update all data from wallet or database"""
        if not self.wallet and not self.db:
            return

        try:
            balance_panel = self.query_one("#balance-panel", BalancePanel)

            if self.virtual_mode and self.wallet:
                # Virtual mode: use wallet
                balance_panel.balance = self.wallet.get_balance()
                balance_panel.initial_balance = self.wallet.get_initial_balance()

                stats = self.wallet.get_statistics()
                balance_panel.total_pl = stats['total_realized_pl']

                positions = self.wallet.get_active_positions()

                # Calculate total invested
                total_invested = sum(pos['entry_price'] * pos['amount'] for pos in positions)
                balance_panel.total_invested = total_invested

                # Calculate total P/L percentage
                total_value = balance_panel.balance + total_invested
                if balance_panel.initial_balance > 0:
                    balance_panel.total_pl_pct = ((total_value - balance_panel.initial_balance) / balance_panel.initial_balance) * 100

                # Update stats
                stats_panel = self.query_one("#stats-panel", StatsPanel)
                stats_panel.current_balance = balance_panel.balance
                stats_panel.active_trades = len(positions)
                stats_panel.total_trades = stats['total_trades']
                stats_panel.winning_trades = stats['winning_trades']
                stats_panel.losing_trades = stats['losing_trades']
                stats_panel.win_rate = stats['win_rate']
                stats_panel.avg_pl = stats['avg_profit_loss']

            else:
                # Real mode: use database
                positions = self.db.get_active_positions()

                # Real trading doesn't track balance the same way - just show invested amount
                total_invested = sum(pos['entry_price'] * pos['amount'] for pos in positions)
                balance_panel.balance = 0  # Not tracked in real mode
                balance_panel.initial_balance = 0
                balance_panel.total_invested = total_invested

                # Get total P/L from closed trades
                total_pl = self.db.get_total_profit_loss()
                balance_panel.total_pl = total_pl
                balance_panel.total_pl_pct = 0  # Can't calculate without balance tracking

                # Get real trading statistics from database
                stats_panel = self.query_one("#stats-panel", StatsPanel)
                stats_panel.current_balance = balance_panel.balance
                stats_panel.active_trades = len(positions)
                trade_stats = self.db.get_trade_statistics()
                stats_panel.total_trades = trade_stats['total_trades']
                stats_panel.winning_trades = trade_stats['winning_trades']
                stats_panel.losing_trades = trade_stats['losing_trades']
                stats_panel.win_rate = trade_stats['win_rate']
                stats_panel.avg_pl = trade_stats['avg_profit_loss']

            # Update positions with live prices from strategy cache
            positions_panel = self.query_one("#positions-panel", PositionsPanel)

            # Get current prices from strategy cache (avoids redundant API calls)
            prices = {}
            if self.strategy:
                # Try to get cached prices from strategy
                try:
                    if hasattr(self.strategy, 'get_current_prices'):
                        # MultiMarketStrategy - get all prices at once
                        prices = self.strategy.get_current_prices(use_cache=True)
                    elif hasattr(self.strategy, 'get_current_price'):
                        # Single EnhancedStrategy
                        market = self.strategy.market
                        price = self.strategy.get_current_price(use_cache=True)
                        if price is not None:
                            prices[market] = price
                except Exception as e:
                    logger.error(f"Error getting cached prices: {str(e)}")

            # Fill in any missing prices with entry prices as fallback
            for pos in positions:
                if pos['market'] not in prices:
                    prices[pos['market']] = pos['entry_price']

            positions_panel.update_positions(positions, prices)

        except Exception as e:
            activity = self.query_one("#activity-panel", ActivityPanel)
            activity.add_message(f"[red]✗[/red] Error: {str(e)}")

    def action_refresh(self) -> None:
        """Manually refresh data"""
        self.update_data()
        activity = self.query_one("#activity-panel", ActivityPanel)
        activity.add_message("[blue]🔄[/blue] Data refreshed")

    def action_quit(self) -> None:
        """Quit the application"""
        self.exit()


def run_tui(virtual_mode: bool = True):
    """Run the Bender TUI (standalone mode - reads from database)"""
    app = BenderTUI(virtual_mode=virtual_mode)
    app.run()


def run_tui_with_data(virtual_mode: bool, wallet=None, db=None, strategy=None):
    """Run the Bender TUI with live data sources

    Args:
        virtual_mode: True for virtual trading, False for real
        wallet: VirtualWallet instance (if virtual_mode=True)
        db: TradeDatabase instance (if virtual_mode=False)
        strategy: The strategy instance being run (for live updates)
    """
    app = BenderTUI(virtual_mode=virtual_mode, live_wallet=wallet, live_db=db, live_strategy=strategy)
    app.run()


if __name__ == "__main__":
    run_tui(virtual_mode=True)
