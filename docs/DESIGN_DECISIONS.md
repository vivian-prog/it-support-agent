# Design decisions

| Decision | Reason | Cost / alternative |
|---|---|---|
| Narrow VPN and internal access scope | Complete employee journey is demonstrable | Broad infrastructure requests escalate |
| Structured final decision + curated renderer | Ground actions in reviewed data and enforce boundaries in code | Less flexible conversation and limited runbook coverage |
| Single model tool loop | Tools and state are easy to inspect | No specialized subagents; not needed for this scope |
| Standard-library HTTP and SQLite | One-command local run without package setup | Custom routing; coarse lock; production needs mature auth/concurrency |
| Separate visible deterministic baseline | Repeatable demos without credentials and falsifiable comparisons | Must never be passed off as model intelligence |
| Fixed synthetic snapshot clock | Stale/fresh cases stay reproducible on any date | Not live health; production uses real time |
| No account/device write tools | Authentication and approval are not implemented | Only guided fixes and local handoff |
| Article registry validates returned steps | Retrieved prompt injection cannot create executable advice | New KB content needs review; no free-form repair generation |
| Explicit user recovery confirmation | Giving advice is not resolving an issue | Whitelist misses valid phrasing; production needs validated semantic feedback |
| Local handoff with transcript and trace | Human can continue without collecting the same facts | No delivery acknowledgement or human SLA |

The primary hypothesis is that context-aware tool use can reduce repetitive IT support exchanges while making failures and escalation inspectable. The current regression suite verifies implementation invariants; it does not validate that business hypothesis. A next-stage experiment should compare FAQ, rules and model orchestration on independent scenarios, measuring correct resolution, inappropriate guidance, escalation precision/recall, employee effort, latency and cost.
