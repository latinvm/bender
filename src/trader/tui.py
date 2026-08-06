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
from trader.formatting import format_currency, format_percentage, calculate_max_width

logger = logging.getLogger('trader.tui')


class BalancePanel(Static):
    """Display current balance and invested amounts"""

    balance = reactive(0.0)
    total_invested = reactive(0.0)
    total_costs = reactive(0.0)
    realized_pl = reactive(0.0)
    initial_balance = reactive(0.0)

    def render(self) -> str:
        # Total capital = balance + invested
        # Do NOT add costs - they are already deducted from balance
        total_value = self.balance + self.total_invested

        # Color code the realized P/L
        pl_color = "green" if self.realized_pl >= 0 else "red"
        pl_sign = "+" if self.realized_pl >= 0 else ""

        # Show checksum: Total + Active Costs - Realized P/L should equal Initial Balance
        # Because:
        # - Realized P/L already includes fees from closed trades
        # - Active costs are fees paid on open positions (not yet in realized P/L)
        # - Balance already has all fees deducted via transactions
        checksum = total_value + self.total_costs - self.realized_pl
        checksum_match = abs(checksum - self.initial_balance) < 0.02
        checksum_indicator = "[green]✓[/green]" if checksum_match else "[red]✗[/red]"

        return f""" [b]Balance:[/b] €{self.balance:.2f}  |  [b]Invested:[/b] €{self.total_invested:.2f}  |  [b]Costs:[/b] €{self.total_costs:.2f}  |  [b]Realized P/L:[/b] [{pl_color}]{pl_sign}€{self.realized_pl:.2f}[/{pl_color}]  |  [b]Total:[/b] €{total_value:.2f}  |  [b]Initial:[/b] €{self.initial_balance:.2f} {checksum_indicator}"""


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
        logger.debug(f"PositionsPanel: Updating {len(positions)} positions with {len(prices)} prices")
        for market, price in prices.items():
            logger.debug(f"  {market}: €{price:.6f}")
        self.refresh()

    def render(self) -> str:
        header = "[b]Active Positions[/b]\n" + "─" * 76

        if not self.positions:
            return header + "\n[dim]No active positions[/dim]"

        # First pass: calculate all P/L values to determine max widths
        pl_values = []
        for pos in self.positions:
            entry_price = pos['entry_price']
            current_price = self.prices.get(pos['market'], entry_price)
            pl_pct = ((current_price - entry_price) / entry_price) * 100
            pl_eur = (current_price - entry_price) * pos['amount']
            pl_values.append((pl_pct, pl_eur))

        # Calculate max widths for P/L columns
        pct_width = calculate_max_width([pct for pct, _ in pl_values])
        eur_width = calculate_max_width([eur for _, eur in pl_values])

        lines = [header]
        lines.append("[b]Market      Amount        Entry         Current       P/L %        P/L €[/b]")
        lines.append("─" * 76)

        # Second pass: format with consistent widths
        for pos, (pl_pct, pl_eur) in zip(self.positions, pl_values):
            market = pos['market']
            amount = pos['amount']
            entry_price = pos['entry_price']
            current_price = self.prices.get(market, entry_price)

            # Color coding
            pl_color = "green" if pl_pct >= 0 else "red"
            pct_sign = "+" if pl_pct >= 0 else "-"
            eur_sign = "+" if pl_eur >= 0 else "-"

            # Format market name (fixed width)
            market_short = market.replace('-EUR', '').ljust(8)

            # Format P/L with consistent widths
            formatted_pct = format_percentage(pl_pct, pct_sign, pct_width)
            formatted_eur = format_currency(pl_eur, eur_sign, eur_width)

            line = f"{market_short}  {amount:>12.2f}  €{entry_price:>10.6f}  €{current_price:>10.6f}  [{pl_color}]{formatted_pct:>10}[/{pl_color}]  [{pl_color}]{formatted_eur:>10}[/{pl_color}]"
            lines.append(line)

        return "\n".join(lines)


