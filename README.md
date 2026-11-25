# WebRouter workshop: give your agent a web router

Hands-on companion to the AI Dev NYC 2026 workshop *Your Agents Need a Web Router*.

One task runs through the whole session: **you're a personal shopping agent for one shopper,
Maya, with a 10-item holiday wishlist**. For each item, find one specific product that meets
every constraint (her size, her price cap, in stock, ships to Brooklyn within a week, free
returns), with the retailer, the price, the evidence, the product URL and the date that price
was shown, inside the last 7 days. You run it with your coding agent's own web search, then with the open source
[WebRouter](https://github.com/Nimbleway/webrouter) (an Apache 2.0 library that puts one
interface in front of many web search, extract and browser providers), and compare quality,
time, tokens and cost.

## What you need

- A coding agent: Claude Code, Cursor or similar.
- [uv](https://docs.astral.sh/uv/). Your agent installs it if it's missing.
- No API keys. WebRouter's search and extract work keyless; costs and tokens for your agent's
  own runs are estimated from a log your agent keeps of its web calls.

You don't need to clone WebRouter: the exercises run it with `uv` / `uvx` when they need it.

## The exercises

Open your coding agent in an empty folder and paste:

> Clone https://github.com/Nimbleway/webrouter-workshop and follow kickoff.md

Then, when the speaker gets there, paste each of these in the same agent:

| Step | Paste | What happens |
|---|---|---|
| 1 | `Follow kickoff.md` (with the clone line above) | Your agent shops the first 5 wishlist items with its built-in web search and fetch (at most 15 searches and 5 page reads per item), logs its web calls and scores the result. All 10 items are the take-home. |
| 2 | `Follow router.md` | Your agent adds WebRouter as an MCP server, reruns the same 5 items with the same limits on `auto` under a $0.50 budget, and compares valid offers and cost per valid offer with your baseline. Then it compares free providers on one wishlist item. |
| 3 | `Follow plan.md` | Your agent asks WebRouter for plans without running anything, and explains the method, providers and reasons. |
| 4 | `Follow rule.md` | You write a ~10-line routing rule and compare its plans with the default rules' plans (no web requests). Rerunning and scoring your rule is the take-home. |

## Files

| File | What it is |
|---|---|
| `persona.json` | The shopper: where she lives, her sizes, what every offer must meet. |
| `wishlist.csv` | Her 10 items, each with a `max_price_usd` and a `must_have`. |
| `config.json` | The price window (prices must have been shown inside it) and the model `harness.py` uses. |
| `answer_key.csv` | The reference: qualifying offers for each item, priced in the window. See below. |
| `kickoff.md`, `router.md`, `plan.md`, `rule.md` | The prompts your agent follows. |
| `score.py` | Scores a results CSV: items found and covered, stale prices, over budget, out of stock, missing evidence, plus time, tokens and cost. |
| `compare.py` | All your runs side by side. |
| `providers.py` | One search across WebRouter's free providers, to see how much the provider alone changes the answer. |
| `plan_demo.py` | WebRouter's plans for a few prompts, with and without a tight budget. |
| `my_router.py` | Your routing rule (step 4). `solutions/my_router.py` has one answer. |
| `rule_run.py` | Searches the wishlist items through a router's plan (default rules or yours) and saves the raw results and a call log; your agent turns them into a CSV to score. |
| `organizers/harness.py` | Optional, for organizers, needs `ANTHROPIC_API_KEY`: runs the task through Claude with its built-in search and fetch or with WebRouter's search and extract, under the same limits, and measures API tokens, to check the estimates attendees get from their call logs. See below. |
| `organizers/provider_trace.py`, `organizers/tool_batch.py` | Used by the harness: run a turn's tool calls in parallel and record every provider attempt. |
| `organizers/tests/` | Tests for the harness, the attempt ledger and the scoring helpers. |
| `organizers/workshop.md` | Presenter guide: the 40-minute timing, the preflight and what the numbers support. |
| `organizers/build_answer_key.py` | For organizers: rebuilds the answer key and the window (needs `NIMBLE_API_KEY`). |
| `organizers/answer_key_raw.json` | Every row the answer-key agents returned, kept or not, for spot checks. |

## About the answer key

`answer_key.csv` is built by one Nimble Web Search Agent run per wishlist item at x-high
effort, told to open retailers' and brands' own product pages for the live price and stock,
and to list up to 8 products that meet every constraint. Offers over the item's price cap,
out of stock, outside the window or without a URL are dropped.

`score.py` counts an offer when it's in budget, in stock, priced inside the window and has
evidence and a URL ("covered"), and an item as "found" when that offer is for a product the
answer key also lists. It's a strong reference, not the only right answer: there are more
good carry-ons than any key lists, so treat "not in answer key" rows as "check by hand".

Organizers: prices move daily, and the session lands on Cyber Monday. The day before, run
`uv run organizers/build_answer_key.py` (window = the 7 days ending today, or pass
`--end YYYY-MM-DD`). It rewrites the window in `config.json` and `answer_key.csv`;
spot-check a few items, then commit both.

## For organizers: measure the comparison

`organizers/harness.py` runs the same task through the API, so you can check the numbers
attendees estimate from their call logs. Set `ANTHROPIC_API_KEY`, then:

```bash
uv run --group organizers python -m unittest discover -s organizers/tests
uv run organizers/harness.py --web native
uv run organizers/harness.py --web webrouter
uv run organizers/harness.py --web webrouter --extract-provider max
```

Each command runs the first 5 items (`--limit 10` for all of them), writes a new directory
under `results/` and prints its path. Earlier runs are kept, and `results/` is ignored by
git. Pass the CSVs to `uv run compare.py <native.csv> <auto.csv> <max.csv>`. Repeat each
configuration, in a different order, before you draw a conclusion.

What's held equal: the model (server-side fallback is off, and a run served by another model
is rejected), the prompt, and the allowance per item, 15 searches and 5 fetched URLs, with
failed requests counted. What isn't: Claude's hosted search and fetch filter results their own
way, WebRouter searches use a one-week recency filter (`--recency none` turns it off), and
page text is capped at 4,000 tokens on one side and 16,000 characters on the other. This
compares two web toolkits as configured, not routing on its own.

