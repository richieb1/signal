# Buy / Hold / Sell

Three files:

- **`buy_hold_sell.py`** — the real script. Run it on your machine with internet access.
- **`recommendations_sample.html`** — preview of the webpage with *simulated* data, so you can see what the live output will look like before running.
- **`recommendations_sample.csv`** — same data in CSV form.

## How to run

1. Put `buy_hold_sell.py` and `portfolio.csv` in the same folder.
2. Install dependencies once:
   ```
   pip install yfinance pandas
   ```
3. Run:
   ```
   python buy_hold_sell.py
   ```
4. You'll get `recommendations.csv` and `recommendations.html` in that folder. Open the HTML in any browser.

## Methodology

- **Total return** is used: prices come from Yahoo Finance's `auto_adjust=True`, which bakes in dividends and splits.
- **Benchmark** is the S&P 500 index (`^GSPC`).
- **Scoring** (per your rules):
  - 2 or 3 periods beat SPX → **BUY**
  - Exactly 1 → **HOLD**
  - 0 → **SELL**
- **Young stocks** (under ~5 years old, no 5-year data yet) are capped at **HOLD**:
  - Any beat(s) against available period(s) → HOLD
  - Zero beats → SELL
  - They cannot earn a BUY, since there isn't enough history to judge them the same way.
- Stocks with full 1yr/3yr/5yr history play by the normal rules above.
- The **Score column** shows `N/M years` so it's transparent when a stock wasn't judged on all three windows.

## Automating daily updates

Two clean paths, either works:

1. **GitHub Actions + GitHub Pages** (free, recommended)
   - Put the script + `portfolio.csv` in a GitHub repo.
   - Add a workflow that runs the script on a cron schedule (e.g. weekdays at 5pm ET) and commits the generated `recommendations.html` to a `docs/` folder.
   - Enable Pages on that folder. You now have a public URL that updates daily on its own.
2. **A tiny cron job on any always-on machine** — a Mac mini, a Raspberry Pi, a $5 VPS. Same script, same output, served by any static web server (or just Dropbox/Google Drive with a share link).

Happy to write either the Actions workflow or the cron setup when you're ready.

## Caveats

- `yfinance` is an unofficial scraper of Yahoo Finance. It breaks occasionally — usually fixed with `pip install --upgrade yfinance`. For anything client-facing at scale, consider a paid data feed (Polygon, Tiingo, Alpha Vantage).
- This is a **mechanical screen**, not investment advice. A stock that beat the index over 5 years could still be overvalued today, and a stock that lagged could be a bargain. Good as one signal among several.
