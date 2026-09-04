# Investment app

Retail customers put money in, buy into a model portfolio, and get rebalanced. Positions are valued every day, returns are reported back, and when the custodian is late with the truth, history gets restated without ever being rewritten.

# The brief, as we received it

> We are building a retail investing product. Customers deposit money, buy into one of four model portfolios, and we rebalance monthly. Nothing exotic, just equities and bonds through a single custodian.
> 
> 
> Positions have to be valued every day. Customers see a balance, a return figure for the period, and a full transaction history they can export at tax time.
> 
> Every ledger entry is immutable. We are regulated and we never rewrite history. When something lands late from the custodian — a dividend, a stock split, a corrected closing price — the customer's return figure for the affected period must be restated to the correct number. Tax reporting depends on it being right.
> 
> Nobody invests until identity checks pass, and money comes in from a linked bank account, not a card. We will not build custody, identity or bank linking ourselves — use providers.
> 
> Users need to see their portfolio. Users need to approve trades above a threshold. Users need to reconcile against the custodian file every morning.
> 
> We want to be live in six weeks. In scope for v1: onboarding and identity checks, deposits and withdrawals, model portfolios, order placement, daily valuation, monthly rebalancing, dividend handling, tax lot accounting, statements, a mobile app, and an adviser console.
> 

# What you are actually building

The core loop, working end to end on a deployed URL:

**onboard with a real KYC check → link a bank and deposit through open banking → buy into a model portfolio with real paper orders → value the book daily → take a late custodian correction and restate the return → reconcile against the custodian every morning.**

Mobile app versus web, adviser console versus admin — your scoping call. Defend it. Everything is USD and US-listed securities: US market hours, T+1 settlement, US tax lots. Single-currency is a deliberate simplification — spend the saved hours on lots and restatements.

# Required integrations

| Slot | Requirement | Suggested sandbox | Live or simulated |
| --- | --- | --- | --- |
| Brokerage / custody | Real accounts, real order lifecycle — submitted, partially filled, filled — with fills arriving by webhook, not just polling. | Alpaca paper trading or Broker API sandbox | Must be live |
| KYC | Nobody funds an account before passing. Show pending and rejected, not just approved. | Persona, Sumsub, Stripe Identity test mode | Must be live |
| Funding — open banking | Link an external bank account and pull deposits from it. Handle the deposit that later bounces. | Plaid sandbox test users | Must be live |
| Market data | Daily closes driving valuation. Handle the missing close and the stale price honestly. | Alpaca data, Polygon or Twelve Data free tiers | Live or simulated |
| Custodian file | A morning positions-cash-transactions file to reconcile against. Your simulator should also ship the late dividend and the corrected price — that is where the track lives. | Simulator expected; label it | Simulated is fine |
| Idle cash — stretch | Sweep uninvested cash into a yield representation, or accept a deposit in USDC. | Circle sandbox, testnet only | Stretch |

# The domain gauntlet

1. **Units and money are different dimensions.** Positions are units to six decimal places; value is units times price; cash is just another position. Mixing the dimensions is the classic day-one bug.
2. **Double-entry across cash and assets.** A buy debits units and credits cash, plus fees. If your ledger cannot show both legs of every trade, it is a list, not a ledger.
3. **Settlement.** Trades settle T+1. Settled cash and available cash diverge and re-converge; you cannot withdraw proceeds that have not settled. Model the gap, do not hide it.
4. **Tax lots.** Every buy opens a lot. Sells consume lots — FIFO or specific-ID, pick and defend. Realized versus unrealized gains fall out of lots done right, and the tax export depends on them.
5. **The dividend.** Declared, ex-date, pay-date — the money arrives days after the entitlement. A dividend that lands late for a period you already reported triggers the restatement machinery.
6. **The split.** A 2-for-1 split doubles units, halves per-unit basis, changes neither value nor return. If your return figure moves on a split, the model is wrong.
7. **The return figure.** Time-weighted versus money-weighted — know why they differ, pick one, defend it. A deposit is not a return; flows must not pollute performance. This is the single most common domain failure we see.
8. **The restatement.** A corrected closing price arrives for three days ago. The affected period's return is restated, the customer sees the corrected number, and the originally published figure remains queryable forever — as-published and as-corrected are both first-class. We run this live.
9. **Rebalancing.** Drift from model weights, order generation with minimums and fractional rules and a cash buffer, partial fills that leave the book mid-flight overnight.
10. **The morning reconciliation.** Positions, cash and transactions against the custodian file. Breaks surfaced on a screen with aging — not a log line.

# Live fire

- Onboard with a sandbox identity, link a Plaid test bank, deposit, invest into a model — watching your orders land at the broker.
- Deliver a corrected close for three days ago and watch the restatement: corrected figure shown, published history preserved.
- Run a 2-for-1 split. Units double, basis halves, return unchanged.
- Replay a fill webhook. Positions must not double.
- Bounce a deposit after the cash was invested, and ask what the customer sees.
- Tamper one position in the custodian file and ask your reconciliation screen to find it.

# A build order that works

Ledger and units model first — get the two-dimension problem right before any UI. Wire Alpaca and Plaid on day one; the T+24h checkpoint expects a deposit buying real paper positions. Valuation and returns second. The restatement machinery third — it is the differentiator, budget real hours for it.

# Stretch ladder

- USDC deposits or an idle-cash sweep, on testnet, ledgered honestly.
- Recurring deposits with a standing investment instruction.
- Model portfolio versioning: the model changes, existing customers drift, what happens next.
- A tax report PDF a human accountant would accept.
- Adviser console with bulk rebalance approval — maker-checker at portfolio scale.
- Performance fee accrual, computed daily, charged monthly.

# What we grade hardest here

The return figure's integrity under flows and corrections, tax lots, and whether your reconciliation actually catches the break we plant. 
