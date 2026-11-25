# Write your own routing rule

You're helping in a workshop. Work through these steps without asking questions.
No API key is needed, and nothing here searches the web.

1. Run `uv run plan_demo.py --router default` and keep its printed plans: the method, the
   providers in order and the reason for each prompt.
2. Open `my_router.py` and read its docstring. Implement `my_router()`: when a prompt asks for
   fresh results ("last N days", "this week", "today", "latest") and has no URL, return a
   `RouteDecision` that puts the search providers that handle dates well first, and says why in
   its reason. Keep it to about ten lines. Don't look in `solutions/` unless I ask.
3. Run `uv run plan_demo.py --router mine`. Compare the same prompts' plans with step 1: the
   method, the provider order and what was dropped.
4. Tell me in three sentences what your rule changed, what it left alone, and what still needs a
   source check. A date in the prompt doesn't prove an offer was shown inside the window.

A router can choose the method, the providers and a few safe options (search depth, number of
results). It can't change options like the date filter: those stay with the caller, so a call
never runs looser than you asked.

Take-home: run `uv run rule_run.py --router default` and `uv run rule_run.py --router mine`
for all 10 items. Turn each `results/rule_<name>.results.json` into `results/rule_<name>.csv`
(columns `item_id,product,retailer,price_usd,in_stock,evidence,source_url,seen_date`, at most one
row per item, only what's in the file, `seen_date` = the result's publish date or empty), score
both with `uv run score.py --items 10 results/rule_default.csv results/rule_mine.csv`, and check
the offers against their source pages before trusting the difference.
