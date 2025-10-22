import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

# Create logs directory if it doesn't exist
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

class TUILogHandler(logging.Handler):
    """Custom log handler that sends logs to the TUI"""

    def __init__(self, callback: Callable[[str], None]):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            msg = self.format(record)
            self.callback(msg)
        except Exception:
            self.handleError(record)


class TUIActivityHandler(logging.Handler):
    """Custom log handler that filters and sends important trading events to TUI activity panel

    Captures:
    - Buy/sell order executions
    - Position changes
    - Strategy signals
    - Errors and warnings
    """

    def __init__(self, callback: Callable[[str], None]):
        super().__init__()
        self.callback = callback
        # Keywords that indicate important trading activity
        self.important_keywords = [
            'buy order placed',
            'sell order placed',
            'buy signal triggered',
            'sell signal triggered',
            'order executed',
            'position',
            'take profit',
            'stop loss',
            'error',
            'warning',
            'test trade',
            'resuming with',
            'virtual',
            'balance'
        ]

    def emit(self, record):
        try:
            msg = record.getMessage().lower()
            level = record.levelname

            # Always include errors and warnings
            is_important = (level in ['ERROR', 'WARNING']) or any(keyword in msg for keyword in self.important_keywords)

            if is_important:
                # Format for activity panel (shorter format)
                formatted = self._format_activity(record)
                if formatted:
                    self.callback(formatted)
        except Exception:
            self.handleError(record)

    def _format_activity(self, record) -> Optional[str]:
        """Format log record as activity message

        Returns:
            Formatted string or None to skip
        """
        msg = record.getMessage()
        level = record.levelname

        # Color coding based on activity type
        if 'buy' in msg.lower() and 'signal' in msg.lower():
            return f"[blue]BUY SIGNAL[/blue] {msg}"
        elif 'buy' in msg.lower() and 'order placed' in msg.lower():
            return f"[green]BUY[/green] {msg}"
        elif 'sell' in msg.lower() and 'signal' in msg.lower():
            return f"[yellow]SELL SIGNAL[/yellow] {msg}"
        elif 'sell' in msg.lower() and 'order placed' in msg.lower():
            return f"[yellow]SELL[/yellow] {msg}"
        elif 'take profit' in msg.lower() or 'stop loss' in msg.lower():
            return f"[magenta]EXIT[/magenta] {msg}"
        elif 'test trade' in msg.lower():
            return f"[cyan]TEST[/cyan] {msg}"
        elif 'resuming' in msg.lower() or 'position' in msg.lower():
            return f"[blue]POSITION[/blue] {msg}"
        elif 'virtual' in msg.lower() and 'executed' in msg.lower():
            return f"[green]OK[/green] {msg}"
        elif level == 'ERROR':
            return f"[red]ERROR[/red] {msg}"
        elif level == 'WARNING':
            return f"[yellow]WARNING[/yellow] {msg}"
        else:
            return f"{msg}"

def setup_logger(name: str = 'trader', console_output: bool = True) -> logging.Logger:
    """Setup basic logging configuration

    Args:
        name: Logger name (default: 'trader')
        console_output: If False, only logs to file (useful when TUI is running)
    """
    # Get logger
    logger = logging.getLogger(name)

    # Only add handlers if they haven't been added yet
    if not logger.handlers:
        logger.setLevel(logging.INFO)

        # Create formatters
        fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        # File handler - daily log file
        daily_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        fh = logging.FileHandler(daily_file)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

        # Console handler (optional)
        if console_output:
            ch = logging.StreamHandler(sys.stdout)
            ch.setFormatter(fmt)
            logger.addHandler(ch)

    return logger


def add_tui_handler(callback: Callable[[str], None]) -> None:
    """Add a TUI handler to the root trader logger

    Args:
        callback: Function to call with each log message
    """
    logger = logging.getLogger('trader')

    # Create and add TUI handler
    fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    tui_handler = TUILogHandler(callback)
    tui_handler.setFormatter(fmt)
    logger.addHandler(tui_handler)


def add_tui_activity_handler(callback: Callable[[str], None]) -> None:
    """Add a TUI activity handler to capture important trading events

    Args:
        callback: Function to call with each activity message
    """
    logger = logging.getLogger('trader')

    # Create and add activity handler (no formatter needed, handles own formatting)
    activity_handler = TUIActivityHandler(callback)
    logger.addHandler(activity_handler)