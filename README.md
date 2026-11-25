# WebRouter workshop: give your agent a web router

Hands-on companion to the AI Dev NYC 2026 workshop *Your Agents Need a Web Router*.

One task runs through the whole session: **find every product launch from 30 companies in
a 30-day window**, with the company, the announcement, the event date, the evidence and the
source URL. You run it with your coding agent's own web search, then with the open source
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
| 1 | `Follow kickoff.md` (with the clone line above) | Your agent searches the 30 companies with its built-in web search, logs its web calls and scores the result. |
| 2 | `Follow router.md` | Your agent adds WebRouter as an MCP server, reruns the same task with a budget, and compares with your baseline. Then it compares free providers on one company. |
| 3 | `Follow plan.md` | Your agent asks WebRouter for plans without running anything, and explains the method, providers and reasons. |
| 4 | `Follow rule.md` | You write a ~10-line routing rule, rerun, rescore and post your score. |

## Files

| File | What it is |
|---|---|
| `companies.csv` | The 30 companies and their official domains. |
| `config.json` | The date window and the model `harness.py` uses. |
| `answer_key.csv` | Launches each company announced on its own site in the window. A draft: see below. |
| `kickoff.md`, `router.md`, `plan.md`, `rule.md` | The prompts your agent follows. |
| `score.py` | Scores a results CSV: launches found, stale or undated, missing evidence, plus time, tokens and cost. |
| `compare.py` | All your runs side by side. |
| `providers.py` | One search across WebRouter's free providers, to see how much the provider alone changes the answer. |
| `plan_demo.py` | WebRouter's plans for a few prompts, with and without a tight budget. |
| `my_router.py` | Your routing rule (step 4). `solutions/my_router.py` has one answer. |
| `rule_run.py` | Runs the task through a router's plan and scores it. |
| `harness.py` | Optional, needs `ANTHROPIC_API_KEY`: runs the task through Claude with its built-in web search or with WebRouter's tools, measuring exact tokens and cost. |
| `build_answer_key.py` | For organizers: rebuilds the draft answer key (needs `EXA_API_KEY`). |

## Check the runtime comparison

With `ANTHROPIC_API_KEY` set in your environment, start with the same five companies:

```bash
uv run harness.py --web native --limit 5
uv run harness.py --web webrouter --limit 5
uv run compare.py
```

The harness runs independent WebRouter calls from each model turn concurrently, with
at most six tool calls in flight across all companies. Use `--tool-workers 1` to run
the tool calls serially, or `--search-provider <name>` to test a specific search backend.
Each rerun overwrites that mode's results, so save them before changing settings.

WebRouter runs also write `results/harness_webrouter.trace.jsonl`: the company, tool,
provider, duration, response size and error flag for every completed tool call.
Use this alongside the CSV score and metrics to check runtime without losing track of
result quality. A five-company run is a quick check, not the full 30-company benchmark.

Run the offline concurrency tests with `uv run python -m unittest -v test_tool_batch.py`.

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
