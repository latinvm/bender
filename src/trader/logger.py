import logging
import os
import sys
import time
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

class DailyFileHandler(logging.FileHandler):
    """File handler writing to <directory>/<prefix>YYYY-MM-DD<suffix>.

    Switches to a new file when a record's (local) date differs from the
    current file's, so a long-running bot gets one file per day instead of
    one ever-growing file named after its start date.
    """

    def __init__(self, directory, prefix: str = '', suffix: str = '.log', clock: Callable[[], float] = time.time):
        self.directory = Path(directory).resolve()
        self.prefix = prefix
        self.suffix = suffix
        self._day = self._day_of(clock())
        super().__init__(self._path_for(self._day), delay=True)

    @staticmethod
    def _day_of(timestamp: float) -> str:
        return time.strftime('%Y-%m-%d', time.localtime(timestamp))

    def _path_for(self, day: str) -> Path:
        return self.directory / f"{self.prefix}{day}{self.suffix}"

    def emit(self, record):
        # Handler.handle() holds the handler lock, so swapping streams is safe.
        # Logging must never raise into the trading loop: any failure (a moved
        # logs/ directory, a full disk) goes to handleError instead.
        try:
            day = self._day_of(record.created)
            if day != self._day:
                self._day = day
                if self.stream:
                    self.stream.close()
                    self.stream = None
                self.baseFilename = os.path.abspath(self._path_for(day))
            if self.stream is None:
                self.directory.mkdir(parents=True, exist_ok=True)
            super().emit(record)
        except Exception:
            self.handleError(record)


def log_level_from_env() -> int:
    """Log level from LOG_LEVEL (DEBUG restores the per-check chatter); INFO by default."""
    level = logging.getLevelName(os.getenv('LOG_LEVEL', 'INFO').upper())
    return level if isinstance(level, int) else logging.INFO


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
        logger.setLevel(log_level_from_env())

        # Create formatters
        fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        # File handler - one file per day (logs/YYYY-MM-DD.log)
        fh = DailyFileHandler(log_dir)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

        # Decision records: one JSON object per line, one file per day
        # (logs/decisions-YYYY-MM-DD.jsonl). Kept out of the text log and the
        # TUI, and independent of LOG_LEVEL.
        decisions = logging.getLogger(f'{name}.decisions')
        decisions.setLevel(logging.INFO)
        decisions.propagate = False
        dh = DailyFileHandler(log_dir, prefix='decisions-', suffix='.jsonl')
        dh.setFormatter(logging.Formatter('%(message)s'))
        decisions.addHandler(dh)

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