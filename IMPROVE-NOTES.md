# IMPROVE — edge gate + regularized v2 learner (2026-09-07)

Paper only. **Did not wipe data/ or model_btc.json.**

## Why
The Sep-6 peak was 62% luck on cheap Down fills + 3% tickets on a swollen
book. Lifetime hit rate is ~50%. The v1 SGD book has intercept ~-21 and
prequential ~51%. Buying 0.50–0.70 asks at that hit rate is how PnL walked
from ~$4.8k toward the original $1k.

## What changed
1. **Value gate** (`risk.ev_per_stake` / `min_ev_per_stake: 0.05`)
   Skip unless P(side) beats fill + fee by 5% of stake. Ask is a price
   check, not a model input.
2. **Smaller tickets** — max stake 1.2% (was 3%), ask cap 0.58 (was 0.70/0.80).
3. **v2 learner** — `data/model_btc_v2.json` trains in parallel with L2
   `alpha=0.01`, feature clip, P(up) clip. Harvest uses v2 once trusted
   (≥30 rows). v1 is kept and still updated; not deleted.
4. **Softer v1 blend** while v2 is cold (`learner_blend_weight: 0.55`).

## Not done
- No ETH/SOL
- No data wipe / no learner reset of v1
- Features still the same four spot stats

## Verify
- Next harvest log: learner=v1 then v2; skip when EV fails
- data/model_btc_v2.json appears on the data branch after a few settles
