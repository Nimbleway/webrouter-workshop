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
3. Redo the kickoff task (same companies, same window) using **only web-router's tools**
   (`search`, `extract`), not your built-in web tools. Search and extract need no API keys.
   Keep the same official-domain-first queries and parallelism as the baseline.
   Use `max_results=5` for the initial search and pass independent URLs together to
   `extract`. Keep the default search provider. For extraction, use `provider="max"`
   to race available extractors instead of waiting for sequential provider fallback.
   This can start extra billable fetches: keep the shared budget active and record
   the reported cost. Keep failed URLs explicit; don't count them as read pages.
   The Python harness delays its alternative extractors by two seconds; MCP's `max`
   races them immediately. The task has a fixed
   date window: put those dates in the query and verify event dates from evidence,
   rather than using a relative `recency` filter.
   Start the task timer after installation, restart and budget setup; stop it after
   writing the result CSV. Exclude scoring, comparison and the provider demo below.
4. Log every web-router call to `results/router.calls.jsonl`, one JSON line each:
   `{"tool": "<search or extract>", "input": "<query or URLs>", "result_chars": <approximate length returned>, "cost_usd": <the cost the tool reported, or null>}`
5. Write `results/router.csv` (same columns as `results/baseline.csv`) and
   `results/router.meta.json` (`started`, `finished`, `seconds`, `agent`), timing with `date -u +%FT%TZ`.
6. Call `budget_status` and tell me what it reports.
7. Run `uv run score.py results/router.csv`, then `uv run compare.py`, and show me both tables.
8. Run `uv run providers.py Figma` and summarize in two sentences how much the provider
   alone changed the results.
