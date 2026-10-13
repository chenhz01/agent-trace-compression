#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agent-trace-compression — replayability benchmark for agent trace compression.

Loads an agent trace (JSONL events: role/content/optional tool+args), applies
three deterministic compression strategies — truncate, summarize, structured —
and compares them on compression ratio vs replayability (how much of the
decision-critical structure survives). Rule-based only: no LLM, no network.
"""
import argparse
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
except Exception:
    pass

VERSION = "0.1.1"
STRATEGIES = ("truncate", "summarize", "structured")
DIGEST_HEAD = 48


class TraceError(Exception):
    """Input problem that maps to exit code 2."""


def load_trace(path):
    """Load JSONL trace. Returns (events, skipped). Lenient: bad lines skipped."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_lines = f.read().splitlines()
    except OSError as e:
        raise TraceError("cannot read trace file: %s" % e)
    events, skipped = [], 0
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        if isinstance(obj, dict):
            events.append({
                "role": str(obj.get("role", "unknown")),
                "content": str(obj.get("content", "")),
                "tool": obj.get("tool"),
                "args": obj.get("args"),
            })
        else:
            skipped += 1
    return events, skipped


def _digest(text):
    text = text.strip()
    if len(text) <= DIGEST_HEAD:
        return text
    return text[:DIGEST_HEAD] + "...(%d chars elided)" % len(text)


def _charlen(events):
    return sum(len(e["role"]) + len(e["content"]) for e in events)


def strategy_truncate(events, keep=2):
    """Keep first `keep` and last `keep` events; mark the middle elided."""
    if keep < 0:
        raise TraceError("keep must be >= 0")
    n = len(events)
    if n <= 2 * keep:
        return [dict(e) for e in events], 0
    head = [dict(e) for e in events[:keep]]
    tail = [dict(e) for e in events[n - keep:]]
    dropped = n - 2 * keep
    marker = {"role": "system", "content": "[%d events elided]" % dropped,
              "tool": None, "args": None}
    return head + [marker] + tail, dropped


def strategy_summarize(events):
    """Keep every step; collapse tool-result contents into digests."""
    out = []
    for e in events:
        c = dict(e)
        if e["role"] == "tool":
            c["content"] = _digest(e["content"])
        out.append(c)
    return out, 0


def strategy_structured(events):
    """Keep role/tool/args for every event; replace content with a digest."""
    out = []
    for e in events:
        c = {"role": e["role"], "tool": e["tool"], "args": e["args"],
             "content": _digest(e["content"])}
        out.append(c)
    return out, 0


def replayability(original, compressed):
    """Fraction of original events whose (role, tool, args) signature survives.
    Counted per signature with multiplicity (multiset intersection), so a
    duplicated signature cannot be double-counted beyond what the compressed
    trace actually retains."""
    def sigs(evs):
        return [(e["role"], e["tool"], json.dumps(e.get("args"), sort_keys=True,
                                                  ensure_ascii=False)) for e in evs]
    orig, comp = sigs(original), sigs(compressed)
    if not orig:
        return 1.0
    kept = 0
    pool = {}
    for s in comp:
        pool[s] = pool.get(s, 0) + 1
    for s in orig:
        if pool.get(s, 0) > 0:
            kept += 1
            pool[s] -= 1
    return round(kept / len(orig), 3)


def bench(events, keep=2):
    """Run all strategies. Returns report dict."""
    orig_chars = _charlen(events)
    rows = []
    for name in STRATEGIES:
        if name == "truncate":
            comp, dropped = strategy_truncate(events, keep=keep)
        elif name == "summarize":
            comp, dropped = strategy_summarize(events)
        else:
            comp, dropped = strategy_structured(events)
        comp_chars = _charlen(comp)
        ratio = round(orig_chars / comp_chars, 3) if comp_chars else 0.0
        rows.append({
            "strategy": name,
            "events_out": len(comp),
            "chars_in": orig_chars,
            "chars_out": comp_chars,
            "compression_ratio": ratio,
            "replayability": replayability(events, comp),
            "events_dropped": dropped,
        })
    return {"schema": "agent-trace-compression/v1",
            "events_in": len(events), "keep": keep, "results": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="agent-trace-compression",
        description="Benchmark truncate/summarize/structured compression on an agent trace (deterministic, offline).")
    parser.add_argument("--version", action="version", version="%(prog)s " + VERSION)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("bench", help="run all strategies and compare")
    p.add_argument("--trace", required=True, help="trace file, JSONL events")
    p.add_argument("--keep", type=int, default=2, help="truncate: events kept on each side")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")

    p2 = sub.add_parser("compress", help="apply one strategy and print the compressed trace")
    p2.add_argument("--trace", required=True)
    p2.add_argument("--strategy", choices=STRATEGIES, required=True)
    p2.add_argument("--keep", type=int, default=2)

    args = parser.parse_args(argv)
    if args.cmd not in ("bench", "compress"):
        parser.print_usage(sys.stderr)
        return 2
    try:
        events, skipped = load_trace(args.trace)
        if args.cmd == "bench":
            report = bench(events, keep=args.keep)
            report["skipped_lines"] = skipped
        else:
            fn = {"truncate": lambda: strategy_truncate(events, args.keep),
                  "summarize": lambda: strategy_summarize(events),
                  "structured": lambda: strategy_structured(events)}[args.strategy]
            comp, _ = fn()
            report = {"skipped_lines": skipped, "events_out": len(comp),
                      "events": comp}
    except TraceError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2

    if args.cmd == "bench" and not args.json:
        print("agent-trace-compression bench  (%d events in, keep=%d)"
              % (report["events_in"], report["keep"]))
        print("  %-11s %9s %9s %9s %9s" % ("strategy", "chars_out", "ratio", "replay", "dropped"))
        for r in report["results"]:
            print("  %-11s %9d %9.3f %9.3f %9d"
                  % (r["strategy"], r["chars_out"], r["compression_ratio"],
                     r["replayability"], r["events_dropped"]))
        if skipped:
            print("  note: %d malformed line(s) skipped" % skipped)
    else:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
