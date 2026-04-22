# Portfolio Signal — Streamlit Web App

A self-serve web app wrapper around `buy_hold_sell.py`. Users upload a portfolio CSV, the app fetches live total-return data from Yahoo Finance, and shows Buy/Hold/Sell recommendations against the S&P 500.

## Files

- `app.py` — Streamlit web app (the front door)
- `buy_hold_sell.py` — the analysis logic (imported by app.py)
- `requirements.txt` — Python dependencies
- `portfolio.csv` — **do NOT include this in the deployed repo**; users upload their own

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

A browser tab opens at `http://localhost:8501`.

## Deploy to Streamlit Community Cloud (free)

1. **Create a GitHub repo** with these files at the top level:
   - `app.py`
   - `buy_hold_sell.py`
   - `requirements.txt`
   - `README.md` (this file, optional)

   Do **not** commit `portfolio.csv` — the app takes uploads from the user, so your dad's data stays on his machine.

2. Go to **https://share.streamlit.io** and sign in with your GitHub account.

3. Click **"Create app"** → **"Deploy a public app from GitHub"**.

4. Point it at your repo, branch `main`, main file path `app.py`.

5. Click **Deploy**. First build takes ~2 minutes. You get a URL like `https://your-app-name.streamlit.app`.

6. Share that URL with your dad. He uploads his CSV, sees results, downloads the CSV or HTML report if he wants.

## Notes

- **Cold starts:** Free-tier apps sleep after ~7 days of inactivity. First visit after a nap takes ~30 seconds to spin back up. Subsequent visits are instant.
- **Public URL:** Anyone with the link can use the app. They'd have to upload their own portfolio CSV — nothing private is exposed — but if you want to lock it down later, Streamlit supports password protection via `secrets.toml` or you can migrate to a Flask app with auth.
- **Updating the app:** Edit the code, push to GitHub, Streamlit Cloud auto-redeploys within a minute.
- **Data freshness:** Every upload triggers a fresh pull from Yahoo Finance. No caching of results between sessions.
