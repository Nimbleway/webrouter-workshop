# Write your own routing rule

You're helping in a workshop. Work through these steps without asking questions.
No API key is needed.

1. Run `uv run rule_run.py --router default`. It searches the 30 companies through the
   open source WebRouter's built-in rules and saves what came back to
   `results/rule_default.results.json`, with a call log and timing.
2. Read that file and write `results/rule_default.csv` with columns
   `company,announcement,event_date,evidence,source_url`: one row per real product launch
   the company announced inside the window in `config.json`. Use only what's in the file;
   don't search. Skip results that aren't launches. Leave `event_date` empty if the result
   has no date. Then run `uv run score.py results/rule_default.csv` and keep the score.
3. Open `my_router.py` and read its docstring. Implement `my_router()`: when a prompt asks
   for fresh results ("last N days", "this month", "latest") and has no URL, return a
   `RouteDecision` that sends the search to providers that handle dates well, first.
   Use what `uv run providers.py Figma` shows about which free providers return dated
   results. Keep it to about ten lines. Don't look in `solutions/` unless I ask.
4. Run `uv run rule_run.py --router mine`, turn `results/rule_mine.results.json` into
   `results/rule_mine.csv` the same way as step 2, and run `uv run score.py results/rule_mine.csv`.
   Compare with step 2: launches found, stale results and estimated cost.
5. Try one more idea of your own (a different provider order, a rule for another kind of
   prompt) and repeat step 4. Keep whichever scores better.
6. Print the leaderboard line for your best run:
   `uv run score.py results/rule_mine.csv --line`
   and tell me to post it in the workshop channel.

A router can choose the method, the providers and a few safe options (search depth,
number of results). It can't change options like the date filter: those stay with the
caller, so a call never runs looser than you asked.
