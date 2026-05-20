// =============================================================================
// Glitch Trend Follower — cTrader cBot
//
// Companion to the GlitchTrendFollower indicator. Same signal logic, but
// places actual market orders with ATR-based stop-loss and take-profit and
// fixed-risk position sizing (default 0.5 % of equity per trade).
//
// Risk model
// ----------
//   • Position size is computed from the account balance, the per-trade
//     risk percentage, and the SL distance in pips. Never exceeds the
//     volume cap configured below.
//   • One position per symbol per direction at a time. Re-entry only after
//     the prior position closes.
//   • Daily drawdown halt: trading is suspended for the rest of the UTC
//     day once losses reach DailyLossHaltPercent of the day-open balance.
//     This is a built-in safety net — works well with prop-firm rule sets
//     that require strict daily-loss control.
//
// Tested defaults are for H1 charts on indices (JPN225, GER40, UK100) and
// crypto (BTCUSD, ETHUSD). Forex pairs typically need wider AtrSlMultiplier
// because spreads are tighter relative to typical moves.
// =============================================================================

using System;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

// ── Templated credentials (CBOT-DIST-1 / -2) ─────────────────────
// algo_pack.py's `_inject_credentials` replaces the marker strings
// below with the operator's freshly-minted API key, user id, and
// ingest-base URL at .algo download time. Standalone the template
// still compiles — heartbeats POST to the placeholder URL and
// silently fail.
namespace GlitchExecutorCredentials
{
    public static class Credentials
    {
        public const string ApiKey     = "__GLITCH_API_KEY__";
        public const string UserId     = "__GLITCH_USER_ID__";
        public const string IngestBase = "__GLITCH_INGEST_BASE__";
    }
}

namespace cAlgo.Robots
{
    // AccessRights.FullAccess is required so the cBot can POST a
    // 30 s heartbeat to /v1/me/cbot/heartbeat (CBOT-DIST-2). cTrader
    // Desktop will show a one-time install warning that the cBot
    // needs network + filesystem access; the install guide
    // (CBOT-DIST-3, Settings → cBot Setup) explains why.
    [Robot(AccessRights = AccessRights.FullAccess, TimeZone = TimeZones.UTC,
           AddIndicators = true)]
    public class GlitchTrendFollowerBot : Robot
    {
        // ── Signal parameters (mirror the indicator) ────────────────────────

        [Parameter("SMA period",          DefaultValue = 9,   MinValue = 2, Group = "Signal")]
        public int SmaPeriod { get; set; }

        [Parameter("EMA period",          DefaultValue = 21,  MinValue = 2, Group = "Signal")]
        public int EmaPeriod { get; set; }

        [Parameter("ADX period",          DefaultValue = 14,  MinValue = 2, Group = "Signal")]
        public int AdxPeriod { get; set; }

        [Parameter("ATR period",          DefaultValue = 14,  MinValue = 2, Group = "Signal")]
        public int AtrPeriod { get; set; }

        [Parameter("Crossover lookback",  DefaultValue = 5,   MinValue = 1, Group = "Signal")]
        public int CrossoverLookback { get; set; }

        [Parameter("ADX min trend",       DefaultValue = 15.0, Group = "Signal")]
        public double AdxMinTrend { get; set; }

        [Parameter("Min confidence to trade", DefaultValue = 0.60, MinValue = 0.0, MaxValue = 1.0,
                   Group = "Signal")]
        public double MinTradeConfidence { get; set; }

        // ── Trade management ───────────────────────────────────────────────

        [Parameter("Risk per trade (% equity)", DefaultValue = 0.5, MinValue = 0.01, MaxValue = 5.0,
                   Group = "Risk")]
        public double RiskPerTradePct { get; set; }

        [Parameter("Max position volume (units)", DefaultValue = 100000, MinValue = 1,
                   Group = "Risk")]
        public double MaxVolumeUnits { get; set; }

