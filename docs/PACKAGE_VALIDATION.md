# Submission package validation

Date: 2026-10-22 (Asia/Shanghai).

Checks were performed on a clean staged copy of the source with no runtime data, credentials, Git metadata or virtual environment copied in.

- 44/44 unit and HTTP integration tests passed using Python 3.9.6 and the optional OAuth validation dependencies from the local verification environment. Log: `evaluation/package-unit-results-2026-10-22.txt`.
- 19/19 deterministic scenarios passed using system Python. Report: `evaluation/package-demo-report-2026-10-22.json`.
- Default server startup succeeded using system Python with no optional OAuth dependencies; home page and configuration endpoint both returned HTTP 200 on a temporary loopback port. The original running app was not interrupted.
- Submission packaging excludes runtime databases, OAuth credentials, API keys, local virtual environments, Python caches and Git metadata. Only allowlisted source, docs, fixtures and evaluation materials are included.
- ZIP CRC and manifest SHA-256 verification passed after extracting the final archive.

No additional live model requests were made for this packaging check. The earlier real-model test scope and limitations remain in README and the dated evaluation report. This validates a local submission snapshot, not production readiness.
