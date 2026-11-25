# Presenter guide

The session follows one task: be Maya's personal shopping agent for the first 5 items in
`wishlist.csv`, inside the price window in `config.json`. Each offer needs a product, a
retailer, a price, a stock status, one sentence of evidence, the product URL and the date
that price was shown. All 10 items are the take-home.

The timing follows the deck. The exercise slides carry their own minutes (5, 10, 5, 5); the
rest is a suggested split of the other 15.

| Minutes | Slides | Activity |
|---|---|---|
| 0–2 | 1 | Cover. Introduce Maya and what counts as a valid offer: in budget, in stock, priced inside the window, with evidence and a URL. |
| 2–7 | 2 | Your turn: `Clone ... and follow kickoff.md`. The agent's own search and fetch on 5 items. Leave it running. |
| 7–14 | 3–9 | Why web access is harder than it looks, and the routing recipe, while the baseline finishes. Keep a labeled saved run ready. |
| 14–24 | 10 | Your turn: `Follow router.md`. Add WebRouter and repeat on `auto` under the $0.50 budget. Look at which providers served the calls and what failed. |
| 24–28 | 11–13 | Configure vs describe, the measured comparison, the benchmark. Open one or two offers' product pages: separate "no evidence" from "no such offer". |
| 28–34 | 14–15 | The task as routed steps, then your turn: `Follow plan.md`. Read three plans, cut the budget. No web requests. |
| 34–39 | 16 | Your turn: `Follow rule.md`. Change the provider order and compare plans. No web requests. |
| 39–40 | 17–18 | Takeaways and links. Rerunning and scoring the rule, and all 10 items, are the take-home. |

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
