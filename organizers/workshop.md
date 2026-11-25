# Presenter guide

The session follows one task: be Maya's personal shopping agent for the first 5 items in
`wishlist.csv`, inside the price window in `config.json`. Each offer needs a product, a
retailer, a price, a stock status, one sentence of evidence, the product URL and the date
that price was shown. All 10 items are the take-home.

| Minutes | Activity |
|---|---|
| 0–5 | Explain the task and what counts as a valid offer: in budget, in stock, priced inside the window, with evidence and a URL. |
| 5–13 | `Follow kickoff.md`: the agent's own search and fetch. Keep a labeled saved run ready. |
| 13–23 | `Follow router.md`: add WebRouter and repeat on `auto` under the $0.50 budget. Look at which providers served the calls and what failed. |
| 23–30 | Check a few offers against their product pages. Separate "no evidence" from "no such offer". |
| 30–37 | `Follow plan.md`, then `Follow rule.md`: read a plan, change the provider order, explain what changed. No web requests. |
| 37–40 | Discuss observed quality, time and known cost. Rerunning and scoring the rule, and all 10 items, are the take-home. |

## Before the session

- Rebuild the answer key and the window the day before (see the README).
- Run the MCP install, the budget call and one `extract` on the presenter machine, with the
  exact commands in `router.md`.
- If a live service is down, switch to a saved run and say so.
- A result from `organizers/harness.py` is an API measurement. It doesn't predict what an
  attendee's coding agent will do or how long it takes.

## What the numbers support

- Compare the same items, the same model, a web-enabled baseline and the same limits on
  both sides (15 searches and 5 page reads per item).
- "Found" and "covered" come from the answer key and the offer's own fields. They aren't a
  source check: open the page before calling an offer correct.
- Costs are estimates. A call with no reported cost is counted as $0 and flagged as
  unpriced, so the total is a floor, not a bill.
- Give the sample, the configuration and the number of repeats with any figure, and
  report the tradeoff you saw. Routing doesn't always win.