class StatsPanel(Static):
    """Display trading statistics"""

    total_trades = reactive(0)
    winning_trades = reactive(0)
    losing_trades = reactive(0)
    win_rate = reactive(0.0)
    avg_pl = reactive(0.0)
    total_pl = reactive(0.0)
    current_unrealized_pl = reactive(0.0)
    active_trades = reactive(0)

    def render(self) -> str:
        win_color = "green" if self.win_rate >= 50 else "yellow" if self.win_rate >= 40 else "red"

        # Calculate max width for all P/L values to ensure consistent spacing
        pl_values = [self.current_unrealized_pl, self.avg_pl, self.total_pl]
        max_width = calculate_max_width(pl_values)

        # Format P/L values with consistent widths
        current_pl_color = "green" if self.current_unrealized_pl >= 0 else "red"
        current_pl_sign = "+" if self.current_unrealized_pl >= 0 else "-"
        formatted_current_pl = format_currency(self.current_unrealized_pl, current_pl_sign, max_width)

        avg_pl_color = "green" if self.avg_pl >= 0 else "red"
        avg_pl_sign = "+" if self.avg_pl >= 0 else "-"
        formatted_avg_pl = format_currency(self.avg_pl, avg_pl_sign, max_width)

        total_pl_color = "green" if self.total_pl >= 0 else "red"
        total_pl_sign = "+" if self.total_pl >= 0 else "-"
        formatted_total_pl = format_currency(self.total_pl, total_pl_sign, max_width)

        return f"""[b]Trading Statistics[/b]
{'─' * 30}
Active Trades:    {self.active_trades}
Total Trades:     {self.total_trades}
Winning Trades:   [green]{self.winning_trades}[/green]
Losing Trades:    [red]{self.losing_trades}[/red]
Win Rate:         [{win_color}]{self.win_rate:.1f}%[/{win_color}]
Current P/L:      [{current_pl_color}]{formatted_current_pl}[/{current_pl_color}]
Avg P/L:          [{avg_pl_color}]{formatted_avg_pl}[/{avg_pl_color}]
Total P/L:        [{total_pl_color}]{formatted_total_pl}[/{total_pl_color}]"""


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
        # Auto-scroll to bottom when new content is added
        self.call_after_refresh(self.scroll_end)

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
            # Auto-scroll to bottom when new content is added
            self.call_after_refresh(self.scroll_end)

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
        height: 3;
        border: solid $primary;
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
        width: 33%;
        height: 100%;
        background: $surface;
    }

    #activity-panel {
        border: solid $success;
        padding: 1;
        width: 67%;
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

    def __init__(self, virtual_mode: bool = True, live_wallet=None, live_db=None, live_strategy=None, stop_event=None):
        super().__init__()
        self.virtual_mode = virtual_mode
        self.wallet: Optional[VirtualWallet] = live_wallet
        self.db: Optional[TradeDatabase] = live_db
        self.strategy = live_strategy  # Live strategy instance (EnhancedStrategy or MultiMarketStrategy)
        self.stop_event = stop_event  # Signals the strategy thread to stop on quit
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
            _, _, virtual_config, _ = get_config()
            self.wallet = VirtualWallet(
                db_path=virtual_config.virtual_db_path,
                initial_balance=virtual_config.initial_balance
            )
        elif not self.virtual_mode and not self.db:
            _, db_config, _, _ = get_config()
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
        activity.add_message(f"[green]START[/green] Bender TUI started ({mode} mode, {live_label})")

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

                positions = self.wallet.get_active_positions()

                # Calculate total invested
                total_invested = sum(pos['entry_price'] * pos['amount'] for pos in positions)
                balance_panel.total_invested = total_invested

                # Get total costs (fees)
                total_costs = self.wallet.get_total_costs()
                balance_panel.total_costs = total_costs

                # Get realized P/L from closed trades
                realized_pl = self.wallet.get_total_profit_loss()
                balance_panel.realized_pl = realized_pl

                # Update stats
                stats_panel = self.query_one("#stats-panel", StatsPanel)
                stats_panel.active_trades = len(positions)
                stats_panel.total_trades = stats['total_trades']
                stats_panel.winning_trades = stats['winning_trades']
                stats_panel.losing_trades = stats['losing_trades']
                stats_panel.win_rate = stats['win_rate']
                stats_panel.avg_pl = stats['avg_profit_loss']
                stats_panel.total_pl = stats['total_realized_pl']

            else:
                # Real mode: use database
                positions = self.db.get_active_positions()

                # Real trading doesn't track balance the same way - just show invested amount
                total_invested = sum(pos['entry_price'] * pos['amount'] for pos in positions)
                balance_panel.balance = 0  # Not tracked in real mode
                balance_panel.total_invested = total_invested
                balance_panel.initial_balance = 0  # Not tracked in real mode

                # Get total costs (fees)
                total_costs = self.db.get_total_costs()
                balance_panel.total_costs = total_costs

                # Get realized P/L from closed trades
                realized_pl = self.db.get_total_profit_loss()
                balance_panel.realized_pl = realized_pl

                # Get real trading statistics from database
                stats_panel = self.query_one("#stats-panel", StatsPanel)
                stats_panel.active_trades = len(positions)
                trade_stats = self.db.get_trade_statistics()
                stats_panel.total_trades = trade_stats['total_trades']
                stats_panel.winning_trades = trade_stats['winning_trades']
                stats_panel.losing_trades = trade_stats['losing_trades']
                stats_panel.win_rate = trade_stats['win_rate']
                stats_panel.avg_pl = trade_stats['avg_profit_loss']

                # Get total P/L from closed trades
                total_pl = self.db.get_total_profit_loss()
                stats_panel.total_pl = total_pl

            # Update positions with live prices from strategy
            positions_panel = self.query_one("#positions-panel", PositionsPanel)

            # Get current prices from strategy with short cache (5s)
            # This matches the TUI update interval, ensuring fresh prices on each refresh
            # while avoiding excessive API calls
            prices = {}
            if self.strategy:
                # Try to get prices from strategy with short cache window
                try:
                    if hasattr(self.strategy, 'get_current_prices'):
                        # MultiMarketStrategy - get all prices at once with short cache
                        prices = self.strategy.get_current_prices(use_cache=True, cache_max_age=5.0)
                        logger.debug(f"TUI: Fetched {len(prices)} prices from MultiMarketStrategy")
                    elif hasattr(self.strategy, 'get_current_price'):
                        # Single EnhancedStrategy - use short cache
                        market = self.strategy.market
                        price = self.strategy.get_current_price(use_cache=True, cache_max_age=5.0)
                        if price is not None:
                            prices[market] = price
                            logger.debug(f"TUI: Fetched price for {market}: €{price:.6f}")
                except Exception as e:
                    logger.error(f"Error getting prices: {str(e)}")
            else:
                logger.debug("TUI: No strategy available, will use entry prices")

            # Fill in any missing prices with entry prices as fallback
            for pos in positions:
                if pos['market'] not in prices:
                    logger.debug(f"TUI: Using entry price for {pos['market']}: €{pos['entry_price']:.6f}")
                    prices[pos['market']] = pos['entry_price']

            # Calculate unrealized P/L for active positions
            unrealized_pl = 0.0
            for pos in positions:
                entry_value = pos['entry_price'] * pos['amount']
                current_price = prices.get(pos['market'], pos['entry_price'])
                current_value = current_price * pos['amount']
                pl = current_value - entry_value
                unrealized_pl += pl
                logger.debug(f"TUI P/L calc: {pos['market']} @ €{current_price:.6f} (entry €{pos['entry_price']:.6f}) = {pl:+.4f}")

            # Update stats panel with unrealized P/L
            logger.debug(f"TUI: Total unrealized P/L = €{unrealized_pl:+.4f}")
            stats_panel.current_unrealized_pl = unrealized_pl

            positions_panel.update_positions(positions, prices)

        except Exception as e:
            activity = self.query_one("#activity-panel", ActivityPanel)
            activity.add_message(f"[red]ERROR[/red] {str(e)}")

    def action_refresh(self) -> None:
        """Manually refresh data"""
        self.update_data()
        activity = self.query_one("#activity-panel", ActivityPanel)
        activity.add_message("[blue]REFRESH[/blue] Data refreshed")

    def action_quit(self) -> None:
        """Quit the application, signalling the strategy thread to stop first"""
        if self.stop_event is not None:
            self.stop_event.set()
        self.exit()


def run_tui(virtual_mode: bool = True):
    """Run the Bender TUI (standalone mode - reads from database)"""
    app = BenderTUI(virtual_mode=virtual_mode)
    app.run()


def run_tui_with_data(virtual_mode: bool, wallet=None, db=None, strategy=None, stop_event=None):
    """Run the Bender TUI with live data sources

    Args:
        virtual_mode: True for virtual trading, False for real
        wallet: VirtualWallet instance (if virtual_mode=True)
        db: TradeDatabase instance (if virtual_mode=False)
        strategy: The strategy instance being run (for live updates)
        stop_event: threading.Event used to stop the strategy thread on quit
    """
    app = BenderTUI(virtual_mode=virtual_mode, live_wallet=wallet, live_db=db, live_strategy=strategy, stop_event=stop_event)
    app.run()


if __name__ == "__main__":
    run_tui(virtual_mode=True)
