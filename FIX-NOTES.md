# FIX NOTES — token-by-side + conf cap (2026-09-06)

Approved by Cory via Hank. Paper only. **Did not wipe data/ or reset learner.**

## FIX 1 — Token-by-side
**File:** src/harvest.py
- Added 	oken_id_for_side(market_dict, side) — maps UP/DOWN via Gamma outcomes + clobTokenIds (handles JSON-string or list).
- Harvest tick uses it before get_best_ask; **refuses trade** if unmapped.
- Kept _extract_first_token_id as thin deprecated helper for old tests.

**Tests:** 	est_token_id_for_side_maps_up_and_down, 	est_token_id_for_side_refuses_unmapped

## FIX 2 — Cap / soft-blend learner confidence
**Files:** src/engine.py, config.yaml
- Trusted path soft-blends learner P(up) with heuristic (learner_blend_weight: 0.7).
- Caps confidence at learner_conf_cap: 0.85 so ~1.0 SGD cannot always max stake.

**Tests:** updated 	est_engine_trusts_learner_when_available; added 	est_engine_caps_extreme_learner_confidence

## Files changed (for GitHub Desktop)
1. src/harvest.py
2. src/engine.py
3. config.yaml
4. 	ests/test_core.py
5. FIX-NOTES.md (this file)


## Cory — GitHub Desktop
Local checkout was behind origin. **Pull first, then push** these changes (resolve any trivial conflicts favoring this FIX if needed). Do **not** wipe data/ or the data branch / learner.

## Verify
1. Local: python -m pytest tests/test_core.py -q → 21 passed
2. Cory: commit + push these files via GitHub Desktop (do **not** force-reset data branch)
3. Next green harvest log: Down trades should ask Down token; conf should not print as 1.000 every tick
4. Board/Actions stay RUNNING; n_seen must not drop

## Not done
- No ETH/SOL enable
- No learner reset
- No harvest.yml change
