# Agent Upgrade Tracker

## Objective

Upgrade the modular `agentkit` from the old near-deterministic monolith into a
hybrid planning agent with:

- a stronger simulator
- explicit candidate evaluation
- deterministic feasibility and execution
- optional LLM arbitration at the policy layer

This file reflects the current modular implementation status.

## Current Implementation

### 1. Simulator and world model

Relevant files:

- [world.py](/Users/akshat/Data/UIUC/Spring%202026/Courses/CS%20498%20AI%20Agents%20in%20the%20Wild/Project/Dynamic-Emergency-Response-Allocation-AI-Agent/rescuebench_agent/world.py:1)
- [tools.py](/Users/akshat/Data/UIUC/Spring%202026/Courses/CS%20498%20AI%20Agents%20in%20the%20Wild/Project/Dynamic-Emergency-Response-Allocation-AI-Agent/rescuebench_agent/tools.py:1)
- [scenarios.py](/Users/akshat/Data/UIUC/Spring%202026/Courses/CS%20498%20AI%20Agents%20in%20the%20Wild/Project/Dynamic-Emergency-Response-Allocation-AI-Agent/rescuebench_agent/scenarios.py:1)

What is now implemented:

- concurrent mission scheduling instead of serialized per-dispatch clock jumps
- event-driven time advancement
- reusable vehicles with mission phases
- dynamic rerouting after trigger events
- generalized quantity handling for:
  - patient transport
  - bulk supply
  - medical capacity style requirements
- hospital reservation and admission tracking
- fuel validation and in-mission fuel consumption
- route timing with vehicle `speed_multiplier`
- committed-work accounting to avoid duplicate dispatches for already-covered or
  already-committed work

### 2. Modular hybrid agent

Relevant files:

- [agents/rescue_agent.py](/Users/akshat/Data/UIUC/Spring%202026/Courses/CS%20498%20AI%20Agents%20in%20the%20Wild/Project/Dynamic-Emergency-Response-Allocation-AI-Agent/rescuebench_agent/agents/rescue_agent.py:1)
- [agents/planning.py](/Users/akshat/Data/UIUC/Spring%202026/Courses/CS%20498%20AI%20Agents%20in%20the%20Wild/Project/Dynamic-Emergency-Response-Allocation-AI-Agent/rescuebench_agent/agents/planning.py:1)

What is now implemented:

- feasible next-dispatch candidate generation
- adaptive same-time dispatch bundle generation
- cloned-world rollout projection for bundle evaluation
- adaptive search depth and bundle size based on open incidents, available
  vehicles, quantity-heavy incidents, and pending triggers
- scoring on projected:
  - PWRS
  - Cap-PWRS
  - resolution rate
  - deadline adherence
- completion-time-aware scoring for transport missions
- scarcity-aware and future-option-aware heuristics
- disruption-risk-aware bundle scoring against pending trigger edges
- unresolved-risk scoring for projected post-bundle states
- incident-spread reward and over-concentration penalty
- optional LLM selection among shortlisted bundles
- conservative LLM override gating so the LLM cannot replace a clearly better
  heuristic plan with a materially worse one
- memory entries for blocked states, LLM choices, and dynamic alerts

What the LLM currently does:

- ethical tie-breaking when enabled
- bundle arbitration when feasible plans are close or dynamic context makes the
  tradeoff ambiguous

What the LLM does not currently do:

- raw routing
- direct low-level tool micromanagement in the main `agentkit` loop
- open-ended action invention outside the validated shortlist

### 3. Regression and generalization coverage

Relevant file:

- [tests/test_agent_generalization.py](/Users/akshat/Data/UIUC/Spring%202026/Courses/CS%20498%20AI%20Agents%20in%20the%20Wild/Project/Dynamic-Emergency-Response-Allocation-AI-Agent/rescuebench_agent/tests/test_agent_generalization.py:1)

Coverage added:

- custom quantity capability not named in the benchmark
- custom scarce-vehicle planning case
- custom dynamic diversion case

Purpose:

- verify the agent is not keyed to benchmark scenario IDs or fixed benchmark
  capability names

## Latest Validated No-API Regression Snapshot

Source:

- [regression_all_tiers_after_policy.txt](/Users/akshat/Data/UIUC/Spring%202026/Courses/CS%20498%20AI%20Agents%20in%20the%20Wild/Project/Dynamic-Emergency-Response-Allocation-AI-Agent/rescuebench_agent/regression_all_tiers_after_policy.txt:1)

### Deterministic

- Tier 1: `pwrs=0.745`, `cap_pwrs=0.931`
- Tier 2: `pwrs=0.400`, `cap_pwrs=0.903`
- Tier 3: `pwrs=0.719`, `cap_pwrs=0.820`
- Tier 4: `pwrs=0.506`, `cap_pwrs=0.797`

### Current modular AgentKit

- Tier 1: `pwrs=0.745`, `cap_pwrs=0.931`
- Tier 2: `pwrs=0.400`, `cap_pwrs=0.903`
- Tier 3: `pwrs=0.807`, `cap_pwrs=0.864`
- Tier 4: `pwrs=0.506`, `cap_pwrs=0.797`

Interpretation:

- parity with deterministic on Tiers 1, 2, and 4
- meaningful policy gain on Tier 3
- no benchmark-ID hardcoding detected in the synthetic tests

## Current Limitations

- The simulator still reroutes from the last reached node, not a continuous
  along-edge position.
- The current `agentkit` now does bundle selection, but only over a small
  deterministic shortlist rather than a larger search space or open-ended
  tool-using loop.
- The LLM role is stronger than in the monolith, but it still arbitrates over
  structured alternatives instead of driving the full control loop.
- Under the current benchmark and simulator, Tiers 1, 2, and 4 still leave
  limited headroom over the deterministic baseline, so the strongest validated
  gain remains Tier 3.

## Practical Conclusion

The current modular agent is stable enough to report as:

- a substantially improved simulation and evaluation environment relative to
  the monolith
- a hybrid planning baseline with deterministic grounding
- a modest but real policy improvement over the original monolithic
  `agentkit`

If more engineering time is available later, the next meaningful upgrade is
larger-search bundle planning, contingency-aware lookahead over multiple future
events, or a stronger multi-step LLM critique loop on top of the current bundle
selector.
