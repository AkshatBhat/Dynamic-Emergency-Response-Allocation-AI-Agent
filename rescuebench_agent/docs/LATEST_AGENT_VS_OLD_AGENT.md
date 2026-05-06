# Latest Agent vs Old Agent

## Old agent in the monolith

The original `agentkit` in
`archived_legacy_not_current/legacy_agent/agent/AgentImplementation.py` was mostly a
deterministic greedy dispatcher.

What it mainly did:

- sort incidents by severity and deadline
- pick the nearest feasible vehicle
- rely on deterministic routing and validation
- use the LLM only in a narrow ethical tie-break situation

Practical implication:

- it behaved very similarly to the deterministic baseline
- the LLM was not part of routine planning

## Latest modular agent

The current modular `agentkit` in
[agents/rescue_agent.py](../agents/rescue_agent.py)
is a hybrid planner.

What it now does:

- generates feasible next-dispatch candidates
- simulates candidates on cloned world states
- scores candidates on projected benchmark outcomes
- accounts for mission completion time, not only incident arrival time
- penalizes wasting scarce vehicles that may be needed elsewhere
- can use the LLM to arbitrate among shortlisted candidates

What still remains deterministic:

- scenario loading
- routing
- feasibility checks
- world-state evolution
- dispatch execution

## World model difference

The modular package also runs on a much stronger simulator than the monolith.

New simulator behavior includes:

- concurrent missions
- event-driven time advancement
- reusable vehicles
- dynamic rerouting after alerts
- generalized quantity handling
- hospital reservation and admission tracking
- fuel and speed effects

This means the latest agent is being evaluated in a more realistic environment
than the old one.

## Bottom line

The old agent was best described as:

- deterministic policy with a tiny amount of LLM use

The latest modular agent is better described as:

- deterministic execution and simulation with hybrid candidate-based planning
  and optional LLM arbitration

So the latest version is not a pure LLM agent, but it is materially more
agentic and more defensible than the original monolithic `agentkit`.
