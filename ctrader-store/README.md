# cTrader Store products

Source for the cAlgo C# indicators and cBots published under the
GlitchExecutor cTrader Store seller account (approved 2026-05-13).

Each subfolder is one product family — a paired indicator + cBot that
share the same signal logic — with:

  - `*.cs`        cAlgo source (compile in cTrader Automate IDE to `.algo`)
  - `LISTING.md`  ready-to-paste title / short / full description / tags /
                  screenshot brief / price floor
  - `screenshot-*.png` + `logo.png` (binary assets, not committed by default)

Per the store rules: source is never transmitted with the upload — the
platform encrypts and per-user-locks the compiled `.algo`. Keep this
repo private. The seller workflow is:

  1. `cs` → compile in cTrader Automate IDE → `.algo`
  2. Upload `.algo` + screenshots + logo via the seller dashboard
  3. Review takes 1-3 business days
  4. 70 % of price goes to the seller; cTrader retains 30 %

## Current line-up

| Folder              | Indicator                       | cBot                             | Status        |
|---------------------|---------------------------------|----------------------------------|---------------|
| `trend-follower/`   | Glitch Trend Follower ($19)     | Glitch Trend Follower cBot ($39) | source ready  |

## Roadmap

Next ports in priority order — each maps 1:1 to a base model in
`/opt/glitch-ouroboros/ctrader/ensemble/models/`:

  - mean-reverter      (Bollinger reversion + RSI confirmation)
  - momentum-hunter    (Donchian breakout + volume confirmation)
  - mamba-reversion    (the standalone reversion ensemble used by the
                        `mamba` bot — strongest reward:risk on the demo
                        engine, 4.77 R:R)
  - multi-tf-align     (cross-timeframe SMA/EMA alignment scorer)
  - session-analyst    (London / NY session bias filter — indicator only)
  - volume-profiler    (volume-by-price overlay — indicator only)

After 3 paired products land, bundle the trio as a "Snake Pack" at a
discount; the store supports bundle listings.