        [Parameter("Stop-loss ATR multiplier",  DefaultValue = 1.5, MinValue = 0.1,
                   Group = "Risk")]
        public double AtrSlMultiplier { get; set; }

        [Parameter("Take-profit ATR multiplier", DefaultValue = 3.0, MinValue = 0.1,
                   Group = "Risk")]
        public double AtrTpMultiplier { get; set; }

        [Parameter("Daily loss halt (% balance)", DefaultValue = 2.5, MinValue = 0.1, MaxValue = 10.0,
                   Group = "Risk")]
        public double DailyLossHaltPercent { get; set; }

        [Parameter("Label",               DefaultValue = "GlitchTF", Group = "Misc")]
        public string Label { get; set; }

        [Parameter("Allow longs",         DefaultValue = true,  Group = "Misc")]
        public bool AllowLongs { get; set; }

        [Parameter("Allow shorts",        DefaultValue = true,  Group = "Misc")]
        public bool AllowShorts { get; set; }

        // ── Internal state ──────────────────────────────────────────────────

        private SimpleMovingAverage _sma;
        private ExponentialMovingAverage _ema;
        private DirectionalMovementSystem _dms;
        private AverageTrueRange _atr;

        private DateTime _currentUtcDay;
        private double _dayOpenBalance;
        private bool _haltedToday;

        // ── Heartbeat plumbing (CBOT-DIST-2) ─────────────────────
        // Static HttpClient — one socket pool for the lifetime of
        // the cBot, avoids the per-call connection thrash that
        // bites short-lived HttpClient instances. cAlgo runs each
        // cBot in its own process, so static is process-local.
        private static readonly HttpClient _http = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(10),
        };
        private const int HeartbeatIntervalSeconds = 30;
        private DateTime _lastHeartbeatAt = DateTime.MinValue;

        protected override void OnStart()
        {
            _sma = Indicators.SimpleMovingAverage(Bars.ClosePrices, SmaPeriod);
            _ema = Indicators.ExponentialMovingAverage(Bars.ClosePrices, EmaPeriod);
            _dms = Indicators.DirectionalMovementSystem(AdxPeriod);
            _atr = Indicators.AverageTrueRange(AtrPeriod, MovingAverageType.Simple);

            _currentUtcDay = Server.Time.Date;
            _dayOpenBalance = Account.Balance;
            _haltedToday = false;

            // First heartbeat fires immediately so the operator sees
            // the cBot come alive in the matrix the moment they hit
            // Start. Subsequent ticks are throttled by
            // HeartbeatIntervalSeconds in OnTick below.
            SendHeartbeat();
        }

        protected override void OnTick()
        {
            // cTrader fires OnTick on every quote — far too noisy for a
            // 30s heartbeat. We throttle by wall-clock here rather than
            // using cAlgo's Timer API so the call doesn't run on cAlgo's
            // UI thread.
            if ((DateTime.UtcNow - _lastHeartbeatAt).TotalSeconds >= HeartbeatIntervalSeconds)
            {
                SendHeartbeat();
            }
        }

        private void SendHeartbeat()
        {
            _lastHeartbeatAt = DateTime.UtcNow;
            try
            {
                var url = GlitchExecutorCredentials.Credentials.IngestBase + "/me/cbot/heartbeat";
                var json = "{\"ctid_trader_account_id\":" + Account.Number + "}";
                var req = new HttpRequestMessage(HttpMethod.Post, url);
                req.Headers.Add("Authorization", "Bearer " + GlitchExecutorCredentials.Credentials.ApiKey);
                req.Content = new StringContent(json, Encoding.UTF8, "application/json");

                // Fire-and-forget — never block the cBot's OnTick on
                // network. Any non-200 is silently ignored; the matrix
                // chip will simply read "Xm ago" until the next
                // successful call.
                _http.SendAsync(req)
                     .ContinueWith(t => { var _ = t.Exception; },
                                   TaskContinuationOptions.OnlyOnFaulted);
            }
            catch (Exception)
            {
                // Network unavailable, bad token, etc. — never crash
                // the cBot for a heartbeat failure. The trading loop
                // must keep running.
            }
        }

