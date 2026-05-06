# Dynamic Emergency Response Allocation Agent
### CS 498 AI Agents in the Wild — Final Presentation

---

## Slide 1 — Introduction & Motivation

**The Problem**
- LLMs excel at semantic reasoning but fail at strict mathematical optimization
- Disaster response requires both: parsing unstructured text *and* zero-error spatial constraint satisfaction
- End-to-end LLM solvers hallucinate routes, lose track of capacities, output infeasible actions

**Why It Matters**
- Opens a new design space: LLM as *orchestrator*, not *calculator*
- Enables explainable decisions in high-stakes domains — not a black box
- Directly relevant to AI agents research on hybrid human-AI systems

**Our Approach**
- Built **RescueBench** — a deterministic emergency dispatch benchmark
- Built **AgentKit** — a hybrid agent combining lookahead planning with conditional LLM arbitration
- Compared against zero-shot LLM and greedy deterministic baselines

---

## Slide 2 — Benchmark: Domain & Design

**Domain:** Humanitarian Logistics & Emergency Resource Allocation

**What We Built**
- 20 deterministic JSON scenarios on a shared 16-node city map
- Heterogeneous 4-class fleet: ambulances, fire engines, police, supply trucks
- Mathematically verified deadlines computed via Dijkstra's algorithm

**How We Generated It**
- Manually authored base city graph (`base_city_world.json`) to guarantee solvability
- LLM-assisted mutation pipeline (Gemini) to generate diverse incidents and dynamic triggers
- Injected timestamped infrastructure failures (bridge collapses, road floods)

**What Makes It Unique**
- No subjective grading — success is purely Boolean and algebraic
- Forces heuristic orchestration: agents *must* use external tools to avoid violations
- 4 difficulty tiers that isolate distinct failure modes

> 📊 **[PLACEHOLDER: Tier breakdown table or city map diagram]**

---

## Slide 3 — Benchmark: Tasks & Evaluation

**4 Difficulty Tiers**

| Tier | Name | Challenge |
|------|------|-----------|
| 1 | Basic Triage | Direct routing, single-unit dispatches |
| 2 | Constraint Math | Capacity arithmetic, multi-unit coordination |
| 3 | Ethical Prioritization | Forced scarcity — sacrifice low-severity to save high-severity |
| 4 | Dynamic Replanning | Mid-mission infrastructure failures triggered by simulation clock |

**Concrete Example — Tier 3 (Ethical Prioritization)**
- Train derailment (Severity 10) needs all 4 units of medical capacity
- Two minor injuries also active — total fleet capacity is exactly 4
- Agent must *intentionally* abandon minor injuries to maximize global score

**Concrete Example — Tier 4 (Dynamic Replanning)**
- At t=8 min: *"Suspension bridge blocked by debris"*
- Agent must discard its prior route and calculate a detour on the fly

**Evaluation Metrics**
- **PWRS** — Priority-Weighted Resolution Score (on-time, weighted by severity)
- **Cap-PWRS** — Partial coverage credit
- **Constraint Violation Rate** — Hard count of physically impossible actions

---

## Slide 4 — Agent Architecture

**The Agent Loop**
- Observe → Plan → Act → (Replan on alerts) → repeat
- After each dispatch: wait for next event (vehicle return or dynamic trigger)
- On dynamic alert: flush queue, re-rank all open incidents from scratch

> 🖼️ **[PLACEHOLDER: agentkit_architecture.png — high-level loop diagram]**

**Plain English**
> *"At every step, the agent looks at all possible dispatches, simulates them forward, and picks the best one — falling back to the LLM only when the scores are too close to call."*

---

## Slide 5 — Key Components & Technical Approach

> 🖼️ **[PLACEHOLDER: agentkit_components.png — key components diagram]**

**7 Components**

| Component | Role |
|---|---|
| WorldState | Live simulation — vehicles, incidents, routes, hospitals |
| Candidate Generator | Every valid (vehicle → incident) pair |
| Hybrid Scorer | Ranks by urgency, slack, scarcity |
| Clone-Based Rollout | Simulates each candidate forward — projects future PWRS |
| ValidatorTool | Hard gate — nothing dispatches without passing constraints |
| LLM Arbitrator | Tiebreaker when top scores are within 8% |
| Memory Log | Feeds recent decisions and alerts into LLM context |

**Central Techniques**
- **Lookahead via world cloning** — deep-copy simulator, dispatch on the copy, read projected score
- **Scarcity-aware scoring** — penalizes tying up a vehicle that is the only option elsewhere
- **Conditional LLM** — only invoked at genuine decision boundaries, not every step

