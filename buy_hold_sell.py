"""
Buy / Hold / Sell analyzer.

For each stock in portfolio.csv:
  - Fetch total-return price history (adjusted close) from Yahoo Finance.
  - Compute 1-year, 3-year, and 5-year total returns.
  - Compare each available return to the S&P 500 (^GSPC) over the same period.
  - Score 2-3 wins -> BUY, 1 win -> HOLD, 0 wins -> SELL.
  - Stocks younger than a given window are scored only on periods they qualify for
    (e.g. a 2-year-old stock is judged 0/1 -> SELL, 1/1 -> BUY).

Outputs:
  - recommendations.csv
  - recommendations.html (self-contained, opens in any browser)

Requires:
  pip install yfinance pandas
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf


PORTFOLIO_CSV = Path("portfolio.csv")
OUTPUT_CSV = Path("recommendations.csv")
OUTPUT_HTML = Path("recommendations.html")
BENCHMARK = "^GSPC"  # S&P 500 index
PERIODS_YEARS = (1, 3, 5)
# How close is "close enough" when looking for a price N years ago.
# Markets are closed on weekends/holidays, so we allow a small window.
LOOKBACK_TOLERANCE_DAYS = 7


@dataclass
class StockResult:
    symbol: str
    returns: dict[int, Optional[float]]      # years -> return (e.g. 0.23 = 23%), None if N/A
    beats: dict[int, Optional[bool]]         # years -> True/False/None (None = couldn't compare)
    score: int                                # number of "beats"
    eligible_periods: int                    # how many periods we could actually judge on
    recommendation: str                      # BUY / HOLD / SELL / ERROR
    note: str                                # human-readable note (e.g. "2/2 years")
    error: Optional[str] = None


def fetch_price_history(ticker: str, years: int = 6) -> pd.DataFrame:
    """Fetch enough history to cover our longest lookback, using auto-adjusted
    prices so dividends and splits are baked in (= total return)."""
    end = datetime.today()
    start = end - timedelta(days=365 * years + 30)
    df = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        auto_adjust=True,     # adjusts Close for splits AND dividends -> total return
        progress=False,
        threads=False,
    )
    # yfinance sometimes returns a multi-index column frame for a single ticker;
    # flatten it so df["Close"] always works.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def price_on_or_near(df: pd.DataFrame, target_date: datetime) -> Optional[float]:
    """Return the adjusted close on target_date, or the nearest trading day within
    a small tolerance window. Returns None if no match is found (e.g. stock didn't
    exist yet)."""
    if df.empty:
        return None
    # Find the closest index entry on or before target_date
    idx = df.index[df.index <= pd.Timestamp(target_date)]
    if len(idx) == 0:
        return None
    candidate_date = idx[-1]
    gap_days = (pd.Timestamp(target_date) - candidate_date).days
    if gap_days > LOOKBACK_TOLERANCE_DAYS:
        # There IS data before target_date, but the closest point is too far back
        # (means we're asking for a date before the stock started trading).
        return None
    return float(df.loc[candidate_date, "Close"])


def compute_returns(df: pd.DataFrame) -> dict[int, Optional[float]]:
    """Compute 1yr, 3yr, 5yr total returns from an auto-adjusted price frame."""
    if df.empty:
        return {y: None for y in PERIODS_YEARS}

    latest_price = float(df["Close"].iloc[-1])
    latest_date = df.index[-1].to_pydatetime()

    results: dict[int, Optional[float]] = {}
    for years in PERIODS_YEARS:
        past_date = latest_date - timedelta(days=365 * years)
        past_price = price_on_or_near(df, past_date)
        if past_price is None or past_price == 0:
            results[years] = None
        else:
            results[years] = (latest_price - past_price) / past_price
    return results


def analyze_stock(symbol: str, benchmark_returns: dict[int, Optional[float]]) -> StockResult:
    try:
        df = fetch_price_history(symbol)
    except Exception as e:
        return StockResult(
            symbol=symbol, returns={y: None for y in PERIODS_YEARS},
            beats={y: None for y in PERIODS_YEARS}, score=0,
            eligible_periods=0, recommendation="ERROR", note="fetch failed",
            error=str(e),
        )

    if df.empty:
        return StockResult(
            symbol=symbol, returns={y: None for y in PERIODS_YEARS},
            beats={y: None for y in PERIODS_YEARS}, score=0,
            eligible_periods=0, recommendation="ERROR", note="no data returned",
            error="empty dataframe",
        )

    stock_returns = compute_returns(df)

    beats: dict[int, Optional[bool]] = {}
    score = 0
    eligible = 0
    for years in PERIODS_YEARS:
        sr = stock_returns[years]
        br = benchmark_returns.get(years)
        if sr is None or br is None:
            beats[years] = None
            continue
        eligible += 1
        won = sr > br
        beats[years] = won
        if won:
            score += 1

    # Scoring rules (per client):
    #   - Full 3-period history (1yr + 3yr + 5yr all available):
    #       0 beats -> SELL, 1 -> HOLD, 2-3 -> BUY
    #   - Young stocks (missing the 5yr data point because the stock is
    #     under ~5 years old): cap at HOLD. Any beat(s) against the 1yr
    #     benchmark -> HOLD; zero beats -> SELL. Never BUY.
    #   - No comparable history at all -> SELL.
    has_five_year_data = stock_returns[5] is not None
    if eligible == 0:
        recommendation = "SELL"
        note = "0/0 years"
    elif not has_five_year_data:
        # Young stock: HOLD ceiling
        recommendation = "HOLD" if score >= 1 else "SELL"
        note = f"{score}/{eligible} years"
    else:
        # Full history: normal rules
        if score == 0:
            recommendation = "SELL"
        elif score == 1:
            recommendation = "HOLD"
        else:
            recommendation = "BUY"
        note = f"{score}/{eligible} years"

    return StockResult(
        symbol=symbol, returns=stock_returns, beats=beats,
        score=score, eligible_periods=eligible,
        recommendation=recommendation, note=note,
    )


def load_symbols(path: Path) -> list[str]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        return [row["Symbol"].strip() for row in reader if row.get("Symbol", "").strip()]


def fmt_pct(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"{x * 100:+.1f}%"


def write_csv(results: list[StockResult], bench: dict[int, Optional[float]], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "Symbol", "Recommendation", "Score",
            "1yr Return", "3yr Return", "5yr Return",
            "Beat SPX 1yr", "Beat SPX 3yr", "Beat SPX 5yr",
            "Error",
        ])
        for r in results:
            def beat_cell(y: int) -> str:
                b = r.beats[y]
                return "" if b is None else ("Yes" if b else "No")
            w.writerow([
                r.symbol, r.recommendation, r.note,
                fmt_pct(r.returns[1]), fmt_pct(r.returns[3]), fmt_pct(r.returns[5]),
                beat_cell(1), beat_cell(3), beat_cell(5),
                r.error or "",
            ])


def write_html(results: list[StockResult], bench: dict[int, Optional[float]], path: Path) -> None:
    generated = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    buys  = sum(1 for r in results if r.recommendation == "BUY")
    holds = sum(1 for r in results if r.recommendation == "HOLD")
    sells = sum(1 for r in results if r.recommendation == "SELL")
    errors = sum(1 for r in results if r.recommendation == "ERROR")

    def row_html(r: StockResult) -> str:
        def cell(y: int) -> str:
            ret = fmt_pct(r.returns[y])
            b = r.beats[y]
            if b is None:
                cls = "na"
            elif b:
                cls = "win"
            else:
                cls = "loss"
            return f'<td class="num {cls}">{ret}</td>'
        rec_class = r.recommendation.lower()
        return (
            f'<tr>'
            f'<td class="sym">{r.symbol}</td>'
            f'{cell(1)}{cell(3)}{cell(5)}'
            f'<td class="note">{r.note}</td>'
            f'<td><span class="tag {rec_class}">{r.recommendation}</span></td>'
            f'</tr>'
        )

    # Sort: BUY first, then HOLD, then SELL, then ERROR; alphabetical within group
    order = {"BUY": 0, "HOLD": 1, "SELL": 2, "ERROR": 3}
    sorted_results = sorted(results, key=lambda r: (order.get(r.recommendation, 9), r.symbol))

    rows_html = "\n".join(row_html(r) for r in sorted_results)
    bench_row = (
        f'<div class="bench-line"><span class="bench-label">S&amp;P 500 Benchmark</span>'
        f'<span><b>1yr</b> {fmt_pct(bench[1])}</span>'
        f'<span><b>3yr</b> {fmt_pct(bench[3])}</span>'
        f'<span><b>5yr</b> {fmt_pct(bench[5])}</span></div>'
        f'<div class="legend">'
        f'<span class="swatch win"></span> beat the benchmark &nbsp;&middot;&nbsp; '
        f'<span class="swatch loss"></span> lagged the benchmark &nbsp;&middot;&nbsp; '
        f'<span class="swatch na"></span> insufficient history'
        f'</div>'
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Portfolio Signal &mdash; {generated}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,400;0,600;0,800;1,400&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink: #0c0a08;
    --paper: #f5f1e8;
    --paper-dim: #ebe5d5;
    --rule: #1a1714;
    --buy: #1f6b3a;
    --hold: #b8860b;
    --sell: #a32020;
    --err: #555;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--paper); color: var(--ink); }}
  body {{
    font-family: 'Fraunces', Georgia, serif;
    font-feature-settings: "lnum", "ss01";
    line-height: 1.45;
    padding: 48px 32px 96px;
    background-image:
      radial-gradient(ellipse at 20% 0%, rgba(180,140,60,0.08), transparent 50%),
      radial-gradient(ellipse at 100% 100%, rgba(60,80,120,0.06), transparent 50%);
  }}
  .wrap {{ max-width: 1080px; margin: 0 auto; }}
  header {{
    border-bottom: 2px solid var(--rule);
    padding-bottom: 24px;
    margin-bottom: 32px;
    display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end; justify-content: space-between;
  }}
  .masthead {{ display: flex; flex-direction: column; }}
  .eyebrow {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px; letter-spacing: 0.18em; text-transform: uppercase;
    color: var(--ink); opacity: 0.65;
  }}
  h1 {{
    font-family: 'Fraunces', serif; font-weight: 800; font-style: italic;
    font-size: clamp(36px, 6vw, 64px); margin: 4px 0 0; letter-spacing: -0.02em;
    line-height: 1.0;
  }}
  h1 em {{ font-style: normal; font-weight: 400; color: #6b5a2e; }}
  .meta {{
    font-family: 'JetBrains Mono', monospace; font-size: 12px;
    text-align: right; line-height: 1.7;
  }}
  .meta b {{ font-weight: 600; }}
  .summary {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 0;
    border: 2px solid var(--rule); margin-bottom: 28px; background: var(--paper-dim);
  }}
  .summary > div {{
    padding: 18px 20px; border-right: 1px solid var(--rule);
  }}
  .summary > div:last-child {{ border-right: none; }}
  .summary .label {{
    font-family: 'JetBrains Mono', monospace; font-size: 10px;
    letter-spacing: 0.16em; text-transform: uppercase; opacity: 0.7;
  }}
  .summary .value {{
    font-family: 'Fraunces', serif; font-weight: 800; font-size: 40px; line-height: 1;
    margin-top: 6px;
  }}
  .summary .buy .value  {{ color: var(--buy); }}
  .summary .hold .value {{ color: var(--hold); }}
  .summary .sell .value {{ color: var(--sell); }}
  .bench {{
    font-family: 'JetBrains Mono', monospace; font-size: 12px;
    padding: 12px 14px; border: 1px dashed var(--rule); margin-bottom: 24px;
    background: rgba(255,255,255,0.35);
  }}
  .bench-line {{
    display: flex; flex-wrap: wrap; gap: 18px; align-items: center;
  }}
  .bench-label {{
    font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
    font-size: 10px; padding-right: 6px; border-right: 1px solid rgba(26,23,20,0.3);
  }}
  .bench-line b {{ font-weight: 600; opacity: 0.65; margin-right: 4px; }}
  .legend {{
    margin-top: 10px; padding-top: 10px;
    border-top: 1px dotted rgba(26,23,20,0.25);
    font-size: 11px; opacity: 0.85; display: flex; flex-wrap: wrap; gap: 4px;
    align-items: center;
  }}
  .swatch {{
    display: inline-block; width: 10px; height: 10px;
    vertical-align: middle; margin-right: 4px; border-radius: 2px;
  }}
  .swatch.win  {{ background: var(--buy); }}
  .swatch.loss {{ background: var(--sell); opacity: 0.85; }}
  .swatch.na   {{ background: var(--err); opacity: 0.5; }}
  table {{
    width: 100%; border-collapse: collapse;
    font-family: 'JetBrains Mono', monospace; font-size: 13px;
  }}
  thead th {{
    text-align: left; font-weight: 600; padding: 12px 10px;
    border-bottom: 2px solid var(--rule);
    font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase;
  }}
  thead th.num {{ text-align: right; }}
  tbody td {{
    padding: 11px 10px; border-bottom: 1px solid rgba(26,23,20,0.15);
    vertical-align: middle;
  }}
  tbody tr:hover {{ background: rgba(26,23,20,0.04); }}
  td.sym {{
    font-family: 'Fraunces', serif; font-weight: 600; font-size: 17px;
    letter-spacing: 0.01em;
  }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.num.win  {{ color: var(--buy); }}
  td.num.loss {{ color: var(--sell); opacity: 0.85; }}
  td.num.na   {{ color: var(--err); opacity: 0.55; }}
  td.note {{ font-size: 11px; opacity: 0.7; }}
  .tag {{
    display: inline-block;
    font-family: 'JetBrains Mono', monospace; font-weight: 600; font-size: 11px;
    letter-spacing: 0.14em; padding: 5px 10px;
    border: 1.5px solid currentColor;
  }}
  .tag.buy   {{ color: var(--buy); background: rgba(31,107,58,0.08); }}
  .tag.hold  {{ color: var(--hold); background: rgba(184,134,11,0.1); }}
  .tag.sell  {{ color: var(--sell); background: rgba(163,32,32,0.08); }}
  .tag.error {{ color: var(--err); background: rgba(0,0,0,0.04); }}
  footer {{
    margin-top: 40px; font-family: 'JetBrains Mono', monospace; font-size: 11px;
    opacity: 0.55; border-top: 1px solid var(--rule); padding-top: 16px;
  }}
  @media (max-width: 640px) {{
    .summary {{ grid-template-columns: repeat(2, 1fr); }}
    .summary > div:nth-child(2) {{ border-right: none; }}
    .summary > div:nth-child(1), .summary > div:nth-child(2) {{ border-bottom: 1px solid var(--rule); }}
    .meta {{ text-align: left; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="masthead">
      <div class="eyebrow">Daily Signal &mdash; Portfolio Analysis</div>
      <h1>Buy. Hold. <em>Sell.</em></h1>
    </div>
    <div class="meta">
      Generated <b>{generated}</b><br>
      Benchmark: S&amp;P 500 (^GSPC)<br>
      Total-return methodology
    </div>
  </header>

  <section class="summary">
    <div class="buy"><div class="label">Buy</div><div class="value">{buys}</div></div>
    <div class="hold"><div class="label">Hold</div><div class="value">{holds}</div></div>
    <div class="sell"><div class="label">Sell</div><div class="value">{sells}</div></div>
    <div><div class="label">Errors</div><div class="value">{errors}</div></div>
  </section>

  <div class="bench">{bench_row}</div>

  <table>
    <thead>
      <tr>
        <th>Symbol</th>
        <th class="num">1-Year</th>
        <th class="num">3-Year</th>
        <th class="num">5-Year</th>
        <th>Score</th>
        <th>Call</th>
      </tr>
    </thead>
    <tbody>
{rows_html}
    </tbody>
  </table>

  <footer>
    Returns are total returns (dividends reinvested) from Yahoo Finance adjusted-close data.
    Stocks are compared to the S&amp;P 500 over the same period.
    This is a mechanical screen, not investment advice.
  </footer>
</div>
</body>
</html>
"""
    path.write_text(html)


def main() -> int:
    if not PORTFOLIO_CSV.exists():
        print(f"ERROR: {PORTFOLIO_CSV} not found in current directory.", file=sys.stderr)
        return 1

    symbols = load_symbols(PORTFOLIO_CSV)
    print(f"Loaded {len(symbols)} symbols from {PORTFOLIO_CSV}.")

    print("Fetching benchmark (S&P 500)...")
    bench_df = fetch_price_history(BENCHMARK)
    bench_returns = compute_returns(bench_df)
    print(f"  S&P 500  1yr={fmt_pct(bench_returns[1])}  "
          f"3yr={fmt_pct(bench_returns[3])}  5yr={fmt_pct(bench_returns[5])}")

    results: list[StockResult] = []
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {sym} ...", end=" ", flush=True)
        r = analyze_stock(sym, bench_returns)
        print(f"{r.recommendation} ({r.note})")
        results.append(r)

    write_csv(results, bench_returns, OUTPUT_CSV)
    write_html(results, bench_returns, OUTPUT_HTML)
    print(f"\nWrote {OUTPUT_CSV} and {OUTPUT_HTML}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