        protected override void OnBar()
        {
            RollDay();
            if (_haltedToday) return;

            int idx = Bars.ClosePrices.Count - 2;  // last closed bar
            if (idx < Math.Max(EmaPeriod + CrossoverLookback,
                               Math.Max(AdxPeriod, AtrPeriod) + 2)) return;

            // ── Compute signal ────────────────────────────────────────────
            double sma = _sma.Result[idx];
            double ema = _ema.Result[idx];
            double adx = _dms.ADX[idx];
            double atrVal = _atr.Result[idx];
            if (double.IsNaN(sma) || double.IsNaN(ema) ||
                double.IsNaN(adx) || double.IsNaN(atrVal)) return;
            if (adx <= AdxMinTrend) return;

            bool bullish = false, bearish = false;
            int firstScan = Math.Max(1, idx - CrossoverLookback + 1);
            for (int i = firstScan; i <= idx; i++)
            {
                double sp = _sma.Result[i - 1], ep = _ema.Result[i - 1];
                double sn = _sma.Result[i],     en = _ema.Result[i];
                if (double.IsNaN(sp) || double.IsNaN(ep) ||
                    double.IsNaN(sn) || double.IsNaN(en)) continue;
                if (sp <= ep && sn > en) bullish = true;
                else if (sp >= ep && sn < en) bearish = true;
            }
            if (!bullish && !bearish) return;

            double conf = adx >= 25 ? 0.90 : (adx >= 20 ? 0.75 : 0.60);
            if (conf < MinTradeConfidence) return;

            TradeType side = bullish ? TradeType.Buy : TradeType.Sell;
            if (side == TradeType.Buy  && !AllowLongs)  return;
            if (side == TradeType.Sell && !AllowShorts) return;

            // Don't pyramid on an existing position from this bot on this symbol.
            foreach (var p in Positions)
                if (p.Label == Label && p.SymbolName == Symbol.Name && p.TradeType == side)
                    return;

            // ── Size the position ─────────────────────────────────────────
            double slDistancePrice = atrVal * AtrSlMultiplier;
            double tpDistancePrice = atrVal * AtrTpMultiplier;
            double slPips = slDistancePrice / Symbol.PipSize;
            double tpPips = tpDistancePrice / Symbol.PipSize;

            if (slPips < Symbol.Spread / Symbol.PipSize * 2) return;  // SL too tight vs spread

            double riskAmount = Account.Balance * (RiskPerTradePct / 100.0);
            double pipValuePerUnit = Symbol.PipValue;  // value of 1 pip per 1 unit
            if (pipValuePerUnit <= 0) return;

            double volume = riskAmount / (slPips * pipValuePerUnit);
            volume = Symbol.NormalizeVolumeInUnits(volume, RoundingMode.Down);
            volume = Math.Min(volume, MaxVolumeUnits);
            volume = Math.Max(volume, Symbol.VolumeInUnitsMin);
            if (volume <= 0 || volume > MaxVolumeUnits + 1) return;

            ExecuteMarketOrder(side, Symbol.Name, volume, Label, slPips, tpPips);
        }

        // ── Daily-loss halt ────────────────────────────────────────────────

        private void RollDay()
        {
            var today = Server.Time.Date;
            if (today != _currentUtcDay)
            {
                _currentUtcDay = today;
                _dayOpenBalance = Account.Balance;
                _haltedToday = false;
                return;
            }
            if (_haltedToday) return;

            double dayPnL = Account.Balance - _dayOpenBalance;
            double haltThreshold = -_dayOpenBalance * (DailyLossHaltPercent / 100.0);
            if (dayPnL <= haltThreshold)
            {
                _haltedToday = true;
                Print("[GlitchTF] Daily-loss halt triggered: P&L {0:F2} ≤ threshold {1:F2}. "
                      + "No new entries until UTC day rolls.", dayPnL, haltThreshold);
            }
        }
    }
}
