"""
Streamlit web app for the Buy/Hold/Sell analyzer.

Run locally:
    streamlit run app.py

Deploy to Streamlit Community Cloud:
    1. Push this folder (app.py, buy_hold_sell.py, requirements.txt) to a public GitHub repo.
    2. Go to https://share.streamlit.io, sign in with GitHub, click "New app",
       point it at the repo, and set the main file to app.py.
    3. Done. You'll get a public URL to share.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# Import the real analysis logic from buy_hold_sell.py (same folder).
import buy_hold_sell as bhs


st.set_page_config(
    page_title="Portfolio Signal",
    page_icon="📈",
    layout="wide",
)

# Ask search engines not to index this app. Respected by Google, Bing, etc.
# Not enforceable against bad actors, but handles the 99% case.
st.markdown(
    '<meta name="robots" content="noindex, nofollow">',
    unsafe_allow_html=True,
)

# ---------- Header ----------
st.title("Portfolio Signal")
st.caption(
    "Upload a portfolio CSV with a **Symbol** column. "
    "We'll fetch total-return data from Yahoo Finance, compare each stock's "
    "1yr / 3yr / 5yr performance to the S&P 500, and label each as Buy, Hold, or Sell."
)

with st.expander("How the scoring works"):
    st.markdown("""
    For each stock we compute total return (dividends reinvested) over 1, 3, and 5 years
    and compare each figure to the S&P 500 over the same window.

    - **Full history (1yr + 3yr + 5yr available):** 2–3 beats = **BUY**, 1 beat = **HOLD**, 0 beats = **SELL**
    - **Young stocks (no 5-year history yet):** Any beat = **HOLD**, 0 beats = **SELL**. They cannot earn a BUY yet.
    - The *Score* column shows how many periods we could actually judge (e.g. `2/3 years`, `1/1 years`).

    This is a mechanical screen, not investment advice.
    """)

st.divider()

# ---------- Upload ----------
uploaded = st.file_uploader(
    "Upload portfolio.csv",
    type=["csv"],
    help="Must include a 'Symbol' column. Other columns are ignored.",
)

if uploaded is None:
    st.info("Waiting for a CSV upload to begin.")
    st.stop()

# ---------- Parse upload ----------
try:
    df = pd.read_csv(uploaded)
except Exception as e:
    st.error(f"Could not read that CSV. Error: {e}")
    st.stop()

if "Symbol" not in df.columns:
    st.error(
        "That CSV doesn't have a column named 'Symbol'. "
        f"I found these columns instead: {list(df.columns)}"
    )
    st.stop()

symbols = [s.strip() for s in df["Symbol"].dropna().astype(str) if s.strip()]
symbols = list(dict.fromkeys(symbols))  # dedupe, preserve order

if not symbols:
    st.error("No valid symbols found in the Symbol column.")
    st.stop()

st.success(f"Found **{len(symbols)}** symbols. Starting analysis…")

# ---------- Run analysis ----------
progress = st.progress(0.0, text="Fetching S&P 500 benchmark…")
status = st.empty()

try:
    bench_df = bhs.fetch_price_history(bhs.BENCHMARK)
    bench_returns = bhs.compute_returns(bench_df)
except Exception as e:
    st.error(f"Failed to fetch S&P 500 benchmark data: {e}")
    st.stop()

status.write(
    f"**S&P 500:** 1yr {bhs.fmt_pct(bench_returns[1])} · "
    f"3yr {bhs.fmt_pct(bench_returns[3])} · "
    f"5yr {bhs.fmt_pct(bench_returns[5])}"
)

results: list[bhs.StockResult] = []
for i, sym in enumerate(symbols, 1):
    progress.progress(i / len(symbols), text=f"Analyzing {sym} ({i}/{len(symbols)})…")
    results.append(bhs.analyze_stock(sym, bench_returns))

progress.empty()
status.empty()

# ---------- Summary metrics ----------
buys  = sum(1 for r in results if r.recommendation == "BUY")
holds = sum(1 for r in results if r.recommendation == "HOLD")
sells = sum(1 for r in results if r.recommendation == "SELL")
errors = sum(1 for r in results if r.recommendation == "ERROR")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Buy", buys)
col2.metric("Hold", holds)
col3.metric("Sell", sells)
col4.metric("Errors", errors)

# ---------- Write outputs to buffers so we can offer downloads ----------
# Reuse the real writers — they expect Path objects, so we write to a temp dir
# and then read back the bytes for the download buttons.
import tempfile
with tempfile.TemporaryDirectory() as tmpdir:
    csv_path = Path(tmpdir) / "recommendations.csv"
    html_path = Path(tmpdir) / "recommendations.html"
    bhs.write_csv(results, bench_returns, csv_path)
    bhs.write_html(results, bench_returns, html_path)
    csv_bytes = csv_path.read_bytes()
    html_bytes = html_path.read_bytes()

# ---------- Download buttons ----------
d1, d2 = st.columns(2)
today = datetime.now().strftime("%Y-%m-%d")
d1.download_button(
    "Download CSV",
    data=csv_bytes,
    file_name=f"recommendations-{today}.csv",
    mime="text/csv",
    use_container_width=True,
)
d2.download_button(
    "Download HTML report",
    data=html_bytes,
    file_name=f"recommendations-{today}.html",
    mime="text/html",
    use_container_width=True,
)

st.divider()

# ---------- Results table ----------
# Build a clean dataframe for on-page display.
# Sort: group (BUY/HOLD/SELL/ERROR) first, then avg margin vs S&P descending,
# so the strongest performers rise to the top of each group. Ties on symbol.
order = {"BUY": 0, "HOLD": 1, "SELL": 2, "ERROR": 3}
sorted_results = sorted(
    results,
    key=lambda r: (order.get(r.recommendation, 9), -bhs.sort_score(r, bench_returns), r.symbol),
)

table_rows = []
for r in sorted_results:
    table_rows.append({
        "Symbol": r.symbol,
        "Call": r.recommendation,
        "Score": r.note,
        "1-Year": bhs.fmt_pct(r.returns[1]),
        "3-Year": bhs.fmt_pct(r.returns[3]),
        "5-Year": bhs.fmt_pct(r.returns[5]),
        "Beat 1yr": "" if r.beats[1] is None else ("✓" if r.beats[1] else "✗"),
        "Beat 3yr": "" if r.beats[3] is None else ("✓" if r.beats[3] else "✗"),
        "Beat 5yr": "" if r.beats[5] is None else ("✓" if r.beats[5] else "✗"),
    })

display_df = pd.DataFrame(table_rows)


def highlight_call(val: str):
    colors = {
        "BUY":   "background-color: #d6efdc; color: #0d4a1f; font-weight: 600;",
        "HOLD":  "background-color: #fbeacc; color: #7a5806; font-weight: 600;",
        "SELL":  "background-color: #f4cccc; color: #6e1111; font-weight: 600;",
        "ERROR": "background-color: #e6e6e6; color: #333; font-weight: 600;",
    }
    return colors.get(val, "")


def highlight_beat(val: str):
    if val == "✓":
        return "color: #1f6b3a; font-weight: 700;"
    if val == "✗":
        return "color: #a32020;"
    return "color: #888;"


styled = (
    display_df.style
    .map(highlight_call, subset=["Call"])
    .map(highlight_beat, subset=["Beat 1yr", "Beat 3yr", "Beat 5yr"])
)

st.dataframe(styled, use_container_width=True, hide_index=True)

st.caption(
    f"Generated {datetime.now().strftime('%B %d, %Y at %I:%M %p')} · "
    "Total-return methodology · Data from Yahoo Finance"
)
