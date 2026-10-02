# Harness Fusion maintenance instructions

- Start with HANDOFF.md, README.md, and docs/ARCHITECTURE.md.
- Preserve fail-closed completion: no checks, malformed/stale review, scope violation, or exhausted budgets cannot be success.
- Keep Planner and Evaluator read-only; harness-owned state must not be model-owned.
- Keep process execution shell-free and never add permission-bypass flags.
- Add targeted regression tests for changes to completion gates, process lifecycle, scope detection, and resume.
- Run `python -m unittest discover -s tests -v` after functional changes.
- Do not claim actual provider/Windows/CI validation unless it has been executed.
- Do not publish, push, deploy, or change the original harness-v2 repository unless the user asks.
- Explain outcomes and limitations in Korean. No automatic subagent delegation.
