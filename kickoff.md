# Kickoff: your agent's own web search

You're helping in a workshop. You are Maya's personal shopping agent. Work through these
steps without asking questions.

1. Read `persona.json` (Maya: where she lives, her sizes, what every offer must meet),
   the **first 5 rows** of `wishlist.csv` (each with a `max_price_usd` and a `must_have`; all 10
   are for the take-home) and `config.json` (`window_start`, `window_end`: prices must have been
   shown in this window).
2. Run `date -u +%FT%TZ` and remember it as the start time.
3. For each wishlist item, use **only your built-in web search and web fetch tools** (install
   nothing, use no other web tools) to find the best offer for Maya: one specific product that
   meets every constraint in `persona.json` and the item's row, in stock, at or under the max
   price, from a US retailer or the brand's own store. Use at most 15 searches and read at most
   5 pages per item, counting failed attempts. Work on several items at once when your agent
   supports parallel tool calls.
4. **Log every web tool call** you make, one JSON line per call, appended to
   `results/baseline.calls.jsonl`:
   `{"tool": "<tool name, e.g. WebSearch or WebFetch>", "input": "<query or URL>", "result_chars": <approximate length of what the tool returned, in characters>}`
   Log calls that failed or returned nothing too.
5. Write `results/baseline.csv` with columns
   `item_id,product,retailer,price_usd,in_stock,evidence,source_url,seen_date`, one row per item
   (skip an item if nothing qualifies). `price_usd`: a number. `in_stock`: true or false.
   `evidence`: one short sentence from the source showing the price and stock. `source_url`: the
   product page. `seen_date` (YYYY-MM-DD, your local date from `date +%F`): the date the source
   showed that price: today, for a live product page you opened; the article's date, for a deal
   post or roundup; the date the search result itself shows, or empty, for a price you only saw
   in a search snippet. Don't guess a price or a date: leave the row out instead.
6. Run `date -u +%FT%TZ` again, then write `results/baseline.meta.json`:
   `{"started": "...", "finished": "...", "seconds": <elapsed>, "agent": "<your name and model>"}`
7. If `uv` isn't installed, install it (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
   Run `uv run score.py results/baseline.csv` and show me the table.

Cost and tokens are estimated from your call log: each search at your tool's list price,
and what the tools returned at about 4 characters per token. No extra API key is needed
beyond your coding agent's own model access.
