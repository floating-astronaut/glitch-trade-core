"""
Human-readable reports for a `RunResult`.

Three views the caller is likely to want:

  - `print_headline(result)`     — single-line "passed / failed and why"
  - `print_per_bot(result)`      — bot-level attribution table
  - `print_per_symbol(result)`   — symbol-level attribution table
  - `print_daily(result, n=14)`  — last N days of P&L + breach trace
  - `check_consistency(result, rules)` — payout-blocking checks
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from .runner import RunResult
from .rules import FundingPipsZeroRules, FUNDINGPIPS_ZERO


def _fmt_money(x: float) -> str:
    sign = "-" if x < 0 else " "
    return f"{sign}${abs(x):>10,.2f}"


def _fmt_pct(x: float) -> str:
    return f"{x*100:+6.2f}%"


# ── Headline ────────────────────────────────────────────────────────────

def print_headline(result: RunResult, *, rules: FundingPipsZeroRules = FUNDINGPIPS_ZERO) -> None:
    s = result.summary
    print()
    print(f"=== {rules.name} ===")
    print(f"  starting balance:  ${s['starting_balance']:>12,.0f}")
    print(f"  ending balance:    ${s['ending_balance']:>12,.2f}")
    print(f"  total P&L:         {_fmt_money(s['total_pnl'])}  ({_fmt_pct(s['total_pnl_pct'])})")
    print(f"  HWM:               ${s['equity_hwm']:>12,.2f}")
    print(f"  trades applied:    {s['trades_applied']:>5}  (capped: {s['trades_capped']}, vetoed: {s['trades_vetoed']})")
    print(f"  days traded:       {s['days_traded']:>5}  (profitable: {s['profitable_days']})")
    if s["terminated"]:
        b = s["breach"]
        print(f"  ❌ TERMINATED via {b['rule']} at {b['at']}")
        print(f"     {b['detail']}")
    else:
        # Withdrawability
        cushion = rules.profit_cushion_pct
        needed_pct = rules.min_withdraw_total_pct
        if s["total_pnl_pct"] < needed_pct:
            print(f"  ⚠️   alive but below {needed_pct:.0%} payout floor")
            print(f"      (need ≥ {needed_pct:.0%} cumulative profit; currently {_fmt_pct(s['total_pnl_pct'])})")
        else:
            split = rules.profit_split_to_trader
            withdrawable_pct = s["total_pnl_pct"] - cushion
            withdrawable = s["starting_balance"] * withdrawable_pct * split
            print(f"  ✅ survived. withdrawable to trader ≈ ${withdrawable:,.2f} "
                  f"({withdrawable_pct:.2%} × {split:.0%} split)")


# ── Per-bot attribution ─────────────────────────────────────────────────

def print_per_bot(result: RunResult) -> None:
    by_bot: dict[str, dict] = defaultdict(lambda: {"n": 0, "raw": 0.0, "scaled": 0.0,
                                                    "wins": 0, "losses": 0})
    for t in result.trades:
        if t.vetoed is not None:
            continue
        b = by_bot[t.bot]
        b["n"] += 1
        b["raw"] += t.raw_pnl
        b["scaled"] += t.scaled_pnl
        b["wins"] += 1 if t.scaled_pnl > 0 else 0
        b["losses"] += 1 if t.scaled_pnl < 0 else 0

    rows = sorted(by_bot.items(), key=lambda kv: kv[1]["scaled"], reverse=True)
    print()
    print(f"  {'bot':10} {'trades':>7} {'wins':>6} {'losses':>7} {'WR':>6} "
          f"{'raw P&L':>13} {'scaled P&L':>13}")
    for bot, b in rows:
        wr = b["wins"] / (b["wins"] + b["losses"]) * 100 if (b["wins"] + b["losses"]) else 0
        print(f"  {bot:10} {b['n']:>7} {b['wins']:>6} {b['losses']:>7} {wr:>5.1f}% "
              f"{_fmt_money(b['raw'])} {_fmt_money(b['scaled'])}")


# ── Per-symbol attribution ──────────────────────────────────────────────

def print_per_symbol(result: RunResult, *, top: int = 10) -> None:
    by_sym: dict[str, dict] = defaultdict(lambda: {"n": 0, "scaled": 0.0})
    for t in result.trades:
        if t.vetoed is not None:
            continue
        s = by_sym[t.symbol]
        s["n"] += 1
        s["scaled"] += t.scaled_pnl

    rows = sorted(by_sym.items(), key=lambda kv: kv[1]["scaled"], reverse=True)
    print()
    print(f"  symbol attribution (top/bottom {top})")
    print(f"  {'symbol':10} {'trades':>7} {'scaled P&L':>13}")
    for sym, s in rows[:top]:
        print(f"  {sym:10} {s['n']:>7} {_fmt_money(s['scaled'])}")
    if len(rows) > top:
        print(f"  {'…':10}")
        for sym, s in rows[-3:]:
            print(f"  {sym:10} {s['n']:>7} {_fmt_money(s['scaled'])}")


# ── Daily history ───────────────────────────────────────────────────────

def print_daily(result: RunResult, *, n: int = 14) -> None:
    days = result.account.daily_records[-n:]
    if not days:
        print("\n  (no daily records — no closed trades in window)")
        return
    print()
    print(f"  daily P&L (last {len(days)} of {len(result.account.daily_records)} days)")
    print(f"  {'day':12} {'start':>12} {'end':>12} {'P&L':>12} {'%':>7} {'#':>4} {'prof?':>6}")
    for d in days:
        print(f"  {d.day:12} ${d.start_balance:>10,.0f} ${d.end_balance:>10,.0f} "
              f"{_fmt_money(d.realised_pnl)} {_fmt_pct(d.pnl_pct):>7} "
              f"{d.n_trades:>4} {'✓' if d.profitable else ' ':>6}")


# ── Consistency / payout checks ─────────────────────────────────────────

def check_consistency(result: RunResult, *, rules: FundingPipsZeroRules = FUNDINGPIPS_ZERO) -> dict:
    days = result.account.daily_records
    if not days:
        return {"ok": False, "reason": "no days"}
    total_profit = sum(d.realised_pnl for d in days if d.realised_pnl > 0)
    best_day = max((d.realised_pnl for d in days), default=0.0)
    profitable = sum(1 for d in days if d.profitable)

    issues: list[str] = []
    if total_profit > 0:
        share = best_day / total_profit
        if share > rules.max_best_day_share_of_profit:
            issues.append(
                f"best day = {share:.0%} of total profit (limit {rules.max_best_day_share_of_profit:.0%})"
            )

    # Min profitable days check is per-rolling-30 in firm rules; here we just
    # report it over the full window for sanity.
    if profitable < rules.min_profitable_days_per_30 and len(days) >= 30:
        issues.append(
            f"{profitable} profitable days < {rules.min_profitable_days_per_30} "
            f"required per 30 (window has {len(days)} days)"
        )

    return {
        "ok": not issues,
        "issues": issues,
        "total_profit": total_profit,
        "best_day": best_day,
        "best_day_share": (best_day / total_profit) if total_profit else 0,
        "profitable_days": profitable,
        "total_days": len(days),
    }


def print_consistency(result: RunResult, *, rules: FundingPipsZeroRules = FUNDINGPIPS_ZERO) -> None:
    c = check_consistency(result, rules=rules)
    print()
    print("  payout consistency checks")
    if "best_day_share" not in c:
        print(f"  (skipped: {c.get('reason', 'no daily records')})")
        return
    print(f"  best-day share of profit: {c['best_day_share']:.0%}  "
          f"(limit {rules.max_best_day_share_of_profit:.0%})")
    print(f"  profitable days:          {c['profitable_days']}/{c['total_days']}  "
          f"(need ≥ {rules.min_profitable_days_per_30} per 30)")
    if c["ok"]:
        print("  ✅ payout-eligible")
    else:
        for issue in c["issues"]:
            print(f"  ⚠️  {issue}")
