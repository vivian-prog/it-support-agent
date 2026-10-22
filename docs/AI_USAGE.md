# AI assistance disclosure

This project was developed with substantial AI assistance in Codex. The assistant proposed the initial scope and design, authored most implementation code, synthetic data, tests and documentation, and performed the recorded automated checks and browser inspections.

The candidate requested the project, directed revisions to the UI wording, requested preservation of the API Key option and addition of ChatGPT authorization, completed the account login/authorization, tried the interface, and requested further testing and explanations. These activities do not imply independent authorship or line-by-line review of the code. Independent candidate review of the implementation is not asserted here.

## Verification and attribution

- `demo`: deterministic workflow baseline using synthetic tools; no model or network is required.
- `chatgpt`: real authorization and model-selected tool calls were exercised. The extended synthetic suite initially passed 11/13 cases. Subsequent targeted retests produced a latest observed pass for each of the 13 cases; no final-build full-suite 13/13 run is claimed.
- `openai`: the original API Key mode remains available. Its protocol was tested with fake transport; a paid request with a real API Key has not been verified.

Evaluation inputs and assertions were authored by the assistant against the project's own synthetic fixtures. They are not an independently authored benchmark. The dated reports retain failures, fixes and retests. All backend data is simulated, and handoff records are local artifacts rather than tickets delivered to IT.

The candidate should describe only work and understanding they can personally substantiate in the interview. Further independent review, additional test cases and any candidate-authored changes should be recorded when actually performed.
