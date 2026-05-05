# Potential Professor Q&A

---

**Q1: You said the LLM confirmed the heuristic's top pick every single time in Tier 3. So what is the point of including the LLM at all?**

The LLM acts as a safety valve for edge cases the heuristic cannot anticipate. In our 20 scenarios it never needed to override, but the design is deliberate — ethical ties between identically scored incidents, dynamic alerts that change context mid-run, and genuinely ambiguous multi-way tradeoffs are all cases where rule-based scoring can break down. The Tier 3 result actually validates the architecture: the LLM was consulted and agreed, which means the rollout was producing reliable signal. In a larger or messier deployment, the LLM override path would see more use.

---

**Q2: What makes Tier 3 specifically the one where lookahead helps? Why not Tier 1 or Tier 2?**

Tiers 1 and 2 have scenarios where the dispatch order does not affect outcomes — each incident has enough independent coverage that a greedy choice and the optimal choice converge. Tier 3 introduces ordering dependencies: dispatching vehicle A to incident X first leaves vehicle B unavailable for incident Y, causing a deadline miss. The reverse order avoids it. A greedy heuristic scores each dispatch in isolation and misses this. The clone-based rollout simulates the downstream consequence and catches it. Tier 4 also has ordering complexity, but the bottleneck there is the road closure constraint, not dispatch order, which no algorithm can overcome given the no-recall rule.

---

**Q3: How does this scale? Would clone-based rollout be feasible in a real city with hundreds of vehicles and incidents?**

At current scale — up to roughly 15 vehicles and 10 incidents per scenario — each rollout takes milliseconds. The cost scales with the number of candidates times rollout depth, so a much larger fleet would need either a shallower rollout, a smaller candidate pool, or parallelization across candidates. The architecture supports all three. The LLM call, not the rollout, is the actual latency bottleneck in practice. For real deployment you would also want to tune the candidate pool cap and rollout depth based on available compute.

---

**Q4: Your benchmark is only 20 scenarios. How confident are you that these results generalize?**

We are cautious about this and acknowledge it explicitly in the conclusion. The 20 scenarios were designed to stress different constraint types across four tiers, so they are not all identical, but 20 is a small sample for strong statistical claims. The consistency across all five scenarios within each tier is encouraging — there are no outlier scenarios where one method randomly dominates. Ideally we would validate at 100+ scenarios before making strong generalizations, and expanding the benchmark is the most direct next step.

---

**Q5: Could the Tier 4 problem be solved with a different design — for example, allowing vehicles to be reassigned mid-mission?**

Yes, that is the most direct fix. If a vehicle could be recalled or rerouted after a road closure fires, the agent could react and redirect it to a still-reachable incident. The current no-recall constraint was a deliberate design choice to keep the benchmark grounded in real-world emergency dispatch, where mid-mission redirects carry physical and coordination costs. Adding a recall action with an associated penalty — for example, partial credit lost and delay incurred — would be a natural extension and would make Tier 4 a genuine algorithmic challenge rather than a structural one.
