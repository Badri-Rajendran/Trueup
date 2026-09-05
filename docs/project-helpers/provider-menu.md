# The provider menu

All of these have free, self-serve sandbox or test modes as of mid-2026. They are suggestions, not requirements: any equivalent is fine, though the menu is deliberately US-first, because Corgi is. Spend $0: if a provider wants a card or a company you do not have, use their prefab test entities or simulate and label it.


| Slot | Suggested providers | Notes |
| :--- | :--- | :--- |
| **KYC: identity** | Persona, Sumsub, Stripe Identity, Onfido | Use the provider's published test identities. Never feed real PII, yours or anyone's, into a trial system. |
| **KYB: business** | Middesk, Persona KYB, Sumsub KYB | Gate the account: unverified entities can look but not transact. |
| **Payments: cards and collection** | Stripe test mode, GoCardless sandbox (direct debit) | Test cards, test clocks, webhook replay from the dashboard: use all of it. |
| **Payment rails: ACH, transfers** | Increase sandbox, Moov test mode, Modern Treasury sandbox | All simulate returns and delayed settlement. Returns are the interesting part. |
| **Open banking** | Plaid sandbox, TrueLayer sandbox, GoCardless bank account data | Plaid's sandbox test users are the fastest path to a linked funding account. |
| **Card issuing** | Lithic sandbox, Stripe Issuing test mode, Marqeta sandbox | Both Lithic and Stripe let you simulate an authorization, then capture a different amount later. That asymmetry is the whole point of Track 3. |
| **Brokerage and market data** | Alpaca paper trading + Broker API sandbox; Polygon or Twelve Data free tiers | Alpaca gives you accounts, orders, fills and positions with no money at risk. |
| **Stablecoins** | Circle sandbox (USDC on testnet), Bridge sandbox | Testnet only: Base Sepolia or equivalent. A stablecoin payout that actually confirms on a testnet is worth far more than a slide about one. |
| **Documents and e-sign** | Documenso (open source), Dropbox Sign test mode, DocuSign developer | Documents must be generated from data, never hand-typed. |