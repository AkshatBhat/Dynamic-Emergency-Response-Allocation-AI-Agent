# RescueBench Modular Refactor Notes

## Goal

This folder is a clean refactor of the original monolithic implementation in
`agent/AgentImplementation.py`. The old file is preserved unchanged so the
course submission history remains intact. The new package exists to make the
agent code reviewable, extensible, and safer to evolve.

Note:

- This document is primarily about the modularization rationale.
- Some "next phase" items mentioned below have since been implemented in the
  modular package.
- For the current agent/world-model status, use
  [AGENT_UPGRADE_TRACKER.md](/Users/akshat/Data/UIUC/Spring%202026/Courses/CS%20498%20AI%20Agents%20in%20the%20Wild/Project/Dynamic-Emergency-Response-Allocation-AI-Agent/rescuebench_agent/AGENT_UPGRADE_TRACKER.md:1).

## File-by-File Justification

### `__init__.py`

- Keeps the package importable.
- Exposes the highest-level runner functions only.
- Avoids leaking the entire internal implementation surface.

### `__main__.py`

- Adds a package entrypoint so the new code can be run with
  `python3 -m rescuebench_agent`.
- Keeps the CLI bootstrapping out of the library modules.

### `paths.py`

- Centralizes benchmark path resolution.
- Fixes one structural issue in the old file: the old runner assumed benchmark
  JSON lived under `agent/benchmark`, while the repo actually has a top-level
  `benchmark/` directory.

### `scenarios.py`

- Isolates JSON-to-internal-state translation.
- Makes it easier to change scenario schema later without touching the agent,
  tools, metrics, and CLI at the same time.

### `world.py`

- Separates the simulation engine from the planning logic.
- This is the correct place for future upgrades such as:
  - true concurrent dispatch
  - multi-ambulance patient aggregation
  - vehicle release / return-to-service logic
  - hospital occupancy updates
  - fuel and speed effects

### `tools.py`

- Keeps agent actions and validation separate from the world model.
- Preserves the old benchmark semantics while making dispatch and validation
  independently testable.
- This separation is necessary if we later add higher-level tools like
  `dispatch_bundle` or `score_candidate_plans`.

### `metrics.py`

- Decouples scoring from execution.
- Makes metric changes auditable, which matters because benchmark results are
  only meaningful if metric definitions are easy to inspect.

### `routing.py`

- Extracts shared routing helpers instead of leaving them as hidden functions in
  one large script.
- Prevents `nearest_hospital` from being duplicated between planners.

### `prompts.py`

- Groups prompt and tool schema definitions in one place.
- Makes the LLM-visible contract explicit.
- This is important because the next iteration of the agent should likely add:
  - higher-level planning prompts
  - candidate-plan scoring prompts
  - reflection prompts
  - structured plan-selection outputs

### `modes/deterministic.py`

- Keeps the greedy baseline isolated.
- This matters because the current `agentkit` implementation is too close to
  the deterministic baseline; separating the baseline clearly will make future
  comparisons honest.

### `modes/react.py`

- Keeps the tool-calling ReAct implementation separate from the deterministic
  baseline and from `agentkit`.
- This is the current path where LLM tool use is actually happening.
- It is now easier to compare pure ReAct against a future hybrid agent.

### `modes/zero_shot.py`

- Keeps the weakest baseline isolated.
- This helps preserve a clear experimental story: zero-shot vs ReAct vs
  deterministic vs future hybrid.

### `agents/rescue_agent.py`

- Gives the custom agent its own file instead of burying it inside the runner.
- This is the main file meant to evolve next.
- Right now it preserves the old behavior, which is mostly deterministic plus an
  LLM ethical tie-breaker. That is intentional for parity during refactor.
- This module is the right place to replace the current greedy policy with:
  - candidate-plan generation
  - lookahead planning
  - reflection memory
  - LLM-based plan selection over feasible actions

### `agents/planning.py`

- Added in the second phase of the refactor.
- Defines the structured `DispatchCandidate` object used by the upgraded
  planning loop.
- This keeps the new planner state explicit instead of passing around ad hoc
  dicts or tuples.

### `benchmark.py`

- Separates orchestration from implementation details.
- Makes it possible to benchmark new agents without touching core simulation
  code.

### `cli.py`

- Moves argument parsing and output persistence out of the agent logic.
- Also loads `.env` here, which avoids side effects when library modules are
  merely imported.

## Safe Improvements Included in the Refactor

### Python 3.9 compatibility

The original file uses `str | None` annotations without
`from __future__ import annotations`, which causes runtime failures under the
default local `python3` (3.9). Every new module includes the future import so
the new package runs cleanly on Python 3.9.

### Correct benchmark path resolution

The new package resolves benchmark files from the repository root instead of
assuming they live under `agent/`.

## What This Refactor Intentionally Does Not Change Yet

To keep the refactor reviewable, the package preserves the current benchmark
behavior before changing agent policy. That means the following limitations are
still present by design in this first pass:

- `RescueAgent` is still mostly deterministic.
- The `memory` log is still observational, not yet used as reflective planning
  context.
- Dispatch remains serialized rather than truly concurrent.
- Ambulance capacity is still treated per-vehicle instead of as a composable
  multi-unit transport resource.
- Hospital occupancy is validated but not meaningfully updated after dispatch.

## Recommended Next Refactor Phase

The next phase should target `agents/rescue_agent.py`, `tools.py`, and
`world.py` together.

### Priority 1: fix benchmark fidelity

- Support multi-vehicle patient transport.
- Add concurrent dispatch semantics.
- Update hospital occupancy and vehicle reuse.

### Priority 2: make the LLM matter at the policy level

- Generate top-k feasible candidate dispatch bundles in code.
- Dry-run or score those candidates with deterministic features.
- Ask the LLM to choose among candidates rather than asking it to do raw routing
  math.

### Priority 3: add explicit reflection memory

- After failures or replans, store short structured reflections.
- Feed the last few reflections back into the next planning prompt.
- This aligns with the motivation from Reflexion-style agent designs.

### Priority 4: introduce stronger planning tools

- `get_feasible_actions`
- `score_candidate_plans`
- `dispatch_bundle`
- `summarize_failure_reasons`

Those tools would let the LLM reason at the right abstraction level instead of
micromanaging every dispatch call.

## Phase 2 Status

The second-phase agent upgrade has now started inside the modular package.

What changed:

- The old nearest-feasible-unit policy in `agents/rescue_agent.py` was replaced
  with candidate generation over all feasible next dispatches.
- Each candidate is simulated on a cloned `WorldState`.
- A short deterministic rollout estimates downstream benchmark impact before the
  action is executed in the real world.
- The agent now scores candidates using projected PWRS, projected Cap-PWRS, and
  deadline slack rather than only immediate local greediness.
- The LLM is now used for next-action arbitration among close candidates, not
  only for ethical tie-breaking.

What this means:

- The modular `agentkit` path is no longer behaviorally identical to the old
  monolith, by design.
- Deterministic feasibility remains in code, but action choice is now a hybrid
  planning process instead of a one-step greedy rule.
