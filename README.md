# WebRouter workshop: give your agent a web router

Hands-on companion to the AI Dev NYC 2026 workshop *Your Agents Need a Web Router*.

One task runs through the whole session: **find every product launch from five companies in
a fixed date window**, with the company, the announcement, the event date, the evidence and the
source URL. You run it with your coding agent's own search and fetch, then with the open source
[WebRouter](https://github.com/Nimbleway/webrouter) (an Apache 2.0 library that puts one
interface in front of many web search, extract and browser providers), and compare quality,
time, tokens and cost.

## What you need

- A coding agent: Claude Code, Cursor or similar.
- [uv](https://docs.astral.sh/uv/). Your agent installs it if it's missing.
- Your coding agent needs its usual model access or subscription. WebRouter search and extract
  can work without extra provider keys, subject to backend availability and quotas.

You don't need to clone WebRouter: the exercises run it with `uv` / `uvx` when they need it.

## The exercises

Open your coding agent in an empty folder and paste:

> Clone https://github.com/Nimbleway/webrouter-workshop and follow kickoff.md

Then, when the speaker gets there, paste each of these in the same agent:

| Step | Paste | What happens |
|---|---|---|
| 1 | `Follow kickoff.md` (with the clone line above) | Your agent searches the first five companies with its built-in web search, logs its web calls and scores the result. |
| 2 | `Follow router.md` | Your agent adds WebRouter as an MCP server, reruns the same task with a budget, and compares with your baseline. Then it compares providers on one company. |
| 3 | `Follow plan.md` | Your agent asks WebRouter for plans without running anything, and explains the method, providers and reasons. |
| 4 | `Follow rule.md` | You write a ~10-line routing rule, inspect the changed plan, then compare saved outputs. |

## Files

| File | What it is |
|---|---|
| `companies.csv` | The 30 companies and their official domains. |
| `config.json` | The date window and the model `harness.py` uses. |
| `answer_key.csv` | Launches each company announced on its own site in the window. A draft: see below. |
| `kickoff.md`, `router.md`, `plan.md`, `rule.md` | The prompts your agent follows. |
| `score.py` | Reports draft-key overlap and field checks, plus source-reviewed labels when supplied. |
| `compare.py` | All your runs side by side. |
| `providers.py` | One search across WebRouter's available providers, to see how much the provider alone changes the answer. |
| `plan_demo.py` | WebRouter's plans for a few prompts, with and without a tight budget. |
| `my_router.py` | Your routing rule (step 4). `solutions/my_router.py` has one answer. |
| `rule_run.py` | Runs the task through a router's plan and scores it. |
| `harness.py` | Optional, needs `ANTHROPIC_API_KEY`: runs the task through Claude with native search and fetch or with WebRouter's search and extract, measuring API tokens and estimating cost. |
| `build_answer_key.py` | For organizers: rebuilds the draft answer key (needs `EXA_API_KEY`). |

## Reproduce the comparison

Set `ANTHROPIC_API_KEY`, then run the same five companies with each configuration:

```bash
uv run python -m unittest -v
uv run harness.py --web native
uv run harness.py --web webrouter --extract-provider auto
uv run harness.py --web webrouter --extract-provider max
```

Each command writes a new directory under `results/`, prints its path, and preserves
previous runs. Pass the CSV paths to `uv run compare.py <native.csv> <auto.csv> <max.csv>`.
Repeat all three configurations, rotating their order, before drawing conclusions.
Use all 30 companies only for a broader follow-up, not the live exercise.

Both paths request the same model with fallback disabled and allow at most 15 searches
and five fetched URLs per company. Failed routed requests consume that allowance too.
Native uses hosted search plus fetch; WebRouter uses search plus asynchronous extraction.
The native service's dynamic filtering and provider search results still differ from
WebRouter's tools. This compares configured web toolkits, not routing in isolation.
An observed native limit overrun or incomplete output invalidates the run.

The default extraction policy is `auto`. Optional `max` lets the first backend run for
two seconds before racing alternatives; an earlier failure starts alternatives immediately.
A complete batch wins; partial failures remain explicit. Each tool call has a 20-second
deadline. At most six routed tool calls run concurrently, but each may dispatch several
provider requests. Native fetch uses a 4,000-token content limit; routed extraction uses
16,000 characters per page. These are approximate, not identical, content budgets.

The attendee MCP exercise uses `auto` under its shared cost cap. Do not force `max`
under that cap: this package version cannot bound its race cost. The API harness is a
separate experiment with retrieval limits, not the attendee's dollar budget.

Artifacts include the configuration, package versions, source hashes, company status,
serving models, cache usage, tool results and provider attempts (including failed or
cancelled race members). The unique session prefix limits cross-run prompt-cache reuse;
each run enables the same five-minute caching policy. Backend caches and quotas can
still vary. Generated artifacts stay local and are ignored by git.

Costs are estimates, not invoices. Model usage uses the distinct input, output, cache-write
and cache-read prices from [Anthropic](https://platform.claude.com/docs/en/about-claude/pricing).
WebRouter's returned-provider subtotal does not include every losing or failed attempt;
unknown prices remain unknown, and its total cost is not displayed as a complete amount.
Do not interpret cancellation as proof that a provider did not bill.

## Account for provider attempts

For a reproducible anonymous-provider experiment, use `--provider-profile keyless`.
This fixes the search and extraction chains, rejects inherited provider credentials,
and records the resolved settings. Use an environment containing only the model key
and ordinary operating-system settings; provider endpoint overrides should be absent.
The default `environment` profile retains normal provider discovery.

Each run also writes `attempts.json`, independently of successful tool results and
after race cleanup. It retains every observed leaf attempt, including errors and
cancelled losers, with separate catalogue estimates, provider-reported cost/usage,
and HTTP dispatch outcomes. Authentication is recorded as booleans; credentials and
request URLs are not copied into this ledger. A dispatch does not prove server receipt,
and cancellation does not prove nonbilling.

Reconcile the ledger against the applicable provider terms or account usage before
claiming a complete cost. Free anonymous access and paid production pricing are
different comparisons. Unknown charged usage stays unknown; a catalogue estimate
is not a receipt. Model costs remain usage-based estimates until matched to billing.

## Validate results

`score.py` reports conservative exact-title/date draft-key overlap, not accuracy. Review
records against dated primary sources before comparing quality. Define one event, check
its announcement date and supporting evidence, and label duplicates and unresolved rows.
Use the same rubric for every arm and hide the arm during review where possible.

Optional `<run>.review.json` sidecars contain:

```json
{
  "records": [{"record_id": "hash from score.record_id(row)", "status": "valid",
               "event_id": "stable-event-id", "verified_source": "https://example.com/release"}],
  "reference_event_ids": ["stable-event-id"],
  "reference_complete": false
}
```

Statuses are `valid`, `invalid`, `duplicate`, or `unresolved`. Missing labels remain
unresolved. Repeated valid event IDs count once. Precision is reported only when all
returned rows are reviewed. Recall requires an independently reviewed, complete scoped
reference; a pooled list of returned events alone is not an exhaustive reference.
Keep the event/date decisions and evidence beside the review file for an audit.

For the 40-minute session and the claims each exercise supports, see [workshop.md](workshop.md).

## About the answer key

`answer_key.csv` was built automatically from each company's own site for the window in
`config.json`, then filtered to launch-like titles. It misses some launches and includes a
few non-launches, so treat "not in answer key" rows as "check by hand", not as wrong.
Organizers: update the window in `config.json`, run `uv run build_answer_key.py` the day
before the session, and review the file by hand.

## Links

- WebRouter: https://github.com/Nimbleway/webrouter
- WebRouter docs: https://docs.webrouter.net
- WebRouter Discord: https://discord.gg/MGztFWSjZh
