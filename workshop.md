# Presenter guide

The session follows one task: find product launches announced by the first five
companies in `companies.csv`, within the exact dates in `config.json`. Each record
needs an announcement, its date, supporting evidence and a source URL.

| Minutes | Activity |
|---|---|
| 0–5 | Explain the task and what counts as a distinct supported launch. |
| 5–13 | Run the native search-and-fetch exercise. Keep a labeled saved run available. |
| 13–23 | Add WebRouter and repeat with budgeted `auto`. Inspect the serving providers and failures. |
| 23–30 | Review a few claims against dated sources; separate missing evidence from genuinely missing launches. |
| 30–37 | Inspect a plan, change a provider-order rule and explain the changed choice. |
| 37–40 | Discuss observed quality, latency and known cost. Move extended runs to the take-home. |

Preflight the exact MCP installation, budget and extraction steps on the presenter
machine. If a live service is unavailable, switch to a clearly labeled saved run.
A Python API harness result does not guarantee a coding agent's runtime or output.

## Slide copy

Opening: **Give your agent a web router.** One interface for multiple providers,
explicit routing choices and fallback when a provider cannot serve a request.

Exercise: **Find five companies' launches in a fixed date window.** Compare the same
model using native search and fetch with WebRouter search and extract. Inspect the
source before counting a record as correct.

Comparison: **Measure the tradeoff on your task.** Report supported distinct events,
invalid and unresolved records, elapsed time and known versus unknown costs. Include
the sample, configuration and repeat count with any quantitative result.

Closing: **Inspect, route, verify.** Change the provider policy, see what served the
request, and check whether the result earns its latency and cost.

Every quantitative comparison needs the same task, a web-enabled baseline and a
source-validation rubric. Raw row counts do not establish accuracy. Report observed
tradeoffs without promising that routing always wins.
