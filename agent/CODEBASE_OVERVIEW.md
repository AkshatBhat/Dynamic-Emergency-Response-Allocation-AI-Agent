# RescueBench Codebase Overview

## What This File Does

`run_benchmark.py` is the complete evaluation harness for RescueBench — a humanitarian-logistics
benchmark that tests LLM agents on emergency dispatch across 20 JSON scenarios spanning 4 difficulty
tiers. It loads scenarios, runs agents, and produces metrics used directly in the paper.

---

## Section-by-Section Breakdown

### Section 1 — Benchmark File Paths
**Why it matters:** Defines the canonical paths to all 20 scenario files organized by tier directory.
This is the single source of truth for where scenarios live on disk. Changing tier names or directory
structure here would break the entire benchmark, so these constants are treated as fixed.

---

### Section 2 — JSON Scenario Loader (`load_scenario`)
**Why it matters:** The raw benchmark JSON uses field names and structures designed for human
readability (e.g., `unit_id`, `location_node`, `severity_weight`). The internal simulation uses
different keys. This section is the translation layer — it converts every scenario file into a
consistent internal dict that `WorldState` can consume. Without this, every agent would need to
parse JSON differently and bugs would be hard to isolate.

---

### Section 3 — WorldState
**Why it matters:** This is the simulation engine — the ground truth of what is happening in the
city at any point in time. Every agent, regardless of architecture, reads from and writes to the
same `WorldState`. Key capabilities that directly affect benchmark scores:

- **Vehicle-type-aware Dijkstra** — some roads only allow ambulances or light vehicles. An agent
  that ignores this will attempt illegal routes, fail dispatches, and score lower.
- **Multi-dispatch tracking** (`cover_incident`) — incidents can require multiple capabilities
  (e.g., fire suppression AND traffic control). The world tracks partial coverage so that multiple
  vehicles can contribute to one incident sequentially. This is what makes Tier 2 hard.
- **Dynamic trigger system** (`advance_clock`) — Tier 4 scenarios include infrastructure failures
  that fire at specific times (e.g., a bridge collapses at t=15). The simulation clock advances on
  every vehicle arrival, firing any triggers that have become due. This is what makes Tier 4 require
  replanning.

---

### Section 4 — WorldTool
**Why it matters:** LLM-based agents (ReAct, zero-shot) cannot be given raw Python objects — they
interact with the simulation through structured function calls. `WorldTool` is the safe, read/write
interface that exposes exactly what an agent needs: query map state, query vehicles, query incidents,
compute routes, and dispatch vehicles. It also handles the hospital routing logic for patient
transport. Keeping this separate from `WorldState` ensures agents cannot accidentally corrupt
internal state in ways the simulation doesn't expect.

---

### Section 5 — ValidatorTool
**Why it matters:** This is the safety layer that enforces physical and logical constraints before
any dispatch mutates world state. It checks: does the vehicle exist, is it available, does it
actually contribute a needed capability, can it physically reach the incident, and is the hospital
valid? The `violation_count` it maintains is a direct benchmark metric — it measures how often an
agent tries to do something illegal. The ablation study (ReAct vs. Ablated ReAct) exists entirely
to show what happens to this number when the validator is removed.

---

### Section 6 — `compute_metrics()`
**Why it matters:** This function produces the four numbers that appear in the paper's results table.
Each metric captures a different dimension of agent performance:

- **PWRS** — did the agent resolve the highest-priority incidents before their deadlines? Binary
  per incident, weighted by severity.
- **Cap-PWRS** — did the agent make progress even on incidents it couldn't fully resolve? Gives
  partial credit for partial capability coverage, with a linear time penalty for late resolution.
  This distinguishes agents that partially help from agents that do nothing.
- **Resolution Rate** — simple count: what fraction of incidents were resolved at all?
- **Deadline Adherence** — of the incidents that were resolved, how many were on time?

Without consistent, well-defined metrics computed from the same world state, cross-mode comparison
would be meaningless.

---

### Section 7 — Deterministic Planner (`run_deterministic`)
**Why it matters:** This is the non-LLM baseline every other mode is compared against. It uses a
simple greedy algorithm: rank incidents by severity then deadline, dispatch the nearest capable
vehicle, repeat. Because it requires no API calls it runs instantly and deterministically — the same
inputs always produce the same outputs. This makes it the reliability floor: any LLM-based agent
that scores below the deterministic baseline is not adding value over a simple rule engine.

