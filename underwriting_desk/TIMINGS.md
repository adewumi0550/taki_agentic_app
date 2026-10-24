# Measured runs

Machine: MacBook (darwin), `gemini-2.5-flash` on Vertex AI, us-central1.
MCP server local on :8080. Measured 2026-10-23 on `conflict_file`.

| | concurrent | sequential |
|---|---|---|
| wall clock | **18.6s** | **36.6s** |
| specialists start at | 5.87 / 5.98 / 6.11 / 6.62s | 5.21 / 10.61 / 14.88 / 20.75s |
| reconciler starts | 18.6s | 36.6s |
| recommendation | DECLINE | DECLINE |

**Speedup: 1.97x, not 4x.**

Two reasons, and both are worth saying out loud:

1. You wait for the *slowest* specialist, not the average one.
2. The reconciler is serial and it is the single most expensive step --
   roughly 12s of the 18.6s concurrent run. Amdahl gets a vote.

Four agents cost roughly four times the tokens and bought a little under
two times the wall clock. On this workload that is worth it, because a
human is waiting. On a batch job it would not be.
