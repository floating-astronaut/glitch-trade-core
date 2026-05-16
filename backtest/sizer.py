"""
Risk-aware position sizer for the backtester.

The live engine sizes positions per-bot, often well above what a 5 %-trailing
prop-firm account can absorb. We rescale historical trades so the simulated
$-risk per trade tracks `rules.risk_per_trade_pct` of the account at the
moment the trade opened.

Strategy
--------
For a historical trade we have:
  • entry_price, sl, lot_size, contract_value  (from ml_trades)
  • realised pnl                                (from ml_trades)

The trade's *intended* dollar risk at entry was approximately
    intended_risk = |entry - sl| × point_value × lots
which lives implicitly in the lot size the live engine chose. To rescale
to a target $-risk of `R = balance × risk_per_trade_pct`, we apply a
scale factor:
    scale = R / intended_risk
and multiply the realised pnl by `scale`. This is exact when stops never
move; close enough when they don't move much.

If a historical row lacks SL data we fall back to the legacy assumption that
`lot_size` itself was the live engine's sizing — and we cap the trade to
`risk_per_trade_pct` of account based on a per-symbol pessimistic ATR.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .rules import FundingPipsZeroRules


# Coarse $-per-point-per-lot table for the symbols the engine actually trades.
# These are good enough for sizing math; bar-replay mode will pull from the
# broker's SymbolsList directly.
POINT_VALUE_USD_PER_LOT: dict[str, float] = {
    # Indices (1 point ≈ $1/lot for cTrader CFD contracts)
    "JPN225": 1.0,
    "GER40":  1.0,
    "UK100":  1.0,
    "US500":  1.0,
    "US30":   1.0,
    "NAS100": 1.0,
    # Metals (XAUUSD: 1 USD price move × 100 troy oz / lot = $100; XAGUSD: $50)
    "XAUUSD": 100.0,
    "XAGUSD":  50.0,
    # Crypto (cTrader BTCUSD lot = 1 BTC; ETHUSD lot = 1 ETH)
    "BTCUSD":   1.0,
    "ETHUSD":   1.0,
    "SOLUSD":   1.0,
    # Forex majors (100k notional, ~$10 per pip for X.XXXX pairs; JPY pairs ≈ $9)
    "EURUSD": 100_000.0,
    "GBPUSD": 100_000.0,
    "AUDUSD": 100_000.0,
    "NZDUSD": 100_000.0,
    "USDCAD": 100_000.0,
    "USDCHF": 100_000.0,
    "USDJPY": 100_000.0,
}


@dataclass(frozen=True)
class SizingResult:
    scale: float           # multiplier applied to historical pnl
    scaled_pnl: float
    intended_risk: float   # original $-risk (from entry/SL)
    target_risk: float     # account_balance × risk_per_trade_pct
    capped: bool           # True if we hit the hard cap


def estimate_trade_risk_usd(
    symbol: str,
    entry: Optional[float],
    sl: Optional[float],
    lots: Optional[float],
) -> Optional[float]:
    """Approximate intended USD risk at entry. None when we can't compute."""
    if not (entry and sl and lots) or symbol not in POINT_VALUE_USD_PER_LOT:
        return None
    distance = abs(entry - sl)
    if distance <= 0:
        return None
    # For FX, the "distance" is in price units (e.g. 0.0010 for EURUSD).
    # POINT_VALUE_USD_PER_LOT is in $/price-unit/lot, so the formula is the same
    # for every asset class.
    return distance * POINT_VALUE_USD_PER_LOT[symbol] * lots


def scale_trade(
    *,
    balance: float,
    realised_pnl: float,
    symbol: str,
    entry: Optional[float],
    sl: Optional[float],
    lots: Optional[float],
    rules: FundingPipsZeroRules,
    sizing_base: Optional[float] = None,
) -> SizingResult:
    """Return a scaled pnl such that the trade's $-risk targets
    `rules.risk_per_trade_pct` of `sizing_base` (defaults to `balance`),
    capped by `risk_per_trade_pct_hard_cap`.

    Important: with a trailing-DD prop-firm rule, sizing off the current
    balance is dangerous — early wins inflate position size, then a normal
    loss eats more than the trailing-DD buffer above the new HWM. Pass
    `sizing_base=min(starting_balance, current_balance)` to keep position
    size bounded by the *original* account size, which is the right
    behaviour for FundingPips-style accounts.

    Cap semantics (the bit that catches the catastrophic case):
      `scale = target / intended` assumes the live SL held — i.e. that
      |realised_pnl| ≈ intended_risk. When the SL didn't hold (slippage,
      no-SL strategy, manually-widened SL after entry), |realised_pnl|
      can be many multiples of intended_risk, and scaling-up that
      already-blown loss wipes the account in one trade. We always
      verify `|scaled_pnl| ≤ cap` AFTER scaling, and bound it if not.
      This is the layer that actually makes the prop-firm replay honest.
    """
    base = sizing_base if sizing_base is not None else balance
    target = base * rules.risk_per_trade_pct
    cap = base * rules.risk_per_trade_pct_hard_cap

    intended = estimate_trade_risk_usd(symbol, entry, sl, lots)
    if intended is None or intended <= 0:
        # We can't recover the intended SL distance — fall back to clamping
        # by absolute pnl. ANY trade whose realised |pnl| exceeds the cap
        # gets scaled down to it (both wins and losses). The earlier
        # version only capped losses, which let a single big winner on a
        # NULL-SL ml_trades row (often a bot exit-on-condition without a
        # hard stop logged) compound into 8000%+ runs on the FTMO replay.
        if abs(realised_pnl) > cap:
            scale = cap / abs(realised_pnl)
            return SizingResult(
                scale=scale,
                scaled_pnl=realised_pnl * scale,
                intended_risk=abs(realised_pnl),
                target_risk=target,
                capped=True,
            )
        return SizingResult(scale=1.0, scaled_pnl=realised_pnl,
                            intended_risk=abs(realised_pnl),
                            target_risk=target, capped=False)

    # Provisional scale assuming the SL held.
    scale = target / intended
    scaled_pnl = realised_pnl * scale

    # Hard cap: the absolute $-loss after scaling must NEVER exceed the
    # rules' hard cap. This is the line that closes the original bug —
    # the previous check (intended*scale > cap) was mathematically
    # vacuous: target<cap by construction, so the condition could only
    # fire in pathological configs. We now check the actual scaled loss
    # against the cap, which catches the realistic case where the SL
    # slipped and the live engine's realised loss was many multiples
    # of its intended risk.
    if scaled_pnl < -cap:
        new_scale = abs(cap / realised_pnl)
        return SizingResult(
            scale=new_scale,
            scaled_pnl=realised_pnl * new_scale,
            intended_risk=intended,
            target_risk=target,
            capped=True,
        )
    # Symmetric upside cap — a freakishly tight SL on a runaway winner
    # shouldn't compound into 50%-in-a-day either (consistency-rule
    # breach risk + unrealistic). Same hard cap, opposite sign.
    if scaled_pnl > cap:
        new_scale = cap / realised_pnl
        return SizingResult(
            scale=new_scale,
            scaled_pnl=realised_pnl * new_scale,
            intended_risk=intended,
            target_risk=target,
            capped=True,
        )

    return SizingResult(
        scale=scale,
        scaled_pnl=scaled_pnl,
        intended_risk=intended,
        target_risk=target,
        capped=False,
    )