`--extract-provider max` lets the first extractor run for two seconds, then races the others.
Keep it out of the attendee exercise: under a cost cap, this WebRouter version can't bound
what a race costs. `--provider-profile keyless` fixes the provider chains and refuses to run
if a provider key is set, for a comparison anyone can reproduce without accounts.

Every run directory has:

- `manifest.json`: the options, package versions, source hashes, git commit and provider chains.
- `harness_<web>.csv`, `.metrics.json` and `.details.json`: the offers, the totals, and per-item
  status, model usage and tool results. A run with a failed or incomplete item exits with an
  error and reports no total cost.
- `attempts.json`: every provider attempt, including failed ones and cancelled race losers,
  with the provider's reported cost and usage, a catalogue estimate and the HTTP outcome.
  Credentials are recorded as present or absent only; request URLs and bodies aren't stored.

Costs are estimates, not invoices. The model cost uses list prices for input, output, cache
writes and cache reads. The WebRouter subtotal covers the responses that came back with a
price; losing and failed attempts may still have been billed, and a cancelled request isn't
proof of no charge. Check `attempts.json` against your provider accounts before you quote a
total.

To check quality by hand, put a `<run>.review.json` next to a results CSV:

```json
{"records": [{"record_id": "from score.record_id(row)", "status": "valid",
              "event_id": "item-1-brand-model", "verified_source": "https://example.com/product"}]}
```

`status` is `valid`, `invalid`, `duplicate` or `unresolved`. `score.py` then also shows the
reviewed counts. Rows without a label stay unresolved, a repeated valid `event_id` counts
once, and precision appears only when every row is reviewed. Use the same rules for every
run, and hide which run a row came from while you review, where you can.

## Links

- WebRouter: https://github.com/Nimbleway/webrouter
- WebRouter docs: https://docs.webrouter.net
- WebRouter Discord: https://discord.gg/MGztFWSjZh