---

## Slide 6 — Results

**PWRS / Cap-PWRS across all tiers**

| Tier | Zero-Shot | Deterministic | **AgentKit** |
|------|-----------|---------------|----------|
| 1 | 0.745 / 0.931 | 0.745 / 0.931 | **0.745 / 0.931** |
| 2 | 0.400 / 0.903 ⚠️ | 0.400 / 0.903 | **0.400 / 0.903** |
| 3 | 0.615 / 0.615 | 0.719 / 0.820 | **0.807 / 0.864** |
| 4 | 0.506 / 0.797 | 0.506 / 0.797 | **0.506 / 0.797** |
| **Mean** | 0.566 / 0.811 | 0.592 / 0.863 | **0.615 / 0.874** |

⚠️ = constraint violations (Zero-Shot, Tier 2)

**Key Findings**
- AgentKit is the only method that **never regresses** across any tier
- Tier 3: AgentKit +8.8pp over deterministic, +19.2pp over zero-shot
- Zero-shot degrades on complexity and introduces violations — structure matters
- Tier 4: all methods fail equally — dynamic blockages are an environmental ceiling

> 📊 **[PLACEHOLDER: Bar chart comparing PWRS across tiers and methods]**

---

## Slide 7 — Where the Agent Succeeds

**Tier 3, Scenario 13 — Vehicle Sequencing**

Setup: One police unit must serve two incidents — a riot (18.3 min away) and a traffic call (6.7 min away)

| Method | Order | PWRS |
|--------|-------|------|
| Zero-Shot | Riot first | 0.850 |
| Deterministic | Riot first | 0.850 |
| **AgentKit** | **Traffic first → Riot** | **1.000** |

The rollout projected that doing the fast job first returns POLICE_01 in time for the riot deadline.
Greedy methods lock the vehicle away for 18+ minutes and miss the deadline.

---

**Tier 3, Scenario 15 — Trolley Problem**

Setup: Three trolley incidents, one police unit, one medic

| Method | PWRS |
|--------|------|
| Zero-Shot | 0.375 — misses two of three |
| Deterministic | 1.000 |
| **AgentKit** | **1.000** |

Zero-shot cannot coordinate parallel dispatch without planning structure.

---

## Slide 8 — Where the Agent Struggles

**Tier 4, Scenario 16 — Bridge Collapse Mid-Mission**
- MED_01 dispatched at t=0. Bridge collapses at t=8 — forcing a major detour.
- MED_01 arrives at t=45.3, far past the deadline.
- **All methods: PWRS = 0.000**
- Replanning only affects *future* dispatches — committed vehicles cannot be recalled

**Tier 4, Scenario 19 — Simultaneous Double Blockage**
- POLICE_01 en route to riot. At t=10: northern approach iced over, southern approach barricaded.
- After completing mission, no valid path remains to any open incident.
- **All methods: PWRS = 0.000**
- When the environment is adversarially constrained, no planning overhead helps

**What We Learned**
- Lookahead only helps when *sequencing* matters — Tier 3 gains, not Tier 4
- Zero-shot fails structurally: its PWRS = Cap-PWRS (0.615 = 0.615) — no partial credit, binary outcomes only
- LLM confirmed heuristic's top pick **every single time** — the scorer is well-calibrated
- The hard ceiling is infrastructure, not algorithm

---

## Slide 9 — Conclusion

**Summary**
- RescueBench: 20 scenarios, 4 tiers, deterministic grading, no LLM-as-judge
- AgentKit: hybrid lookahead + conditional LLM — only method with zero regressions

**3 Things to Remember**
1. **Structure beats raw LLM** — pre-validated candidates eliminate violations and improve reliability
2. **Lookahead is the real driver** — the Tier 3 gain came from the rollout, not the LLM
3. **Hardest problems are environmental** — Tier 4 is an infrastructure ceiling, not a planning problem

**Limitations**
- Single dispatch per step — no joint multi-vehicle bundle optimization
- LLM contribution untested in practice — it agreed with the heuristic every time
- 20 scenarios is a small sample — results need larger-scale validation

**Future Work**
- Bundle-level joint planning for Tier 4 coordination
- Predictive replanning before dynamic events fire
- Stress-test LLM value in genuinely ambiguous, information-sparse scenarios

**Broader Impact**
> *Deterministic grounding and LLM judgment are complements, not competitors. This work shows where the boundary is — and why it matters for any agent operating under hard constraints.*
