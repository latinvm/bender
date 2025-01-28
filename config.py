import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # Project paths
    PROJECT_ROOT = Path(__file__).parent.parent
    DATA_DIR = PROJECT_ROOT / "data"
    LOG_DIR = PROJECT_ROOT / "logs"

    # Exchange settings
    EXCHANGE = "bitvavo"
    API_KEY = os.getenv("BITVAVO_API_KEY")
    API_SECRET = os.getenv("BITVAVO_API_SECRET")
    
    # Trading pairs configuration
    TRADING_PAIRS = {
        "DOGE/EUR": {
            "min_trade_amount": 1.0,  # Minimum EUR per trade
            "position_size": 5.0,     # Max position size in EUR
            "stop_loss": 0.02,        # 2% stop loss
            "take_profit": 0.04,      # 4% take profit
        },
        "XRP/EUR": {
            "min_trade_amount": 1.0,
            "position_size": 5.0,
            "stop_loss": 0.02,
            "take_profit": 0.04,
        },
        "SHIB/EUR": {
            "min_trade_amount": 1.0,
            "position_size": 5.0,
            "stop_loss": 0.02,
            "take_profit": 0.04,
        }
    }

    # Global trading parameters
    TOTAL_BUDGET = 15.0               # Total budget in EUR
    MAX_TRADES = 3                    # Maximum concurrent trades
    RISK_PER_TRADE = 0.02            # 2% risk per trade
    COOLDOWN_PERIOD = 300            # 5 minutes between trades
    
    # Technical Analysis Parameters
    TIMEFRAMES = {
        "fast": "5m",    # 5 minutes
        "medium": "15m", # 15 minutes
        "slow": "1h"     # 1 hour
    }
    
    # Indicators configuration
    INDICATORS = {
        "RSI": {"period": 14, "overbought": 70, "oversold": 30},
        "MACD": {"fast": 12, "slow": 26, "signal": 9},
        "Bollinger": {"period": 20, "stddev": 2}
    }

    # Risk Management
    MAX_DAILY_TRADES = 10            # Maximum trades per day
    MAX_DAILY_LOSS = 0.05           # 5% max daily loss
    TRAILING_STOP = 0.015           # 1.5% trailing stop
    
    # Monitoring and Notifications
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    
    # Backtesting configuration
    BACKTEST_DAYS = 30              # Days to backtest
    
    # Debug and testing
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    PAPER_TRADING = os.getenv("PAPER_TRADING", "True").lower() == "true"

    @classmethod
    def create_directories(cls):
        """Create necessary project directories"""
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOG_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def validate_config(cls):
        """Validate configuration settings"""
        total_position_size = sum(pair["position_size"] for pair in cls.TRADING_PAIRS.values())
        if total_position_size > cls.TOTAL_BUDGET:
            raise ValueError("Total position sizes exceed total budget")
        
        if not cls.API_KEY or not cls.API_SECRET:
            raise ValueError("API credentials not found in environment")

        return True