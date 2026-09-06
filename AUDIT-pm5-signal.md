# AUDIT - pm5-signal

**Lead:** Sig  
**Date:** 2026-09-06 (PT)  
**Phase:** audit-before-long-data (#4)  
**Status at audit:** harvest RUNNING; learner trusted; **do not wipe data/**

Verified live (not invented):
- Board status.json @ 2026-09-06T17:00:29Z -- settle_count **672**, open **1**, hit_rate **~52.2%**, bankroll **~$4988**, pnl **~$3988**, labeled_feat **799**
- Actions: harvest green on ~5m workflow_dispatch (latest 17:05Z)
- data branch: pm5.db, model_btc.json, metrics.jsonl, status/stats
- model_btc.json: **n_seen=162**, trusted (min 30), prequential_acc **~0.59**
- Harvest log: learner_trusted=True, sample trade placed

---

## 1. What it is

Paper-only Polymarket BTC 5-minute Up/Down signal engine. Each harvest tick settles due windows, builds features from exchange spot/klines (not Polymarket price), blends a placeholder heuristic with an online SGD learner, paper-fills if risk allows, and publishes a GitHub Pages board. Fake money only -- no wallet, no live orders.

## 2. How it actually runs

| Piece | Detail |
|--------|--------|
| Clock | .github/workflows/harvest.yml -- schedule */5 plus external cron via workflow_dispatch (redundant; concurrency group harvest) |
| Entrypoint | python src/harvest.py on ubuntu-latest |
| Persistence | Restore whole data/ from data branch, run, commit whole data/ back (git add -f data/), copy dashboard + status/stats to docs/ on main |
| Board | https://ccalaway77.github.io/pm5-signal/ (Pages from main /docs) |
| Ports / local daemon | None -- Actions-only; Desktop folder is the git checkout, not a running server |
| Paper-only | README + code path: only SQLite paper trades via db.insert_trade; no order/sign/wallet APIs |
| Zip / pushes | Hank applies zip locally; Cory pushes via GitHub Desktop (unchanged) |

**Keep RUNNING.** Local Desktop data/ was empty at audit time -- live state lives on the data branch / Pages, not necessarily in the laptop working tree.

## 3. Architecture map

cron/dispatch -> harvest.yml
  -> restore data/ (pm5.db, model_*.json, metrics.jsonl)
  -> harvest.py
       settle.py  -> resolve windows (start_spot vs end_spot) -> settle trades -> learner.observe
       spot.py    -> Coinbase/Kraken/Bybit spot + klines
       engine.py  -> features + heuristic + blend(learner)
       poly.py    -> Gamma market + CLOB best ask
       risk.py    -> ask cutoff, slippage, stake %, fee
       db.py      -> SQLite windows/trades/feat_rows; bankroll = starting + SUM(settled pnl)
       board.py   -> data/status.json + stats.json
  -> publish docs/ + push data branch

| Module | Role |
|--------|------|
| market_adapter.py | markets.yaml -> enabled markets (BTC on; ETH/SOL off) |
| online_learner.py | SGDClassifier + StandardScaler; prequential log; trusted at n_seen >= 30 |
| dashboard.html | LIVE/STALE badge; small-sample banner |

## 4. What is working

- Harvest succeeding on a steady ~5m cadence (verified Actions list).
- Persist fix is real: restore shows growing metrics.jsonl + model_btc.json; log shows learner_trusted=True (n_seen climbing, not cold-start forever).
- Bankroll derived from settled PnL (avoids old double-charge bug documented in db.py).
- Honest-fill intent: fees, slippage tick, ask cutoffs, one trade per slug, late-window cutoff.
- Features from spot only (engine docstring) -- Polymarket price used for sizing/fill gate, not as a model input.
- Board + Actions agree on moving settle_count / fresh updated timestamps.
- Unit tests exist for offline pieces (tests/test_core.py).

## 5. What is rough / patched / risky

1. **CRITICAL -- token side mismatch (verified):** Gamma outcomes are ["Up","Down"] with two clobTokenIds. harvest.py always takes clobTokenIds[0] (Up) for get_best_ask, then records whatever signal side is. **Down signals are priced off the Up book.** PnL and edge for Down trades are not honest until this is fixed. Live probe 2026-09-06 confirmed Up/Down token pair order.
2. **Learner hard-overrides heuristic** once trusted (engine.blend) -- live conf can hit ~1.0, which maxes stake pct and raises ask cutoff to 0.80. Overconfident SGD.
3. **Heuristic is explicitly unvalidated** placeholder momentum (engine.py) -- early win rates are not edge.
4. **ETH/SOL** scaffolded with guessed slugs; still enabled: false (good -- do not flip without Gamma proof).
5. **Desktop checkout lag:** local docs/status.json was hours behind Pages at audit -- do not treat Desktop JSON as live without pull/Pages fetch.
6. **metrics.jsonl append-only** across the pre-persist era -> long file vs n_seen=162 in model; use model_btc.json as source of truth for learner state.
7. **poly.py / ask book sort** still carries author verify-against-live notes; current code takes min(ask price) which is usually fine but worth a spot-check.
8. Fabrication risk: never claim signal/PnL without board or Actions proof (crew card).

## 6. Data quality

| Signal | Read |
|--------|------|
| Sample size | Well past reassessment gate (50 settled / 30 labeled) -- 672 settled, 799 labeled_feat |
| Hit rate ~52% | Barely above coin-flip after fees; not clear edge |
| Prequential ~59% | Better than trade hit rate, but short trusted history (162 observes) and prior wipe era |
| Labels | Outcome = end_spot vs start_spot at settle tick -- approximate; depends on spot feed continuity |
| Training rows | One feat row / observe per settled slug -- not every harvest tick trains |
| Junk risk | High until token-side bug fixed -- Down fills poison both PnL stats and any future calibration |
| Persist | Post-fix learner is real; **do not force-reset** |

## 7. Top 5 improvements (quick to deep)

1. **Quick / critical:** Select CLOB token by signal side (index 0=Up, 1=Down per Gamma outcomes); refuse trade if side/token cannot be mapped.
2. **Quick:** Soft-blend or cap learner confidence (e.g. clip conf, or mix heuristic+learner) so conf~1.0 does not always max stake.
3. **Quick:** Ops note: treat Pages status.json + data branch as live; optional board note when Desktop checkout is stale.
4. **Medium:** Chart/trim metrics.jsonl (or rotate) and surface prequential series on the board for honest is-it-learning reads.
5. **Deep:** Replace placeholder heuristic + raw SGD with a designed feature set / proper online model eval -- only after fills are honest.

## 8. Recommended next 1-2 changes only

1. **Patch token-by-side in harvest.py (+ tiny test)** -- highest integrity fix; keep harvest RUNNING; no data/ wipe.
2. **Cap learner confidence or blend** so trusted mode cannot mint 0.999 conf / max stakes every tick.

Do **not** enable ETH/SOL, reset the learner, or rewrite the pipeline in this phase.

## 9. Lane used

- **Primary:** Sig verified files (Desktop src/, harvest.yml, configs), GitHub Actions logs (gh on laptop), live Pages status.json/stats.json, data branch artifacts (model_btc.json, metrics tail), live Gamma slug probe for token order.
- **OpenRouter Think/Code:** crew script not found under Desktop / Projects / Documents (depth-limited search) -- skipped rather than invent a run.
- **Arena:** not used (no draft for Cory).
- **Claude critique:** not yet (audit written first per playbook).

---

Report path: Desktop\pm5-signal\AUDIT-pm5-signal.md -- TLDR to Hank separately -- Paper money only