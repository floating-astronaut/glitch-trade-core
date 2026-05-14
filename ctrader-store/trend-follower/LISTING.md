# Listing copy — Glitch Trend Follower

Two products ship from this folder:

1. **`GlitchTrendFollower`** — indicator. Price floor **$19**. Lower-friction first listing; buyers see signal & confidence on chart, no order risk.
2. **`GlitchTrendFollowerBot`** — cBot. Price floor **$39**. Same signal logic, places ATR-sized market orders with built-in daily-loss halt.

Submit the indicator first (faster review, cheaper buy, lets the product accumulate ratings before the cBot lands). The cBot follows once the indicator has a few sales.

---

## Indicator listing

**Title** (≤60 chars)
```
Glitch Trend Follower — ADX-confirmed SMA/EMA crossover
```

**Short description** (≤120 chars)
```
Trend signals with confidence: SMA/EMA crossover gated by ADX, ATR-modulated. Plots vote + confidence on every bar.
```

**Full description** (≥300 chars)
```
Glitch Trend Follower is the production trend-detection model that ships
inside the GlitchExecutor systematic engine. It produces a clean BUY / SELL /
HOLD signal on every bar based on three orthogonal classical-TA filters:

  • SMA/EMA crossover detected within the last N bars (default 5)
  • ADX trend strength gate (default minimum 15, with strong/mid bands)
  • ATR-vs-rolling-median volatility modifier that softens confidence
    during quiet markets rather than blocking signals outright

The two outputs are designed for direct consumption by other indicators or
cBots: a Vote histogram (+1 / 0 / -1) and a Confidence series (0.45–0.90).
Strong trend + recent crossover → 0.90 confidence; weak ADX + low ATR →
0.45 floor.

Designed for and tested on H1 charts. Works as-is on indices (JPN225,
GER40, UK100, US500), gold (XAUUSD), and major-pair forex. Adjust
CrossoverLookback and AdxMinTrend per instrument to control fire-rate.
All parameters exposed; no hidden state.

Buyers also get the matching Glitch Trend Follower cBot (sold separately)
which uses these exact signals to place ATR-sized orders with a built-in
daily-loss halt.
```

**Tags** (pick from the form's lists)
- Market: Forex, Indices, Crypto, Commodities
- Strategy: Trend
- Symbol: Multi-Symbol
- Technical Analysis: ADX, ATR, EMA, SMA, Crossover

**Required screenshots (3 minimum, ≥800 px wide)**

1. **`screenshot-01-h1-indices.png`** — H1 JPN225 or GER40 chart with the
   indicator pane below, showing the vote histogram + confidence line through
   a clear trend.
2. **`screenshot-02-confidence-buckets.png`** — Zoom-in on a strong trend
   showing a 0.90 confidence run, then an ATR-penalised 0.60 run.
3. **`screenshot-03-parameters.png`** — Parameters dialog (cTrader IDE) with
   the full list of exposed knobs, demonstrating no hidden config.

**Optional**: 30-second YouTube walkthrough triggers the "video badge" on the
listing — meaningful conversion boost per the store docs.

**Logo** — 300×300 PNG in this folder as `logo.png` (need to create).

**Price**: $19 launch (floor). Promotional pricing okay after first sales come
in; keep above floor.

---

## cBot listing (follow-up, ship after indicator has 3+ ratings)

**Title**
```
Glitch Trend Follower cBot — ATR-sized, daily-loss halt
```

**Short description**
```
ATR-sized auto-trader on the Glitch trend signal. Built-in 2.5%/day loss halt. Prop-firm-friendly defaults.
```

**Full description**
```
Glitch Trend Follower cBot wraps the Glitch Trend Follower signal in a
disciplined execution layer. Every entry is sized so the SL distance × pip
value × position size equals exactly RiskPerTradePct (default 0.5 %) of
account equity. ATR-based stops and targets adapt to instrument volatility
automatically — no per-symbol tuning required for a clean first run.

Risk controls
  • Fixed-risk position sizer using current account balance and SL distance
  • Hard volume cap (MaxVolumeUnits) so a misconfigured pip value can't
    blow up
  • Daily-loss halt: when intraday P&L hits DailyLossHaltPercent of the
    UTC-day-open balance, the bot suspends new entries until the day
    rolls — a built-in answer to prop-firm daily-loss rules
  • Never pyramids: one position per symbol per direction at a time

Tested defaults are tuned for H1 indices and crypto. For forex pairs raise
AtrSlMultiplier to ≥ 2.0 to keep stops outside typical spread+noise.

This is the same trend-following module the GlitchExecutor live engine has
run since 2026-04. Identical signal output to the Glitch Trend Follower
indicator — buy the indicator first to inspect the signal on your charts
before automating.
```

**Tags**: same as indicator + add Strategy: Risk Management.

**Price**: $39 launch.

---

## Submission checklist

Before hitting "Publish":

- [ ] Compile both `.cs` files in cTrader Automate IDE → produce `.algo` artefacts
- [ ] Backtest the cBot in cTrader's built-in backtester on **at least three**
      different symbols (JPN225 H1, BTCUSD H1, EURUSD H1) — keep the equity
      curves as PNGs for the screenshot set
- [ ] Capture the three screenshots above (≥ 800 px wide, ≤ 2 MB each)
- [ ] Create `logo.png` (300×300, ≤ 1 MB) — clean wordmark on dark background
- [ ] Optional: record 30-sec YouTube walkthrough, get the video badge
- [ ] Paste copy from this file into the store's product form
- [ ] Set price at exactly the floor ($19 / $39) for launch; raise later

## Post-launch

- Bundle this with the next two ports (mean-reverter, momentum-hunter) into
  a "Glitch Snake Pack" once each individually has ≥ 3 buyers. Bundle pricing
  is allowed and reportedly converts well.
- Live signal version (subscription-style) is not supported by the store —
  if you want recurring revenue, that channel runs separately (Discord /
  Telegram paid feed, billed via Stripe).
