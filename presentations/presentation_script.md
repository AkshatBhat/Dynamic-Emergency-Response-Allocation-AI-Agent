# Presentation Script
### Dynamic Emergency Response Allocation Agent
### Target: 10 minutes | ~130–150 words per minute

---

## Slide 1 — Introduction & Motivation
**⏱ ~1.5 minutes**

Imagine you're coordinating emergency response during a disaster. You have ambulances, fire engines, police units, and supply trucks — and you need to dispatch them across a city in real time, under tight deadlines, with roads closing as you go.

The natural instinct is to ask an LLM to handle it. LLMs are great at reading unstructured text, reasoning about priorities, and communicating decisions. But the moment you need them to do the actual math — calculate travel times, respect vehicle capacities, track which hospital still has beds — they break down. They hallucinate routes. They dispatch vehicles that don't have the right equipment. They lose track of what's already been committed.

So the question we set out to answer is: how do you build an agent that gets the best of both worlds — the semantic reasoning of an LLM *and* the mathematical precision of deterministic code?

Our answer is a hybrid architecture called AgentKit, evaluated on a benchmark we built called RescueBench. We'll walk you through both today.

---

## Slide 2 — Benchmark: Domain & Design
**⏱ ~1 minute**

RescueBench lives in the domain of humanitarian logistics and emergency resource allocation. It's a set of 20 scenarios, all built on a shared 16-node city map with a heterogeneous fleet of four vehicle types.

What makes the benchmark trustworthy is how we built it. We manually authored the base city graph to guarantee that every scenario is mathematically solvable. We then used a Gemini-powered pipeline to mutate that base into 20 distinct scenarios — generating incidents, computing tight but feasible deadlines using Dijkstra's algorithm, and injecting dynamic events like bridge collapses and road floods on a simulation clock.

The key design decision is that grading is entirely deterministic. There's no LLM-as-a-judge. Success is a Python computation — did the incident get resolved before the deadline, weighted by severity. That removes any subjectivity from our results.

---

## Slide 3 — Benchmark: Tasks & Evaluation
**⏱ ~1 minute**

We organized the 20 scenarios into four difficulty tiers, each designed to stress a specific failure mode.

Tier 1 is basic routing. Tier 2 introduces capacity math — multiple units need to coordinate on a single incident. Tier 3 is where it gets interesting: we force resource scarcity. There's a severe train derailment that needs all available medical capacity, but minor injuries are also active. The total fleet capacity is exactly four. A naive agent that tries to help everyone fails the most critical incident. The agent has to mathematically decide to abandon the minor injuries to maximize the overall score.

Tier 4 adds dynamic replanning. At a fixed time, a hidden trigger fires — a bridge collapses, a road floods — and the agent has to discard its current route and recalculate on the fly.

We evaluate on two primary metrics: PWRS, which is on-time severity-weighted resolution, and Cap-PWRS, which gives partial credit for coverage even when the deadline is missed.

---

## Slide 4 — Agent Architecture
**⏱ ~1 minute**

Here's how the agent works at a high level.

The agent runs in a loop. It observes the current world state, builds a ranked plan of open incidents, and then enters the Act phase — which is where all the interesting work happens. After each dispatch, it waits for the next meaningful event: either a vehicle returning from a mission or a dynamic alert firing. If an alert fires, it replans from scratch. Otherwise it loops back.

The outer loop is simple. The Act phase is where we depart from both baselines. Rather than just sending the nearest available vehicle to the highest priority incident, the agent generates every valid dispatch option, simulates each one forward, and picks the best projected outcome.

---

## Slide 5 — Key Components & Technical Approach
**⏱ ~1 minute**

The pipeline inside Act has seven components.

It starts with the WorldState — the live simulation of everything. The Candidate Generator pulls every valid vehicle-incident pair from that state. The Hybrid Scorer ranks them by urgency, deadline pressure, and scarcity — penalizing the use of a vehicle that's the only option for another incident.

The top candidates then go through Clone-Based Rollout. We deep-copy the world, simulate each dispatch a few steps forward, and measure the projected benchmark score. This is the core of what makes AgentKit smarter than greedy — it looks ahead instead of just acting locally.

Once we have projected scores, if one candidate is clearly better, it goes straight to the ValidatorTool, which enforces hard constraints before anything executes. If the scores are too close to call, we route through the LLM Arbitrator, which gets context from the Memory Log and picks from the shortlist. Either way, nothing dispatches without passing the validator.

