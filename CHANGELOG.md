# Changelog — `glitch-trade-core`

Auto-regenerated from `git log` by `/home/support/bin/changelog-regen`,
called before every push by `/home/support/bin/git-sync-all` (cron `*/15 * * * *`).

**Purpose:** traceability. If a push broke something, scan dates + short SHAs
here; then `git show <sha>` to see the diff, `git revert <sha>` to undo.

**Format:** UTC dates, newest first. Each entry: `time — subject (sha) — N files`.
Body text (if present) shown as indented sub-bullets.

---

## 2026-05-15

- **10:41 UTC** — feat(ir): bar_replay adapter — IR runs through existing simulator (`9bb9a95`) — 3 files
    ir/runner.py: dispatch by IR shape into the right execution path.
    v1 covers the two shapes that match our seed templates:
      1. trend-follower shape — indicators sma+ema+adx+atr with
         crosses_above/below entries + stop_loss/partial_tp/trailing
         exits. Builds TrendFollowerParams + ManagerParams from the
         IR and dispatches to the existing run_sim path.
      2. quick-rule shape — no indicators, single price-trigger entry,
         single limit exit. Uses an in-module bar walker that triggers
         entry/exit on intra-bar high/low touches.
    Anything else raises UnsupportedIRShape (the general IR interpreter
- **10:32 UTC** — feat(ir,rules): Strategy IR v1 + 3 new firm rule sets (rev 4 week 1) (`67e4821`) — 10 files
    IR (ir/schema.json + ir/__init__.py):
      - JSON Schema for the load-bearing IR — instruments, indicators,
        entries, exits, sizing, guards, optional webhook ingress
      - Spans the spectrum: 1-block quick rule ("buy BTCUSD at 80000,
        sell at 81000") up to multi-indicator prop-firm strategy with
        partial TPs and news filters
      - validate(ir) helper; uses jsonschema if available, soft-validates
        required fields otherwise
    Quick-rule parser (ir/quick_parse.py):
      - Deterministic regex grammar (no LLM in v1) covering 4 patterns:
- **10:18 UTC** — backtest: add FTMO Challenge ruleset + static-DD support (`72f71e5`) — 6 files
    Adds a second prop-firm ruleset alongside FundingPips Zero so we can
    A/B the engine against a friendlier rule profile. FTMO's headline
    differences:
                                  FTMO Phase 1   FundingPips Zero
        Max overall drawdown      10 % STATIC    5 % TRAILING
        Max daily loss            5 %            3 %
        Profit target to pass     10 %           4 %
        Min trading days          0              n/a
        Min profitable days       0              7 / 30
        Best-day consistency      none           ≤ 15 % of total profit
- **09:03 UTC** — auto-sync: 2026-05-15 08:03 UTC (`e41ff0f`) — 2 files
        M	backtest/bar_replay/ctrader_backfill.py
- **07:56 UTC** — backtest/ctrader_backfill: auto-load .env via dotenv; fail fast on missing creds (`291be5b`) — 1 file
    Previous run inherited an empty env even after `set -a; . .env` because
    sudo -u under some configs strips inheritance. Now the script:
      1. At import time, if CTRADER_* aren't already set, loads the standard
         ml_collector .env path via python-dotenv (already in the collector
         venv).
      2. At main() entry, if any of the four required env vars are still
         missing, prints a clear error with three remediation paths and
         exits 2 — instead of silently failing on the broker auth call.
    Also accepts CTRADER_ENV_FILE=/path/to/.env to point at a non-default
    location.
- **07:52 UTC** — backtest: cTrader Open API historical bar backfill into ml_bars (`b99a5ba`) — 1 file
    Subclasses the existing CTraderPriceFeed (in /opt/glitch-ouroboros/
    ctrader/ensemble) to add explicit (from_ts, to_ts) trendbar fetches and
    a backward-paginating loop. Pages 4000 bars at a time (cTrader caps at
    ~5000), sleeps 0.4s between calls, dedupes on the (symbol, timeframe,
    bar_time) UPSERT.
    Idempotent — re-running on a populated DB is a no-op for existing rows.
    The unique index `ux_ml_bars_sym_tf_time` is created on first run if
    missing.
    Why
    ---
- **07:47 UTC** — auto-sync: 2026-05-15 07:47 UTC (`e143eba`) — 2 files
        A	backtest/bar_replay/walk_forward.py
- **07:35 UTC** — backtest/bar_replay: phase 2 simulator + Optuna HPO sweep (`0c4291b`) — 1 file
    Replaces the dead-end "this engine cannot pass FundingPips Zero" verdict
    from the tape-replay (Phase 1) with a working pipeline that finds
    shippable cBot parameters by automated search.
    Pipeline
    --------
      ml_bars (Postgres)
        → bars.py             OHLC loader, m1 → any tf via UTC-aligned aggregation
        → indicators.py       SMA / EMA / ADX / ATR / rolling-median (numpy-only,
                              mirrors cAlgo math 1:1 so sim results match what
                              buyers see in cTrader Desktop backtests)
- **07:33 UTC** — auto-sync: 2026-05-15 07:33 UTC (`ab47c35`) — 7 files
        A	backtest/bar_replay/__init__.py
        A	backtest/bar_replay/bars.py
        A	backtest/bar_replay/indicators.py
        A	backtest/bar_replay/manager.py
        A	backtest/bar_replay/sim.py
        ... (+1 more)
- **07:17 UTC** — auto-sync: 2026-05-15 03:18 UTC (`01e50d6`) — 2 files
        A	ctrader-store/trend-follower/screenshots/screenshot-02-confidence-buckets.png
- **03:03 UTC** — auto-sync: 2026-05-14 22:32 UTC (`644ac38`) — 6 files
        A	ctrader-store/trend-follower/GlitchTrendFollower.algo
        A	ctrader-store/trend-follower/GlitchTrendFollowerBot.algo
        A	ctrader-store/trend-follower/logo.png
        A	ctrader-store/trend-follower/screenshots/screenshot-01-h1-chart.png
        A	ctrader-store/trend-follower/screenshots/screenshot-03-parameters.png

## 2026-05-14

- **22:18 UTC** — ctrader-store: first product family (Glitch Trend Follower) (`8da32bf`) — 5 files
    Approved as official cTrader Store seller on 2026-05-13. This is the
    source tree for products we'll list there.
    trend-follower/
      GlitchTrendFollower.cs      indicator — vote + confidence series,
                                  SMA/EMA crossover gated by ADX, ATR-modulated
      GlitchTrendFollowerBot.cs   cBot — ATR-sized market orders, daily-loss
                                  halt at 2.5% by default, never pyramids
      LISTING.md                  paste-ready title, descriptions, tags,
                                  screenshot brief, price floors ($19 / $39)
    README.md catalogues the roadmap: mean-reverter, momentum-hunter,
- **20:18 UTC** — backtest: tape-replay simulator with FundingPips Zero rule engine (`3ac8ab2`) — 5 files
    Reads closed trades from ml_trades chronologically, scales each trade's
    $-risk to a configurable target (default 0.5% of starting balance,
    hard cap 1%), and applies the resulting P&L to a VirtualAccount
    governed by FundingPips Zero rules (3% daily, 5% trailing DD).
    What it answers
    ---------------
    "If FundingPips Zero had been the broker and we'd risk-sized every
    trade, would the engine have survived — and what's the breach trace?"
    Package
    -------

## 2026-05-13

- **06:47 UTC** — auto-sync: 2026-05-13 06:47 UTC (`654ac9a`) — 6 files
        A	backtest/__init__.py
        A	backtest/account.py
        A	backtest/rules/__init__.py
        A	backtest/rules/fundingpips_zero.py
        A	backtest/sizer.py

## 2026-04-25

- **08:27 UTC** — docs(readme): note disabled satellite bots, pitch trained-artefact licensing (`427aa4e`) — 1 file
    Indian King Cobra and Terciopelo repos are now private and the bots
    themselves are disabled in production — only Ouroboros is live today.
    Update the README to:
    - mark satellite strategy repos as private throughout (header link bar,
      Satellite section, Ecosystem links)
    - add a "Fine-tuned models + backtested bots — available on request"
      section near the top so visitors landing here from search or the
      org profile know the trained artefacts (weights, backtest archives,
      per-market params) can be licensed or rebuilt to spec

## 2026-04-20

- **23:00 UTC** — Update public references after repo renames (`236dc87`) — 2 files
- **20:49 UTC** — Polish branding for Glitch Executor Labs public positioning (`c2e3fe0`) — 1 file

## 2026-04-15

- **02:40 UTC** — docs: fix strategy lineage formatting (`0b33ebc`) — 1 file
- **02:40 UTC** — docs: clarify strategy lineage and flagship positioning (`692db24`) — 2 files

## 2026-04-14

- **18:23 UTC** — docs: replace apache header template placeholder (`d83e053`) — 1 file
- **18:18 UTC** — docs: clarify ownership and security contact (`4d0a265`) — 3 files
- **18:06 UTC** — docs: strengthen public onboarding and contribution flow (`827c152`) — 3 files
- **17:59 UTC** — docs: refresh public repo links and branding (`b21b964`) — 2 files

## 2026-04-11

- **02:00 UTC** — Polish README landing section (`23c75d2`) — 1 file

## 2026-04-10

- **21:02 UTC** — Refine core repo positioning for builders (`b240646`) — 1 file
- **20:57 UTC** — Simplify core README header badges (`a4aaba5`) — 1 file
- **20:56 UTC** — Add social preview design briefs (`38d267b`) — 2 files
- **20:23 UTC** — Standardize ecosystem branding and cross-links (`5aea834`) — 1 file
- **20:02 UTC** — Polish family branding across READMEs (`f8de9eb`) — 1 file
- **19:59 UTC** — Remove satellite code from the core umbrella repo (`001238b`) — 12 files
- **19:56 UTC** — Link satellite repos from the core umbrella repo (`9b86b3f`) — 5 files
- **19:38 UTC** — Define Ouroboros and repo ecosystem branding (`c5e65d4`) — 7 files
- **19:13 UTC** — Clarify Indian King Cobra strategy structure (`d0ff25b`) — 4 files
- **19:11 UTC** — Merge Indian King Cobra into main (`d3a5393`) — 7 files
- **19:07 UTC** — Add Indian King Cobra momentum scalper (`686ee42`) — 7 files
- **18:39 UTC** — Add Apache license and project attribution (`e8db05d`) — 4 files
- **18:25 UTC** — Polish repository presentation and architecture docs (`6833dc3`) — 7 files
- **18:18 UTC** — Merge remote GitHub scaffold (`5c9a40f`)
    # Conflicts:
    #	README.md
- **18:18 UTC** — Initial MT5 core and cTrader concept structure (`f4e0042`) — 37 files
- **18:11 UTC** — Initial commit (`9e89f4a`) — 1 file
