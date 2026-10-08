# P4 research snapshot — 2026-10-08

This snapshot contains experimental code, plans, reports, statistical summaries, case cards and figures through v7 Tier C, including cost-control and OpenRouter transport work. Historical results remain historical; no new successful API sampling occurred during the cost-control resume because both requested models returned regional HTTP 403 errors.

`GIT_SNAPSHOT_20261008.json` lists committed evidence with SHA-256 hashes and raw-data exclusions. Full request ledgers, suffix executions, trajectory archives, local billing databases and API credentials remain on the original experiment filesystem. They are not included in Git. Files required for replay or resuming experiments must be restored from that filesystem; this Git snapshot is not a standalone raw-data backup.

Validation: `make check-all` passed; 25 cost-control/authentication regression tests passed. Selected files and the handoff archive were scanned for known local credentials and common token formats; no matches were found.
