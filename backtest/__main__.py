"""
CLI entry-point. Run with:

    python -m backtest                                  # default 25k all 6 bots
    python -m backtest --balance 50000                  # 50k account
    python -m backtest --exclude viper anaconda cobra   # winners-only
    python -m backtest --symbols JPN225 GER40 BTCUSD    # symbol whitelist
    python -m backtest --from 2026-04-15 --to 2026-05-13
"""
from __future__ import annotations

import argparse
import sys

from .runner import run_tape_replay
from .report import (
    print_headline, print_per_bot, print_per_symbol, print_daily,
    print_consistency,
)
from .rules import FUNDINGPIPS_ZERO


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="backtest",
        description="FundingPips-rules backtester over the historical ml_trades tape.")
    p.add_argument("--balance", type=float, default=25_000,
                   help="Starting balance (default: 25000)")
    p.add_argument("--from", dest="date_from", default=None,
                   help="ISO date or timestamp, inclusive (default: all-time)")
    p.add_argument("--to", dest="date_to", default=None,
                   help="ISO date or timestamp, exclusive")
    p.add_argument("--include", nargs="+", default=None,
                   help="Bot whitelist")
    p.add_argument("--exclude", nargs="+", default=None,
                   help="Bot blacklist (mutually exclusive with --include)")
    p.add_argument("--symbols", nargs="+", default=None,
                   help="Symbol whitelist")
    p.add_argument("--show-daily", type=int, default=14,
                   help="Last N daily rows to print (default 14, 0 to hide)")
    args = p.parse_args(argv)

    result = run_tape_replay(
        starting_balance=args.balance,
        date_from=args.date_from,
        date_to=args.date_to,
        include_bots=args.include,
        exclude_bots=args.exclude,
        include_symbols=args.symbols,
        rules=FUNDINGPIPS_ZERO,
    )

    print_headline(result)
    print_per_bot(result)
    print_per_symbol(result)
    if args.show_daily:
        print_daily(result, n=args.show_daily)
    print_consistency(result)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
