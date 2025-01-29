import logging
import sys
from datetime import datetime
from pathlib import Path

# Create logs directory if it doesn't exist
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

def setup_logger(name: str = 'trader') -> logging.Logger:
    """Setup basic logging configuration"""
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
        
        # Console handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        
        # Add handlers
        logger.addHandler(fh)
        logger.addHandler(ch)
    
    return logger