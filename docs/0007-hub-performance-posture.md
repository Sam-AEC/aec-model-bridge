# ADR 0007: Hub Performance Posture

**Status:** Accepted
**Date:** 2026-06-13

## Context
As the AEC Model Bridge expands to orchestrate multiple workflows (such as W3 Model Health) and connect to diverse tools, there is a risk of creeping latency. We need a definitive performance posture that establishes the runtime language and execution budget to ensure the hub remains highly responsive without drifting into unnecessary full-system rewrites.

## Decision
The hub stays **Python**. The Python ecosystem (MCP SDK, IfcOpenShell, specklepy, pyarrow/DuckDB) is our moat. Hub latency is typically dominated by host application responses and I/O, not interpreter overhead.

**Rules for Hot Paths:**
- Performance-critical operations must use native-backed libraries (e.g., IfcOpenShell's C++ core for geometry, pyarrow/DuckDB for the data lake, `orjson` for large payloads).
- A single module may be dropped to Rust/C++ as a Python extension (PyO3/nanobind) ONLY when a recorded profile demonstrates it dominates the workflow budget. Never attempt a whole-hub rewrite.
- Desktop switches (e.g., Revit, Navisworks) remain native by construction (C# in-process with the host).

## Budgets
| Metric | Target Budget | Enforcement |
| --- | --- | --- |
| Hub tool-dispatch overhead | < 10 ms | Perf smoke test (`pytest -m perf`) |
| W3 health audit on sample IFC | < 60 s | Continuous integration (upcoming) |

## Consequences
- Agents are explicitly forbidden from initiating whole-hub language rewrites (e.g., to Rust or Go).
- We maintain a `perf` test marker to assert our tool-dispatch budget programmatically.
- Any new dependency processing large payloads must have a native core.
