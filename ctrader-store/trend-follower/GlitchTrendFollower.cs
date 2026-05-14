// =============================================================================
// Glitch Trend Follower — cTrader Indicator
//
// Port of the "trend_follower" base strategy from the GlitchExecutor Ouroboros
// ensemble engine. Classical-TA only — no ML pickles, no external data feeds,
// no embedded credentials. Buyers get a fully self-contained indicator that
// plots BUY / SELL / HOLD signals and a confidence series.
//
// Algorithm
// ---------
//   1. SMA(SmaPeriod) and EMA(EmaPeriod) over the close series.
//   2. Detect a crossover within the last CrossoverLookback bars.
//   3. Confirm with ADX(AdxPeriod) > AdxMinTrend.
//   4. ATR(AtrPeriod) vs its rolling-median over AtrMedianWindow as a
//      confidence modifier (not a hard gate).
//
//   Confidence buckets:
//     ADX ≥ AdxStrong  → StrongConfidence (default 0.90)
//     ADX ≥ AdxMid     → MidConfidence    (default 0.75)
//     ADX > MinTrend   → LowConfidence    (default 0.60)
//   Low ATR (below rolling median) subtracts LowVolPenalty, floored at
//   MinConfidenceFloor.
//
// Outputs
// -------
//   Vote        +1 for BUY, -1 for SELL, 0 for HOLD
//   Confidence  0.00–0.90 corresponding to the bucket
//
// Defaults are the published reference parameters for the H1 timeframe;
// indicator is timeframe-agnostic so you can apply it on any chart.
// =============================================================================

using System;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

