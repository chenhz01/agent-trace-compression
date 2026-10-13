# Changelog

## v0.1.1 (2026-10-13)

Round-2 revisions after first-draft self-review:

- Fixed 3 test expectations that mis-derived truncate arithmetic (6 events,
  keep=2 drops 2, not 1; keep=0 yields 1 marker event, not 3).
- **Mechanism fix found by tests:** replayability originally used set-based
  signature matching, which double-counted duplicate events (repeated tool
  results inflated truncate's score to 0.833). Replaced with multiset-
  intersection counting; the same case now scores 0.667 correctly.
- Suite raised 54 -> 60 cases (boundary arithmetic, marker semantics, step
  preservation, bench formula, elided-count replayability).
- Re-measured performance after the fix: 27.7 ms/bench on 2,000 events.

## v0.1.0 (2026-10-13)

First draft:

- JSONL trace loader (lenient: malformed lines skipped and counted).
- Three deterministic strategies: truncate (head/tail + elision marker),
  summarize (tool-output digests), structured (role/tool/args preserved,
  content digested).
- Metrics: compression ratio, multiset replayability, events dropped; bench
  compares all three.
- argparse CLI: `bench` and `compress` subcommands, `--json` output.
- self_test.py with scaffold-v2 four defenses; README, LICENSE, ALIGNMENT.
