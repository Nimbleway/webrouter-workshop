# Read the plan

You're helping in a workshop. Work through these steps without asking questions.

1. Run `uv run plan_demo.py`. It asks the open source WebRouter
   (https://github.com/Nimbleway/webrouter) for a plan for three prompts (one with a URL,
   a plain question, a request for a report) and runs nothing. Then it asks again with a
   $0.001 budget.
2. For each prompt, tell me in one line: the method the router chose, the providers in
   order, and the reason it gave.
3. Tell me in two sentences what changed under the tight budget: which providers were
   dropped before anything ran, and why.
4. Point out one thing the default rules did **not** do for
   the fixed-date launch prompt (hint: a date in prose is not an enforced search filter).
5. Then run `uv run plan_demo.py "<a prompt of your own>"` with a prompt I give you, or one
   you choose if I don't, and explain its plan the same way.
