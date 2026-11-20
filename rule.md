# Write your own routing rule

You're helping in a workshop. Work through these steps without asking questions.

1. Run `uv run rule_run.py --router default` and keep its score. That's the
   open source WebRouter's built-in rules on the 30 companies.
2. Open `my_router.py` and read its docstring. Implement `my_router()`: when a prompt asks
   for fresh results ("last N days", "this month", "latest") and has no URL, return a
   `RouteDecision` that sends the search to providers that handle dates well, first.
   Use what `uv run providers.py Figma` shows about which free providers return dated
   results. Keep it to about ten lines. Don't look in `solutions/` unless I ask.
3. Run `uv run rule_run.py --router mine` and compare its score with step 1:
   launches found, stale results and cost.
4. Try one more idea of your own (a different provider order, a rule for another kind of
   prompt) and rerun. Keep whichever scores better.
5. Print the leaderboard line for your best run:
   `uv run score.py results/rule_mine.csv --line`
   and tell me to post it in the workshop channel.

A router can choose the method, the providers and a few safe options (search depth,
number of results). It can't change options like the date filter: those stay with the
caller, so a call never runs looser than you asked. If your rule tries, the plan says so.

No API key is needed. If `ANTHROPIC_API_KEY` is set, `rule_run.py` also uses Claude to turn
search results into cleaner launch records.
