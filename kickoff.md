# Kickoff: your agent's own web search

You're helping in a workshop. Work through these steps without asking questions.

1. Read the first five rows of `companies.csv` (use all 30 only for the take-home) and `config.json` (`window_start`, `window_end`).
2. Run `date -u +%FT%TZ` and remember it as the start time.
3. For each company, use **only your built-in web search and web fetch tools** (install nothing,
   use no other web tools) to find the product launches the company announced inside the window.
   A launch is a new product, feature or release the company itself announced.
   Start each company on its official domain from `companies.csv` (use `site:<domain>`
   in the search query); broaden only if that leaves gaps. Issue independent searches
   together when your agent supports parallel tool calls, up to six at a time.
   Use at most 15 searches and fetch at most five URLs per company, counting failed attempts.
   Read independent source URLs in a batch where supported. Extract a page when search
   evidence does not establish the announcement, date or supporting quotation.
4. **Log every web tool call** you make, one JSON line per call, appended to
   `results/baseline.calls.jsonl`:
   `{"tool": "<tool name, e.g. WebSearch or WebFetch>", "input": "<query or URL>", "result_chars": <approximate length of what the tool returned, in characters>}`
   Log calls that failed or returned nothing too.
5. Write `results/baseline.csv` with columns `company,announcement,event_date,evidence,source_url`
   (`event_date` as YYYY-MM-DD: the date the company announced it; `evidence`: one short sentence from the source).
6. Run `date -u +%FT%TZ` again, then write `results/baseline.meta.json`:
   `{"started": "...", "finished": "...", "seconds": <elapsed>, "agent": "<your name and model>"}`
7. If `uv` isn't installed, install it (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
   Run `uv run score.py results/baseline.csv` and show me the table.

Cost and tokens are estimated from your call log: each search at your tool's list price,
and what the tools returned at about 4 characters per token. No additional web-provider key is needed; your coding-agent subscription or model access still applies.