namespace cAlgo
{
    [Levels(0, 1, -1)]
    [Indicator(IsOverlay = false, TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
    public class GlitchTrendFollower : Indicator
    {
        // ── Strategy parameters (mirror the JSON config in the Python engine) ──

        [Parameter("SMA period",          DefaultValue = 9,   MinValue = 2)]
        public int SmaPeriod { get; set; }

        [Parameter("EMA period",          DefaultValue = 21,  MinValue = 2)]
        public int EmaPeriod { get; set; }

        [Parameter("ADX period",          DefaultValue = 14,  MinValue = 2)]
        public int AdxPeriod { get; set; }

        [Parameter("ATR period",          DefaultValue = 14,  MinValue = 2)]
        public int AtrPeriod { get; set; }

        [Parameter("Crossover lookback",  DefaultValue = 5,   MinValue = 1)]
        public int CrossoverLookback { get; set; }

        [Parameter("ATR median window",   DefaultValue = 100, MinValue = 20)]
        public int AtrMedianWindow { get; set; }

        [Parameter("ADX min trend",       DefaultValue = 15.0)]
        public double AdxMinTrend { get; set; }

        [Parameter("ADX strong",          DefaultValue = 25.0)]
        public double AdxStrong { get; set; }

        [Parameter("ADX mid",             DefaultValue = 20.0)]
        public double AdxMid { get; set; }

        [Parameter("Strong confidence",   DefaultValue = 0.90, MinValue = 0.0, MaxValue = 1.0)]
        public double StrongConfidence { get; set; }

        [Parameter("Mid confidence",      DefaultValue = 0.75, MinValue = 0.0, MaxValue = 1.0)]
        public double MidConfidence { get; set; }

        [Parameter("Low confidence",      DefaultValue = 0.60, MinValue = 0.0, MaxValue = 1.0)]
        public double LowConfidence { get; set; }

        [Parameter("Low-vol penalty",     DefaultValue = 0.15)]
        public double LowVolPenalty { get; set; }

        [Parameter("Min confidence floor",DefaultValue = 0.45)]
        public double MinConfidenceFloor { get; set; }

        // ── Outputs ─────────────────────────────────────────────────────────

        [Output("Vote",       LineColor = "Gold",       PlotType = PlotType.Histogram,
                              Thickness = 2)]
        public IndicatorDataSeries Vote { get; set; }

        [Output("Confidence", LineColor = "DodgerBlue", PlotType = PlotType.Line,
                              Thickness = 2)]
        public IndicatorDataSeries Confidence { get; set; }

        // ── Internal indicators ─────────────────────────────────────────────

        private SimpleMovingAverage _sma;
        private ExponentialMovingAverage _ema;
        private DirectionalMovementSystem _dms;
        private AverageTrueRange _atr;

        protected override void Initialize()
        {
            _sma = Indicators.SimpleMovingAverage(Bars.ClosePrices, SmaPeriod);
            _ema = Indicators.ExponentialMovingAverage(Bars.ClosePrices, EmaPeriod);
            _dms = Indicators.DirectionalMovementSystem(AdxPeriod);
            _atr = Indicators.AverageTrueRange(AtrPeriod, MovingAverageType.Simple);
        }

        public override void Calculate(int index)
        {
            // Need enough history for the indicators + crossover scan.
            int minBars = Math.Max(EmaPeriod + CrossoverLookback,
                                   Math.Max(AdxPeriod, AtrPeriod) + 2);
            if (index < minBars)
            {
                Vote[index] = 0;
                Confidence[index] = double.NaN;
                return;
            }

            double smaNow = _sma.Result[index];
            double emaNow = _ema.Result[index];
            double adxNow = _dms.ADX[index];
            double atrNow = _atr.Result[index];

            if (double.IsNaN(smaNow) || double.IsNaN(emaNow)
                || double.IsNaN(adxNow) || double.IsNaN(atrNow))
            {
                Vote[index] = 0;
                Confidence[index] = double.NaN;
                return;
            }

            // ── Crossover detection ────────────────────────────────────────
            // Bullish crossover: SMA crossed above EMA in the last N bars.
            // Bearish: SMA crossed below EMA in the last N bars.
            int firstScan = Math.Max(1, index - CrossoverLookback + 1);
            bool bullish = false;
            bool bearish = false;
            for (int i = firstScan; i <= index; i++)
            {
                double sp = _sma.Result[i - 1];
                double ep = _ema.Result[i - 1];
                double sn = _sma.Result[i];
                double en = _ema.Result[i];
                if (double.IsNaN(sp) || double.IsNaN(ep) ||
                    double.IsNaN(sn) || double.IsNaN(en)) continue;
                if (sp <= ep && sn > en) bullish = true;
                else if (sp >= ep && sn < en) bearish = true;
            }

            // ── Trend gate ────────────────────────────────────────────────
            bool trendExists = adxNow > AdxMinTrend;
            if (!trendExists || (!bullish && !bearish))
            {
                Vote[index] = 0;
                Confidence[index] = 0;
                return;
            }

            // ── Confidence bucket ─────────────────────────────────────────
            double conf;
            if (adxNow >= AdxStrong)        conf = StrongConfidence;
            else if (adxNow >= AdxMid)      conf = MidConfidence;
            else                            conf = LowConfidence;

            // ── ATR confidence modifier ───────────────────────────────────
            double atrMedian = RollingMedian(_atr.Result, index, AtrMedianWindow);
            if (!double.IsNaN(atrMedian) && atrNow < atrMedian)
            {
                conf = Math.Max(MinConfidenceFloor, conf - LowVolPenalty);
            }

            Vote[index] = bullish ? 1 : -1;
            Confidence[index] = Math.Round(conf, 2);
        }

        // ── Helper ─────────────────────────────────────────────────────────

        private static double RollingMedian(IndicatorDataSeries series, int endIndex, int window)
        {
            int start = Math.Max(0, endIndex - window + 1);
            int n = endIndex - start + 1;
            if (n <= 0) return double.NaN;

            var buf = new double[n];
            int k = 0;
            for (int i = start; i <= endIndex; i++)
            {
                double v = series[i];
                if (!double.IsNaN(v)) buf[k++] = v;
            }
            if (k == 0) return double.NaN;
            Array.Sort(buf, 0, k);
            return k % 2 == 1 ? buf[k / 2] : 0.5 * (buf[k / 2 - 1] + buf[k / 2]);
        }
    }
}
