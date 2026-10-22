# Recorded validation

Build validation date: 2026-10-20 (Asia/Shanghai client date).

- Python 3.9.6; standard library only.
- `python3 -m unittest discover -s tests -v`: **24 tests passed**.
- `python3 evaluate.py`: **19/19 deterministic scenarios passed**; full trace report in `evaluation/demo-report.json`.
- Fake model transport: multi-request Responses tool calls, returning function outputs, history continuity, token accounting, unauthorized tools, invalid final decisions, model outage, bounded loops and unsafe escalation prose.
- Real HTTP: session cookies, cross-client isolation, Host/Origin checks, invalid inputs, CSP, traversal rejection, handoff retrieval.
- Browser: started new session, submitted VPN problem, saw reviewed steps and citations, provided failure feedback, saw terminal local handoff and downloaded its JSON. Download was parsed and checked for attempts and transcript; synthetic sample saved as `docs/example-handoff.json`.
- Browser: selected status-timeout environment, restarted server, refreshed with persisted session, submitted VPN problem, verified escalation that explicitly refused to assume service health.
- Layout inspected at the default narrow view and a desktop viewport. Screenshot in `docs/demo-preview.jpg` shows the narrow view and approved guided steps. No front-end console errors were observed during the inspected interaction.

## Scope of initial validation

At the initial build, no API credentials/model ID were configured and no real model endpoint was called. The ChatGPT OAuth/live smoke check completed later and is recorded below. API Key credentials, real IT services, corporate SSO, device actions and external ticket delivery remain unverified/unconnected. The fake transport tests alone establish protocol handling, not model judgment.

These are co-designed synthetic regression cases, not an independent holdout or a production security assessment. Candidate review has not been claimed. See `AI_USAGE.md`.

## UI copy revision

Replaced promotional slogans and formal diagnostic phrasing with concise Chinese. Buttons, status labels, guided steps, follow-up messages and escalation explanations were updated. Verified the new conversation in the browser; 5 HTTP integration checks and 19 deterministic scenarios passed after the copy changes. The screenshot and sample handoff reflect the revised text.

## ChatGPT authorization addition

The API Key connection remains implemented. Added separate ChatGPT OAuth/plan provider with PKCE, state/browser binding, nonce and signature validation, scope enforcement, issued-client identity binding, protected credential writes, rotating refresh, model catalog selection, revocation and fail-closed SSE completion. The test suite now has 39 tests, including positive/negative RSA JWT verification and a mock comparison proving distinct API Key vs OAuth request contracts. The deterministic scenario suite remains 19/19. No real account credentials are used in unit tests.

The in-app OpenAI login form did not advance in the inspected attempt; the user reported the regular-browser flow advanced. At that stage full live authorization was pending; the completed authorization and live smoke result are recorded below.

## Completed live ChatGPT check

The user completed authorization in an ordinary browser. The app validated the ID token and plan scope, fetched seven account models, and retained the connection through server restart. A first request exposed that this route's `response.completed.output` can be empty even when finalized function calls have been emitted in `response.output_item.done`. The SSE parser now collects finalized streamed items while still requiring a terminal completion event, and a regression test covers that exact shape.

The subsequent isolated synthetic VPN conversation passed: model `gpt-6.1-sol`, 15.75 seconds, 4 model requests, 7 model-selected calls, valid runbook guidance and no tool errors. Full sanitized result: `evaluation/chatgpt-smoke.json`. This used the ChatGPT OAuth token, not the API Key environment variable. The API Key path remains separately implemented and contract-tested; its paid endpoint has not been exercised with a real key. The suite now has 39 passing tests plus 19/19 deterministic scenarios. A single smoke pass does not establish general diagnostic accuracy.

## Extended real-model checks, 2026-10-22 summary

Added 13 new synthetic Chinese/English and failure-case conversations through the live ChatGPT connection. Initial result: 11/13. One repeatable recovery-feedback context bug was fixed with regression coverage. The English case hit transport failures twice; the failure paths preserved context and escalated safely but did not count as successful diagnostic runs. A bounded transport retry and separate metrics were added. The last two-case retest passed without a live retry being triggered; retry recovery was verified using synthetic timeouts and resets. Latest observed per-case outcomes are 13/13 across initial and targeted retests, not a full final-build run. Current unit/integration tests: 44/44. Deterministic scenarios after the changes: 19/19. See the detailed dated Chinese report and raw JSON reports.
