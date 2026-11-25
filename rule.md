# Write your own routing rule

1. Run `uv run plan_demo.py --router default` and save its printed plan.
2. Open `my_router.py`. For fresh-result prompts without a URL, change the preferred
   search-provider order and explain the reason in the returned decision.
3. Run `uv run plan_demo.py --router mine`. Compare the same prompts' methods,
   provider order and exclusions with the default plan. No web requests run.
4. Explain what your rule changed and what still requires a source check. A date in
   a prompt does not establish that an announcement falls inside the window.

Optional take-home: run `uv run rule_run.py --router default --limit 5` and
`uv run rule_run.py --router mine --limit 5`. Each saves a new result directory.
Pass the printed CSV paths to `compare.py`, then validate the records against sources.
Keep every run; do not select only the highest draft-key overlap.

A router can choose the method, provider order and safe options such as search depth.
The caller retains control of date filters. Use the fixed window in `config.json`.
The no-key rule runner returns unverified search hits; with `ANTHROPIC_API_KEY` it
structures those hits using a model. Compare only runs using the same mode.
