"""
Virtual prop-firm account.

Tracks balance, equity, daily P&L, drawdown high-water mark, and emits a
breach record the first time any hard rule is violated. The simulator
queries this object before each candidate trade and stops feeding trades
once `account.terminated` flips to True.

Time bookkeeping
----------------
All timestamps are timezone-aware UTC `datetime` objects. The "day" used
for the daily-loss rule is the broker day (UTC midnight to UTC midnight)
— good enough for a first pass; switch to Eastern-or-broker-local in a
later iteration if FundingPips publishes a stricter definition.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .rules import FundingPipsZeroRules


@dataclass
class Breach:
    """A hard rule violation. After a breach the account is dead."""
    at: datetime
    rule: str          # 'max_daily_loss' | 'max_trailing_dd'
    detail: str        # human-readable summary
    equity: float      # equity at the moment of breach
    threshold: float   # the $ threshold that was crossed


@dataclass
class DailyRecord:
    """One row per UTC day the account was live."""
    day: str           # 'YYYY-MM-DD'
    start_balance: float
    end_balance: float
    realised_pnl: float
    n_trades: int
    profitable: bool   # end_balance > start_balance + min_profitable_pct * size

    @property
    def pnl_pct(self) -> float:
        return (self.realised_pnl / self.start_balance) if self.start_balance else 0.0


class VirtualAccount:
    """A single funded-style account governed by prop-firm rules.

    The simulator calls these methods in order:

        before_open(ts)          → may veto for soft-halt / news / weekend
        record_close(ts, pnl)    → applies realised PnL, updates HWM,
                                    checks for hard breaches

    Then at end-of-day:

        roll_day(end_of_day_ts)  → archives the day, opens a new one
    """

    def __init__(
        self,
        starting_balance: float,
        rules: FundingPipsZeroRules,
        *,
        start_ts: Optional[datetime] = None,
    ) -> None:
        self.starting_balance = float(starting_balance)
        self.balance = float(starting_balance)
        self.equity_hwm = float(starting_balance)
        self.rules = rules

        self._day_open_balance = float(starting_balance)
        self._day_realised_pnl = 0.0
        self._day_trade_count = 0
        self._current_day: Optional[str] = (
            start_ts.astimezone(timezone.utc).date().isoformat() if start_ts else None
        )

        self.breach: Optional[Breach] = None
        self.daily_records: list[DailyRecord] = []
        self.trade_count = 0

    # ── Hard thresholds (absolute $ amounts) ────────────────────────────

    @property
    def daily_loss_threshold(self) -> float:
        """Account hits this $ loss for the day → terminated."""
        return self._day_open_balance * (1 - self.rules.max_daily_loss_pct)

    @property
    def trailing_dd_threshold(self) -> float:
        """Equity below this $ → terminated. Reference is the equity HWM
        (trailing) by default. If the rule set sets `drawdown_is_static =
        True` (e.g. FTMO), we pin the reference at the original starting
        balance — so winning streaks don't tighten the breach buffer."""
        ref = (self.starting_balance
               if getattr(self.rules, "drawdown_is_static", False)
               else self.equity_hwm)
        return ref * (1 - self.rules.max_trailing_dd_pct)

    @property
    def soft_halt_threshold(self) -> float:
        """Stop opening trades (but don't terminate) at this $ for the day."""
        return self._day_open_balance * (1 - self.rules.soft_halt_daily_loss_pct)

    # ── State queries ───────────────────────────────────────────────────

    @property
    def terminated(self) -> bool:
        return self.breach is not None

    @property
    def day_pnl(self) -> float:
        return self._day_realised_pnl

    @property
    def day_pnl_pct(self) -> float:
        return self._day_realised_pnl / self._day_open_balance if self._day_open_balance else 0.0

    @property
    def total_pnl(self) -> float:
        return self.balance - self.starting_balance

    @property
    def total_pnl_pct(self) -> float:
        return self.total_pnl / self.starting_balance if self.starting_balance else 0.0

    # ── Mutations ───────────────────────────────────────────────────────

    def before_open(self, ts: datetime) -> Optional[str]:
        """Returns None if the trade may open, otherwise a reason string.

        The simulator should consult this *before* applying a trade. It does
        not block on news/weekend — those are layered in `newsguard.py` and
        the day-roll logic; this only blocks on soft-halt + termination.
        """
        if self.terminated:
            return "account terminated"
        if self.day_pnl <= -abs(self._day_open_balance * self.rules.soft_halt_daily_loss_pct):
            return f"soft-halt: day P&L {self.day_pnl_pct:.2%} ≤ -{self.rules.soft_halt_daily_loss_pct:.2%}"
        return None

    def record_close(self, ts: datetime, pnl: float) -> None:
        """Apply realised PnL on trade close, update HWM, check hard breaches."""
        if self.terminated:
            return

        # Day rollover if the close lands in a new UTC day.
        self._ensure_day(ts)

        self.balance += pnl
        self._day_realised_pnl += pnl
        self._day_trade_count += 1
        self.trade_count += 1

        # Update high-water mark on positive equity moves.
        if self.balance > self.equity_hwm:
            self.equity_hwm = self.balance

        # ── Hard breach checks ──
        if self.balance <= self.trailing_dd_threshold:
            self.breach = Breach(
                at=ts,
                rule="max_trailing_dd",
                detail=(
                    f"equity {self.balance:,.2f} ≤ HWM {self.equity_hwm:,.2f} "
                    f"× (1 − {self.rules.max_trailing_dd_pct:.0%})"
                ),
                equity=self.balance,
                threshold=self.trailing_dd_threshold,
            )
            return

        if self.balance <= self._day_open_balance - self._day_open_balance * self.rules.max_daily_loss_pct:
            self.breach = Breach(
                at=ts,
                rule="max_daily_loss",
                detail=(
                    f"day P&L {self.day_pnl:,.2f} ≤ "
                    f"-{self.rules.max_daily_loss_pct:.0%} × day-open {self._day_open_balance:,.2f}"
                ),
                equity=self.balance,
                threshold=self._day_open_balance * (1 - self.rules.max_daily_loss_pct),
            )

    def roll_day(self, end_of_day_ts: datetime) -> Optional[DailyRecord]:
        """Close the current day book and start a new one. Returns the
        archived DailyRecord (or None if the day had no activity)."""
        if self._current_day is None:
            self._current_day = end_of_day_ts.astimezone(timezone.utc).date().isoformat()
            self._day_open_balance = self.balance
            return None

        rec = DailyRecord(
            day=self._current_day,
            start_balance=self._day_open_balance,
            end_balance=self.balance,
            realised_pnl=self._day_realised_pnl,
            n_trades=self._day_trade_count,
            profitable=self._day_realised_pnl >= (
                self.starting_balance * self.rules.min_profitable_day_pct
            ),
        )
        self.daily_records.append(rec)

        # Reset day book.
        self._current_day = end_of_day_ts.astimezone(timezone.utc).date().isoformat()
        self._day_open_balance = self.balance
        self._day_realised_pnl = 0.0
        self._day_trade_count = 0
        return rec

    # ── Internal ────────────────────────────────────────────────────────

    def _ensure_day(self, ts: datetime) -> None:
        """Roll the day if the incoming timestamp is past the current day."""
        d = ts.astimezone(timezone.utc).date().isoformat()
        if self._current_day is None:
            self._current_day = d
            self._day_open_balance = self.balance
            return
        if d != self._current_day:
            self.roll_day(ts)

    # ── Reporting helpers ───────────────────────────────────────────────

    def summary(self) -> dict:
        wins = sum(1 for d in self.daily_records if d.profitable)
        return {
            "starting_balance": self.starting_balance,
            "ending_balance": self.balance,
            "total_pnl": self.total_pnl,
            "total_pnl_pct": self.total_pnl_pct,
            "trades": self.trade_count,
            "days_traded": len(self.daily_records),
            "profitable_days": wins,
            "equity_hwm": self.equity_hwm,
            "terminated": self.terminated,
            "breach": (
                {
                    "rule": self.breach.rule,
                    "at": self.breach.at.isoformat(),
                    "detail": self.breach.detail,
                    "equity": self.breach.equity,
                    "threshold": self.breach.threshold,
                }
                if self.breach
                else None
            ),
        }
