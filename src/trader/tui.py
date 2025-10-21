"""Terminal UI for Bender Trading Bot using Textual"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, DataTable, Log
from textual.reactive import reactive
from datetime import datetime
from typing import Dict, List, Optional
import asyncio
from trader.virtual_wallet import VirtualWallet
from trader.config import get_config


class BalancePanel(Static):
    """Display current balance and overall P/L"""

    balance = reactive(0.0)
    initial_balance = reactive(0.0)
    total_pl = reactive(0.0)
    total_pl_pct = reactive(0.0)

    def render(self) -> str:
        pl_sign = "+" if self.total_pl >= 0 else ""
        pl_color = "green" if self.total_pl >= 0 else "red"

        return f"""[bold]💰 Balance:[/bold] €{self.balance:.2f}
[bold]📊 Total P/L:[/bold] [{pl_color}]{pl_sign}€{self.total_pl:.2f} ({pl_sign}{self.total_pl_pct:.2f}%)[/{pl_color}]
[bold]🏦 Initial:[/bold] €{self.initial_balance:.2f}"""


class PositionsTable(Static):
    """Display active trading positions"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.positions: List[Dict] = []

    def compose(self) -> ComposeResult:
        yield DataTable()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Market", "Amount", "Entry Price", "Current Price", "P/L %", "P/L €")
        table.cursor_type = "row"

    def update_positions(self, positions: List[Dict], prices: Dict[str, float]) -> None:
        """Update the positions table with current data"""
        table = self.query_one(DataTable)
        table.clear()

        self.positions = positions

        for pos in positions:
            market = pos['market']
            amount = pos['amount']
            entry_price = pos['entry_price']
            current_price = prices.get(market, entry_price)

            # Calculate P/L
            pl_pct = ((current_price - entry_price) / entry_price) * 100
            pl_eur = (current_price - entry_price) * amount

            # Color coding
            pl_color = "green" if pl_pct >= 0 else "red"
            pl_sign = "+" if pl_pct >= 0 else ""

            table.add_row(
                market,
                f"{amount:.2f}",
                f"€{entry_price:.6f}",
                f"€{current_price:.6f}",
                f"[{pl_color}]{pl_sign}{pl_pct:.2f}%[/{pl_color}]",
                f"[{pl_color}]{pl_sign}€{pl_eur:.2f}[/{pl_color}]"
            )


class StatsPanel(Static):
    """Display trading statistics"""

    total_trades = reactive(0)
    winning_trades = reactive(0)
    losing_trades = reactive(0)
    win_rate = reactive(0.0)
    avg_pl = reactive(0.0)

    def render(self) -> str:
        win_color = "green" if self.win_rate >= 50 else "yellow" if self.win_rate >= 40 else "red"

        return f"""[bold]📈 Trading Statistics[/bold]
━━━━━━━━━━━━━━━━━━━━━━
Total Trades:    {self.total_trades}
Winning Trades:  [{win_color}]{self.winning_trades}[/{win_color}]
Losing Trades:   {self.losing_trades}
Win Rate:        [{win_color}]{self.win_rate:.1f}%[/{win_color}]
Avg P/L:         €{self.avg_pl:.2f}"""


class ActivityLog(Static):
    """Display recent trading activity"""

    def compose(self) -> ComposeResult:
        yield Log(highlight=True, auto_scroll=True)

    def add_activity(self, message: str) -> None:
        """Add a new activity message"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log = self.query_one(Log)
        log.write_line(f"[dim]{timestamp}[/dim] {message}")


class BenderTUI(App):
    """Bender Trading Bot Terminal UI"""

    CSS = """
    Screen {
        background: $surface;
    }

    #balance-panel {
        height: 5;
        border: solid $primary;
        padding: 1;
        margin: 1;
    }

    #positions-container {
        height: 1fr;
        border: solid $accent;
        padding: 1;
        margin: 1;
    }

    #stats-panel {
        width: 30;
        border: solid $secondary;
        padding: 1;
        margin: 1;
    }

    #activity-log {
        height: 15;
        border: solid $success;
        padding: 1;
        margin: 1;
    }

    DataTable {
        height: 100%;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, virtual_mode: bool = True):
        super().__init__()
        self.virtual_mode = virtual_mode
        self.wallet: Optional[VirtualWallet] = None
        self.update_interval = 5  # seconds

    def compose(self) -> ComposeResult:
        """Create child widgets"""
        mode = "VIRTUAL" if self.virtual_mode else "REAL"
        yield Header(show_clock=True)
        yield Container(
            Static(f"[bold]🤖 Bender Trading Bot - {mode} MODE[/bold]", id="title"),
            BalancePanel(id="balance-panel"),
            Horizontal(
                Vertical(
                    Static("[bold]📊 Active Positions[/bold]"),
                    PositionsTable(id="positions-table"),
                    id="positions-container"
                ),
                StatsPanel(id="stats-panel"),
            ),
            ActivityLog(id="activity-log"),
        )
        yield Footer()

    def on_mount(self) -> None:
        """Initialize when app starts"""
        # Initialize wallet
        if self.virtual_mode:
            _, _, virtual_config = get_config()
            self.wallet = VirtualWallet(
                db_path=virtual_config.virtual_db_path,
                initial_balance=virtual_config.initial_balance
            )

        # Log startup
        activity = self.query_one(ActivityLog)
        activity.add_activity("[bold green]✓[/bold green] Bender TUI started")

        # Start update loop
        self.set_interval(self.update_interval, self.update_data)

        # Initial data load
        self.update_data()

    def update_data(self) -> None:
        """Update all data from wallet"""
        if not self.wallet:
            return

        try:
            # Update balance
            balance_panel = self.query_one("#balance-panel", BalancePanel)
            balance_panel.balance = self.wallet.get_balance()
            balance_panel.initial_balance = self.wallet.get_initial_balance()

            # Get statistics
            stats = self.wallet.get_statistics()
            balance_panel.total_pl = stats['total_realized_pl']

            # Calculate total P/L percentage
            if balance_panel.initial_balance > 0:
                total_value = balance_panel.balance + sum(
                    pos['entry_price'] * pos['amount']
                    for pos in self.wallet.get_active_positions()
                )
                balance_panel.total_pl_pct = ((total_value - balance_panel.initial_balance) / balance_panel.initial_balance) * 100

            # Update positions
            positions = self.wallet.get_active_positions()
            positions_table = self.query_one("#positions-table", PositionsTable)

            # Get current prices (for now use entry prices - we'll improve this)
            prices = {pos['market']: pos['entry_price'] for pos in positions}
            positions_table.update_positions(positions, prices)

            # Update stats
            stats_panel = self.query_one("#stats-panel", StatsPanel)
            stats_panel.total_trades = stats['total_trades']
            stats_panel.winning_trades = stats['winning_trades']
            stats_panel.losing_trades = stats['losing_trades']
            stats_panel.win_rate = stats['win_rate']
            stats_panel.avg_pl = stats['avg_profit_loss']

        except Exception as e:
            activity = self.query_one(ActivityLog)
            activity.add_activity(f"[bold red]✗[/bold red] Error updating data: {str(e)}")

    def action_refresh(self) -> None:
        """Manually refresh data"""
        self.update_data()
        activity = self.query_one(ActivityLog)
        activity.add_activity("[bold blue]🔄[/bold blue] Data refreshed")

    def action_quit(self) -> None:
        """Quit the application"""
        self.exit()


def run_tui(virtual_mode: bool = True):
    """Run the Bender TUI"""
    app = BenderTUI(virtual_mode=virtual_mode)
    app.run()


if __name__ == "__main__":
    run_tui(virtual_mode=True)
