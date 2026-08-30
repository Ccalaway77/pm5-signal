# pm5-signal

Paper-only 5-minute crypto Up/Down signal engine for Polymarket. A clean
fork/rebuild — this repo has no connection to any other project and never
touches another repo's files.

**Paper trading only. No real orders, no wallet keys, no live money — ever,
until you deliberately decide otherwise and change the code yourself.**

## What's here

```
src/
  market_adapter.py   config-driven market definitions (BTC on, ETH/SOL scaffolded off)
  db.py               SQLite storage — durable, not GitHub Actions cache
  engine.py           baseline heuristic signal + blend with the learner
  risk.py             position sizing + "don't chase price" guardrails
  online_learner.py   incremental model, updates after every settled trade
  spot.py             exchange spot price (Coinbase/Kraken/Bybit fallback)
  poly.py             Polymarket Gamma/CLOB access
  settle.py           resolves due windows, pays out, labels training data
  board.py            writes status.json / stats.json
  harvest.py          orchestrates one full tick — the entrypoint
tests/test_core.py    unit tests for everything that doesn't need network
markets.yaml          which 5-minute markets are tracked
config.yaml           every tunable number, in one place
dashboard.html        the live board (copied to docs/index.html by the workflow)
.github/workflows/harvest.yml   runs harvest.py every 5 minutes
```

I tested everything that doesn't require live network access (all of
`db.py`, `risk.py`, `engine.py`, `online_learner.py`, `market_adapter.py`,
plus a full synthetic 35-tick run through settle → learn → board) — 8 unit
tests plus the end-to-end run all pass. **`spot.py` and `poly.py` make real
network calls to Coinbase/Kraken/Bybit and Polymarket's Gamma/CLOB APIs,
which I cannot test from this sandbox — those are the two files most likely
to need a small fix after your first real run.**

## What you need to do

### 1. Create the repo
- New, empty GitHub repo (e.g. `pm5-signal`). Do not fork or branch from
  any existing repo — this should have zero shared history with anything
  else.
- Add every file above to it. Easiest on a laptop:
  ```
  git init
  git add .
  git commit -m "initial scaffold"
  git branch -M main
  git remote add origin https://github.com/<you>/pm5-signal.git
  git push -u origin main
  ```
  (No laptop needed either — you can create each file directly through the
  GitHub web UI's "Add file" button if that's easier from the Fold.)

### 2. Repo settings
- **Settings → Actions → General → Workflow permissions** → set to
  **"Read and write permissions."** Required for the workflow to push the
  `data` branch and `docs/` commits.
- **Settings → Pages → Source** → Deploy from branch → `main` → `/docs`
  folder. (The `docs/` folder won't exist until the first workflow run
  creates it — that's fine, come back and set this after step 4.)

### 3. Set up the redundant clock (optional but recommended)
GitHub's own `schedule:` trigger can lag several minutes under load. To
supplement it:
- Create a fine-grained Personal Access Token scoped to **only this repo**,
  with **Actions: Read and write** permission.
- Register a free job at cron-job.org that fires every 5 minutes:
  - `POST https://api.github.com/repos/<you>/pm5-signal/actions/workflows/harvest.yml/dispatches`
  - Header: `Authorization: Bearer <your PAT>`
  - Body: `{"ref":"main"}`
- Never paste that PAT anywhere else, including into a chat with me.

### 4. First run
- Go to the **Actions** tab → `harvest` workflow → **Run workflow** (manual
  dispatch) to trigger it once by hand.
- Watch it go green. If it goes red, open the log — it will almost
  certainly fail in `spot.py` or `poly.py` first, since those are the only
  network calls I couldn't verify from here.
- **If it fails:** copy the error text (and, if you can, the raw JSON from
  hitting the failing URL directly in a browser) and paste it back to me —
  these are simple GET-request field-name mismatches, not architectural
  problems, and are quick to fix once I can see a real response.

### 5. Confirm it's live
- `https://<you>.github.io/pm5-signal/` should show the dashboard.
- `https://<you>.github.io/pm5-signal/status.json` should show live data.
- The pulse badge top-right should read **LIVE** and visibly beat. It reads
  **STALE** automatically if no run has succeeded in the last 12 minutes —
  that alone will tell you if the cron/Actions clock ever stops without
  you needing to check the Actions tab.

### 6. Before enabling ETH or SOL
- Confirm Polymarket actually lists a 5-minute Up/Down market for that
  asset, and confirm the real Gamma slug format — `markets.yaml` currently
  guesses `eth-updown-5m-{unix}` / `sol-updown-5m-{unix}` by mirroring the
  BTC pattern, which is unverified.
- Flip one market on at a time, watch a few harvests go green, then
  consider the next.

### 7. Reassessment gate (don't skip this)
Per market, wait for **~30 labeled feature rows and ~50 settled trades**
before reading the hit rate or PnL as meaning anything. Below that, you're
looking at noise, not edge — `dashboard.html` shows a banner reminding you
of this automatically while the sample is small.

## Guardrails baked in

- Paper only — nothing in this codebase can place a live order or touch a
  wallet key.
- Fees and slippage are deducted before PnL is shown, and the ask-price
  cutoff refuses to chase expensive fills — same "honest fills" discipline
  as the project this was inspired by.
- One market's API failure (a `try/except` around each market in
  `harvest.py`) can't take down another market's data collection.
- The online learner logs a prequential accuracy series to
  `data/metrics.jsonl` on every update, so "the model is improving" is
  something you can chart, not just assert.
