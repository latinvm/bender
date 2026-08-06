"""Portfolio-level risk safeguards.

The strategy layer decides when a single position is bought or sold; this
module decides whether the portfolio as a whole is allowed to keep opening
new positions. When a limit trips, Bender stops opening positions (existing
positions are still managed and can be sold) and logs loudly.
"""

import logging
from datetime import datetime, time as dtime

logger = logging.getLogger('trader.risk')


class RiskManager:
    """Blocks new positions when daily-loss or drawdown limits are hit.

    Args:
        trade_store: object with get_profit_loss_since(dt) and
            get_total_profit_loss() (TradeDatabase or VirtualWallet)
        capital_base: reference equity in EUR that the percentages apply to
            (virtual mode: initial wallet balance; real mode: the maximum
            capital the bot deploys, trade_amount * max_positions)
        max_daily_loss_pct: halt new buys when today's realized loss exceeds
            this percentage of capital_base (0 disables the check)
        max_drawdown_pct: halt new buys when total realized loss exceeds
            this percentage of capital_base (0 disables the check)
    """

    def __init__(self, trade_store, capital_base: float,
                 max_daily_loss_pct: float = 0.0, max_drawdown_pct: float = 0.0):
        self.trade_store = trade_store
        self.capital_base = capital_base
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self._tripped_logged = False

        checks = []
        if max_daily_loss_pct > 0:
            checks.append(f"daily loss limit {max_daily_loss_pct:g}% of €{capital_base:.2f}")
        if max_drawdown_pct > 0:
            checks.append(f"max drawdown {max_drawdown_pct:g}% of €{capital_base:.2f}")
        if checks:
            logger.info(f"Risk manager active: {', '.join(checks)}")
        else:
            logger.info("Risk manager: no limits configured (set MAX_DAILY_LOSS_PCT / MAX_DRAWDOWN_PCT)")

    def can_open_position(self) -> tuple[bool, str]:
        """Check whether opening a new position is currently allowed.

        Returns:
            Tuple of (allowed, reason). reason is set when blocked.
        """
        if self.capital_base <= 0:
            return True, ""

        if self.max_daily_loss_pct > 0:
            midnight = datetime.combine(datetime.now().date(), dtime.min)
            today_pl = self.trade_store.get_profit_loss_since(midnight)
            daily_limit = -(self.capital_base * self.max_daily_loss_pct / 100)
            if today_pl <= daily_limit:
                reason = (f"DAILY LOSS LIMIT HIT: today's realized P/L €{today_pl:+.2f} "
                          f"breaches limit €{daily_limit:+.2f} "
                          f"({self.max_daily_loss_pct:g}% of €{self.capital_base:.2f})")
                self._log_tripped(reason)
                return False, reason

        if self.max_drawdown_pct > 0:
            total_pl = self.trade_store.get_total_profit_loss()
            drawdown_limit = -(self.capital_base * self.max_drawdown_pct / 100)
            if total_pl <= drawdown_limit:
                reason = (f"MAX DRAWDOWN HIT: total realized P/L €{total_pl:+.2f} "
                          f"breaches limit €{drawdown_limit:+.2f} "
                          f"({self.max_drawdown_pct:g}% of €{self.capital_base:.2f})")
                self._log_tripped(reason)
                return False, reason

        self._tripped_logged = False
        return True, ""

    def _log_tripped(self, reason: str) -> None:
        # Log the full warning once per trip, not on every strategy cycle
        if not self._tripped_logged:
            logger.error("=" * 80)
            logger.error(f"RISK SAFEGUARD TRIPPED: {reason}")
            logger.error("No new positions will be opened. Existing positions are still managed.")
            logger.error("=" * 80)
            self._tripped_logged = True
        else:
            logger.info(f"Risk safeguard still active: {reason}")
