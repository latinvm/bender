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