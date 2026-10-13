# agent-trace-compression

Compare three deterministic ways to shrink an agent trace and see which keeps it replayable. Given a JSONL event log (role/content/optional tool+args), it runs truncate, summarize, and structured compression, then reports each strategy's compression ratio against replayability — how much decision-critical structure survives. Pure Python, standard library only, no LLM in the loop.

## Problem

Agent traces get long: tool outputs alone can be megabytes. Every team compresses them somehow — cut the middle, digest the outputs, keep only the skeleton — but the trade-off is never written down. Truncation silently deletes the steps that explain a decision; aggressive digesting keeps step count but loses the arguments that made each step different. Without a shared metric, "compressed trace" means whatever the last refactor left behind.

## How it works

1. **Load** the trace as JSONL events; malformed lines are skipped and counted, never fatal.
2. **Strategies** (all deterministic, rule-based):
   - `truncate` — keep the first and last *keep* events, insert one `[N events elided]` marker.
   - `summarize` — keep every event; replace tool-result content with a 48-char digest.
   - `structured` — keep every event's role/tool/args; digest all content.
3. **Metrics** per strategy: `compression_ratio` (chars in / chars out), `replayability` (fraction of original event signatures that survive, counted with multiplicity), and `events_dropped`.
4. **Compare** — the bench prints all three side by side so the ratio-vs-replayability trade-off is explicit.

## Quickstart

```bash
# ~1 min total
python agent_trace_compression.py bench --trace trace.jsonl
python agent_trace_compression.py bench --trace trace.jsonl --json
python agent_trace_compression.py compress --trace trace.jsonl --strategy structured
```

`bench` runs all three strategies and prints the comparison table.

## Why not X

- **ProfRandom92/comptext-sparkctl** — a Rust CLI packaging synthetic evidence bundles with deterministic replay, context rendering, and review notebooks. It builds a reproducible *artifact format* (`.spkg`); it does not benchmark alternative compression strategies against each other on a replayability metric.
- **RenchuSong/PRESS** — compresses GPS trajectories in road networks (VLDB 2015); a map-matching research service in C++/Go, not an agent-event replay metric.
- **LLM-based trace summarizers** — high-quality prose, but non-deterministic: the same trace summarizes differently on every run, so benchmarks are not reproducible and the summary may drop a critical argument. This tool is deliberately LLM-free.
- **zlib / gzip** — byte-perfect and lossless, but the result is neither human-readable nor selectively replayable; the question here is what to *keep*, not how to *pack*.

## How this differs from comptext-sparkctl

The closest anchor, `ProfRandom92/comptext-sparkctl`, is a local Rust CLI whose workflow — per its README — goes "schema check → package compress → .spkg Evidence-Paket → verify / replay / adversarial", i.e. it compresses a trace *into one canonical evidence package* and proves the package's integrity. That answers "can I trust this bundle?". This repo answers a different question: *which lossy strategy should I choose?* It runs three competing strategies over the same trace and scores each on compression ratio vs replayability, exposing the trade-off rather than hiding it inside one format. Sparkctl is a packaging layer with a single canonical transform; this is a comparative benchmark harness with three interchangeable transforms.

## Performance

[Measured] on Windows 10 Pro, Python 3.11, 2026-10-13. A 2,000-event trace (alternating assistant steps and ~800-char tool outputs) benches all three strategies in **27.7 ms per run** (0.55 s for 20 runs). Reproduce:

```bash
python -c "import time,agent_trace_compression as m; evs=[{'role':'assistant','content':'step %d'%i,'tool':'t%d'%(i%5),'args':{'i':i}} if i%2 else {'role':'tool','content':'out'*200,'tool':None,'args':None} for i in range(2000)]; t0=time.perf_counter(); [m.bench(evs) for _ in range(20)]; print((time.perf_counter()-t0)*50)"
```

## Minimal Fallback

No Python? Load the JSONL in any editor, count lines as `events_in`, and eyeball two numbers: (1) what fraction of lines keep their `tool` field after your compression; (2) whether the step order is intact. That is a manual version of the replayability metric. A spreadsheet with one row per event and a "kept?" column reproduces the same score.

## Design Trade-offs

- **Rule-based digests over LLM summaries** — deterministic, reproducible, and safe to run on untrusted traces; trades away readability of the digest.
- **Replayability counts signatures, not content** — tool name + args decide "which step was this"; content is explicitly excluded so strategies that digest content are not over-penalized.
- **Multiset matching over positional matching** — avoids double-counting duplicate events, at the cost of not detecting reordering.
- **Three fixed strategies over a plugin system** — the comparison only means something if the strategies are fixed and versioned.

## Limits & Second-order Effects

- Replayability 1.0 does not mean the trace is *useful* — structured mode preserves structure while digesting all prose, including the reasoning.
- The elision marker in truncate mode can confuse downstream parsers that expect only real events.
- Teams may optimize for the metric: keeping empty-but-signed tool events inflates replayability without adding information.
- Compression ratio uses character counts, so multibyte-heavy traces look smaller than their byte cost.

## FAQ

**When NOT to use this?**
When you need a lossless archive (use gzip) or a human-readable narrative of what the agent did (use an LLM summarizer and accept non-determinism). This tool is for choosing a *lossy but structured* representation.

**Can I add my own strategy?**
Yes — it is one function returning (events, dropped); the metric functions are independent of strategy choice.

**Why is truncate's replayability not zero even with drops?**
Because only the elided middle is lost; head and tail events keep their full signatures.

**Does it ever call a model?**
No. Zero network, zero model calls — the same trace always produces the same report.

## Core Assumptions

- [A1] Tool name + arguments are the decision-critical part of a trace event; content is secondary for replay purposes. Confidence: Medium — some debugging needs full output text.
- [A2] Deterministic compression is worth more than prettier LLM summaries in evaluation pipelines. Confidence: High.
- [A3] Traces are JSONL events with role/content/optional tool+args. Confidence: High for OpenAI-style harnesses; Medium for bespoke formats.
- [A4] Compression ratio (chars) plus replayability (signatures) jointly characterize "good" compression. Confidence: Medium — utility is task-dependent.

Confidence in the benchmark mechanism: High. As of 2026-10-13.

## License

MIT — see [LICENSE](LICENSE). Contact: hcac4735@agent.qq.com

---

Part of the [zhengming-toolbox](https://github.com/chenhz01/zhengming-toolbox) — 105 purpose-built AI-engineering tools across neglected niches.

Related tools: [memory-expiry-policy](https://github.com/chenhz01/memory-expiry-policy) · [instruction-conflict-detector](https://github.com/chenhz01/instruction-conflict-detector) · [llm-error-code-spec](https://github.com/chenhz01/llm-error-code-spec)