Also contains `_nearest_hospital()` — a shared helper used by both deterministic and AgentKit to
find the closest open hospital for patient transport.

---

### Section 8 — ReAct Agent (`run_react` / ablated)
**Why it matters:** This is the primary LLM architecture being compared against AgentKit. The ReAct
loop gives Claude full tool access — it observes the world, reasons about what to do, and acts, in
a multi-turn loop. The two sub-modes exist for the ablation study:

- **Full ReAct** — validator runs before every dispatch; illegal actions are blocked and the model
  sees the error message and must self-correct.
- **Ablated ReAct** — validator is bypassed; the model can dispatch illegally and the simulation
  will still execute the action. The violation count spike isolates exactly how much work the
  validator is doing.

`TOOL_DEFINITIONS` and `SYSTEM_PROMPT` defined here are fixed — changing them would make results
incomparable across runs.

---

### Section 9 — Zero-Shot Baseline (`run_zero_shot`)
**Why it matters:** The weakest LLM baseline. One prompt, one response, no feedback loop. The model
must plan all dispatches upfront with no ability to observe intermediate results or correct mistakes.
It establishes the floor for LLM-based approaches. The violation counting here is deliberately
decoupled from the validator — violations are counted by inspecting capability contribution directly,
so the count is deterministic given the same LLM response and is not inflated by validator bookkeeping.

---

### Section 9B — AgentKit Agent (`RescueAgent` / `run_agentkit`)
**Why it matters:** This is the novel contribution of the paper. The core architectural claim is
that delegating math to code and reserving the LLM for judgment-only decisions produces a more
reliable agent than a pure ReAct loop. Concretely:

- **Routing, capacity, and capability matching** are pure Python — deterministic, fast, zero tokens.
- **Ethical tie-breaking** (Tier 3 only) is the one case where two incidents are truly equivalent
  on all measurable dimensions and a human-judgment call is justified.
- **Proactive trigger polling** in `observe()` means the agent detects infrastructure failures every
  cycle, not just when a dispatch happens to arrive — this is critical for Tier 4 correctness.
- **Memory log** tracks failed dispatches so the agent can avoid repeating the same mistakes within
  a run.

The separation of concerns (observe → plan → act → replan) also makes the agent's behavior
interpretable and debuggable in a way a raw ReAct transcript is not.

---

### Section 10 — Benchmark Runner
**Why it matters:** Orchestrates everything — iterates over all mode × tier × scenario × run
combinations, catches errors so one bad scenario doesn't abort the whole run, aggregates per-scenario
results into per-tier means, and writes `benchmark_results.json`. The `print_results_table()`
function produces the exact table format used in the paper. Keeping all modes in one runner ensures
they are evaluated on identical scenarios under identical conditions.

---

### Section 11 — CLI Entry Point
**Why it matters:** Makes the benchmark reproducible by anyone with one command. The `--mode`,
`--tier`, `--runs`, `--api-key`, and `--model` flags allow full control over what gets evaluated
without touching source code. The `"all"` shorthand for both mode and tier is what's used for the
final paper numbers.

---

## Tier Difficulty Summary

| Tier | What makes it hard | Key mechanism tested |
|------|--------------------|--------------------|
| 1 | Single-capability incidents, clear roads | Basic routing and priority ordering |
| 2 | Multi-capability incidents, road restrictions | Multi-dispatch coordination, vehicle type constraints |
| 3 | Ethical ties (identical severity + deadline) | Judgment under ambiguity |
| 4 | Infrastructure failures mid-mission | Dynamic replanning |

---

## Data Flow Summary

```
benchmark JSON files
        ↓
  load_scenario()          ← Section 2
        ↓
   WorldState              ← Section 3  (ground truth)
   WorldTool               ← Section 4  (agent interface)
   ValidatorTool           ← Section 5  (safety layer)
        ↓
  run_[mode]()             ← Sections 7–9B
        ↓
  compute_metrics()        ← Section 6
        ↓
  aggregate + print        ← Section 10
        ↓
benchmark_results.json
```
