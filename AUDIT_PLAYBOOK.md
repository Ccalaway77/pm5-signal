# Project audit playbook (leads + free crews)

Phase: **audit → improve → then gather data** (rough baselines first).
Reports to: Moe 📱 + Hank 🏠. Soft routing. Prefer free lanes. Do **not** dump full audits through Grok chat.

## Goal
Each paper project is a patched baseline. Lead + crew produce an honest audit and a small improvement plan Cory can approve — not a silent full rewrite.

## Lanes (use these, not Grok for heavy lift)
1. **Think** — OpenRouter free (`openrouter_crew.py think` / MiniMax free) or DeepSeek app
2. **Code review / patch drafts** — OpenRouter free coder / Nemotron Lightning free; real file edits via Hank + laptop / Cursor cloud agent
3. **Heavy rethink** — Arena Agent (especially kalshi-arena / Cal)
4. **Sharp A-vs-B** — Arena Battle
5. **Critique** — Claude free, **one short pass** after a written audit exists
6. **Moe/Hank** — route, verify no fabrication, escalate decisions to Cory

## Deliverable (one markdown report per project)
Save as `AUDIT-<slug>.md` under the project folder on the laptop (Hank) and paste a short TLDR up to Moe/Hank.

Sections required:
1. **What it is** (1 paragraph)
2. **How it actually runs** (ports, start scripts, paper-only confirmation)
3. **Architecture map** (main modules / data flow — honest, from files not guesses)
4. **What’s working**
5. **What’s rough / patched / risky** (fabrication risks, halt flags, filter debt, hardcoded paths)
6. **Data quality** (are we learning from junk?)
7. **Top 5 improvements** ranked: quick win → deep rethink
8. **Recommended next 1–2 changes only** (no boiling the ocean)
9. **Lane used** (which free tools ran)

## Rules
- Paper money only. Never loosen Cal filters without Cory.
- Don’t “fix” Lars halt=True if it’s intentional WATCH/paper_bleed.
- If a model claims it ran code or placed trades, **verify** with logs/dashboard.
- Stagger deep Arena sessions; don’t run five Arena Agents at once.
- Keep Grok (Moe/Hank/leads chat) for coordination + verification, not 50-page analysis.

## Suggested order
1. Cal 🏟️ kalshi-arena (Arena Agent default)
2. Eddy 🏈 edge
3. Polly 📊 polymarket
4. Sig 📡 pm5-signal (has real learner data — careful)
5. Lars 🧪 pm5-lab (respect halt-by-design)