---

## Slide 6 — Results
**⏱ ~1.5 minutes**

Here are the results across all four tiers, comparing zero-shot, deterministic, and AgentKit on PWRS and Cap-PWRS.

The story is clean. On Tiers 1, 2, and 4, all three methods are essentially tied. AgentKit never regresses — it matches the deterministic baseline everywhere it can't improve.

Tier 3 is where the gap opens. AgentKit scores 0.807 PWRS versus 0.719 for deterministic and 0.615 for zero-shot. That's an 8.8 percentage point gain over the greedy baseline and nearly 20 points over zero-shot.

Zero-shot also introduces constraint violations in Tier 2 — the LLM dispatched a vehicle that contributed nothing to the incident's required capabilities. That's exactly the failure mode the validator is designed to catch. AgentKit has zero violations across all 20 scenarios.

Tier 4 is where everything flattens out. All methods score identically on most scenarios. We'll explain why in a moment.

---

## Slide 7 — Where the Agent Succeeds
**⏱ ~45 seconds**

The clearest success is Tier 3, Scenario 13. One police unit has to serve two incidents — a riot that's 18 minutes away, and a traffic call that's only 6.7 minutes away.

Greedy methods go to the riot first because it's higher severity. That locks the vehicle away for 18 minutes, and by the time it returns, the traffic deadline is missed. PWRS of 0.850.

AgentKit's rollout projected that doing the quick traffic job first would return the vehicle in time to still make the riot deadline. PWRS of 1.000. That's the lookahead working exactly as intended — a non-obvious sequencing decision that greedy reasoning can't find.

---

## Slide 8 — Where the Agent Struggles
**⏱ ~45 seconds**

Tier 4 is the hard limit for everyone. In Scenario 16, a bridge collapses 8 minutes into a mission. The vehicle is already en route and can't be recalled — it just takes the detour and arrives 45 minutes late. All three methods score zero.

In Scenario 19, two simultaneous alerts close both approaches to the riot incident. After the police unit completes its mission, there's no valid path left to any remaining incident. Again, zero for everyone.

The key insight is that replanning only helps future dispatches. Once a vehicle is committed, we can't pull it back. That's the architectural limitation that Tier 4 exposes — and it's a limitation all three methods share equally.

---

## Slide 9 — Conclusion
**⏱ ~1.5 minutes**

To wrap up — we built RescueBench, a deterministically graded emergency dispatch benchmark with 20 scenarios across 4 tiers, and we built AgentKit, a hybrid agent that combines lookahead planning with conditional LLM arbitration.

Three things to take away.

First, structure beats raw LLM reasoning in constrained domains. Zero-shot produces violations and degrades under complexity. Giving the LLM pre-validated candidates to choose from — rather than an open action space — is more reliable.

Second, look-ahead is what separates good from great in complex scenarios. The Tier 3 gain came from the simulation correctly projecting a non-obvious dispatch ordering — it recognized that committing one vehicle too early would leave a more urgent incident without coverage moments later. That kind of multi-step reasoning is exactly what a purely reactive approach misses, and it is what pushed AgentKit nearly 9 points above the rule-based baseline.

Third, the hardest problems are environmental. Tier 4 isn't an algorithm problem — it's an infrastructure problem. No planning sophistication helps when the environment closes off routes after a vehicle is already committed.

To be transparent about limitations — the two main ones are: first, once a vehicle is dispatched it cannot be recalled mid-mission, which is the direct cause of every Tier 4 failure. Second, our benchmark is 20 scenarios. The results are consistent, but they should be validated at larger scale before strong generalizations are made.

The broader lesson is that deterministic grounding and LLM judgment are complements. Determinism handles correctness. The LLM handles contextual nuance at the boundaries where rules alone fall short. That's the design pattern this work demonstrates — and we think it generalizes well beyond emergency dispatch.

Thanks — happy to take questions.

---

## Timing Summary

| Slide | Content | Target Time |
|-------|---------|-------------|
| 1 | Intro & Motivation | 1:30 |
| 2 | Benchmark Design | 1:00 |
| 3 | Tasks & Evaluation | 1:00 |
| 4 | Agent Architecture | 1:00 |
| 5 | Key Components | 1:00 |
| 6 | Results | 1:30 |
| 7 | Success Examples | 0:45 |
| 8 | Failure Examples | 0:45 |
| 9 | Conclusion | 1:30 |
| **Total** | | **10:00** |