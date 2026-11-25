# Same agent, now with a router

You're helping in a workshop. Work through these steps without asking questions.

1. Add the open source WebRouter (https://github.com/Nimbleway/webrouter) as an MCP server.
   Don't clone that repo; run it with uvx.
   - Claude Code: `claude mcp add web-router -- uvx --from "webrouter[mcp]==0.14.0" web-router-mcp`
   - Cursor: add to `.cursor/mcp.json`:
     `{"mcpServers": {"web-router": {"command": "uvx", "args": ["--from", "webrouter[mcp]==0.14.0", "web-router-mcp"]}}}`
   If the web-router tools aren't available to you yet, tell me to restart you and paste
   "Follow router.md" again, then stop.
2. Call web-router's `budget_start` with `max_cost_usd` 0.50 and `time_limit_s` 600.
3. Redo the kickoff task (same shopper, same first 5 wishlist items, same window) using **only
   web-router's tools** (`search`, `extract`), not your built-in web tools. Search and extract
   need no API keys. Keep the same limits as the baseline: at most 15 searches and 5 page reads
   per item, counting failed attempts. Read their option lists first and constrain before you
   search: for each item, `search` with `include_domains` set to a few retailers or the brand's
   own store, so the results are product pages whose text carries the price and stock. `extract`
   a product page only when the search text doesn't show its price or stock: a page costs far
   more tokens than a search result. Pass independent URLs to `extract` together, and work on
   several items at once.
   Keep the default `auto` provider for both search and extract, so the budget can admit
   priced backends and fall back when one fails. Don't force `provider="max"`: it races every
   extractor at once, and the budget can't cap that race in this version.
4. Log every web-router call to `results/router.calls.jsonl`, one JSON line each:
   `{"tool": "<search or extract>", "input": "<query or URLs>", "result_chars": <approximate length returned>, "cost_usd": <the cost the tool reported, or null>}`
   Log failed calls too. Keep a URL that failed to extract as failed, not as a page you read,
   and keep a cost the tool didn't report as `null`, not 0.
5. Write `results/router.csv` (same columns as `results/baseline.csv`) and
   `results/router.meta.json` (`started`, `finished`, `seconds`, `agent`), timing with
   `date -u +%FT%TZ`. Start the timer after setup and the budget call; stop it after writing the CSV.
6. Call `budget_status` and tell me what it reports.
7. Run `uv run score.py results/router.csv`, then `uv run compare.py`, and show me both tables.
   Then tell me, in one line each: valid offers on each side, and cost per valid offer on each
   side (estimated cost divided by items covered).
8. Run `uv run providers.py 1` (wishlist item 1, the carry-on) and summarize in two sentences
   how much the provider alone changed the results.
