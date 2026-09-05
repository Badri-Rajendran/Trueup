1. **You wrote the ledger.** Double-entry, append-only, immutable. My payment provider's balance is their ledger, not yours. Every external money event lands in your ledger as a journal entry, and every balance on every screen is derivable from those entries, including as it stood on any past date.

2. **Webhooks are done properly.** Signatures verified. Consumers idempotent: we will replay events, twice is one. Out-of-order delivery tolerated. Polling is a fallback strategy, not the design.

3. **The correction test.** this project has a specific backdated-correction scenario, listed on its page. It is executed live in the debrief. Corrections are reversal entries plus a re-book, never an edit. The statement shows the corrected figure and still reconciles.

4. **Reconciliation is a feature, not a chore.** A job that pulls provider truth (API or file) and diffs it against your ledger, plus a screen that shows the breaks. We will plant a break and watch it surface.

5. **An agent surface, implemented.** A working MCP surface, not a design for one. Minimum: three read tools and one write tool that lands in the human approval queue. Plus a written list of operations you would never hand an autonomous agent, and why.

6. **Money is never a float.** Integer minor units or exact decimals. State your currency handling and your rounding rule. Pro-rata maths always leaves a penny, and someone has to eat it deterministically.

7. **A decision log written as you go.** Timestamped entries in the repo: what you decided, what you assumed when our answer was too slow, what you cut. A single hour-47 commit titled "add decision log" defeats the purpose and we will read the git history.