# Scoring

Out of 100. We share this deliberately: knowing exactly how you are graded and still choosing what to sacrifice is the skill being tested.

| Area | Points | What earns them |
| :--- | :--- | :--- |
| Domain command | 30 | The vertical's mechanics live in your schema and your state machines, not your README. The track's domain gauntlet handled correctly. Vocabulary used precisely under questioning. |
| A system that runs | 25 | Deployed, stable through the demo, core loop working end to end. The three screens that matter show default, loading, empty, error and one edge state. |
| Integration reality | 20 | Two or more genuinely live sandbox integrations. Verified signatures, idempotent consumers, graceful degradation when a provider is down. Honest real-versus-simulated labelling. |
| Live fire | 15 | The system survives our scripted attacks. When something breaks, you diagnose it in front of us instead of defending it. |
| Judgment and communication | 10 | Questions asked early and well. Assumptions written down. A credible cut list. A decision log a stranger can follow. |

Automatic fails, regardless of everything else:

- Localhost only, or a video in place of a URL.
- A simulated integration presented as live.
- UPDATE or DELETE on money rows. Anywhere. Ever.
- Live-mode API keys, real money, or real personal data.
- Secrets committed to the repo.