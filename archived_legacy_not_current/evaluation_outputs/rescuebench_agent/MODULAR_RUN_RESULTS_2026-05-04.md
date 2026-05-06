# Modular Benchmark Runs - 2026-05-04

## Run Configurations

- `deterministic`: all tiers, `runs=3`, local only
- `agentkit`: all tiers, `runs=3`, local only
- `zero_shot` with Claude: all tiers, `runs=1`
- `react` with Claude: Tier 1 only, `runs=1`
- `ablated` with Claude: Tier 1 only, `runs=1`

## Why the Claude Runs Are Partial

- Claude runs require the external API and are limited by organization token-per-minute rate limits.
- The full `all modes x all tiers x runs=3` benchmark would be expensive and slow.
- The `zero_shot` all-tier run completed, but it encountered rate-limit fallbacks on some later scenarios.
- `react` and `ablated` were limited to Tier 1 because they are multi-turn tool loops and are much slower than zero-shot.

## Saved Raw Result Files

- Full local no-API aggregate:
  [benchmark_results_local_no_api.json](/Users/akshat/Data/UIUC/Spring%202026/Courses/CS%20498%20AI%20Agents%20in%20the%20Wild/Project/Dynamic-Emergency-Response-Allocation-AI-Agent/rescuebench_agent/benchmark_results_local_no_api.json:1)
- The CLI also overwrote
  [benchmark_results.json](/Users/akshat/Data/UIUC/Spring%202026/Courses/CS%20498%20AI%20Agents%20in%20the%20Wild/Project/Dynamic-Emergency-Response-Allocation-AI-Agent/rescuebench_agent/benchmark_results.json:1)
  on each benchmark invocation, so it reflects only the most recent single-mode run.

## Aggregated Results Captured

### Deterministic (`runs=3`, all tiers)

- Tier 1: `pwrs=0.4964`, `cap_pwrs=0.7171`, `resolution_rate=1.0`, `deadline_adherence=0.4`, `violation_count=0.0`, `step_efficiency=1.0`
- Tier 2: `pwrs=0.4`, `cap_pwrs=0.7138`, `resolution_rate=0.8`, `deadline_adherence=0.4`, `violation_count=0.0`, `step_efficiency=0.5`
- Tier 3: `pwrs=0.41`, `cap_pwrs=0.453`, `resolution_rate=0.5`, `deadline_adherence=0.3667`, `violation_count=0.0`, `step_efficiency=0.9`
- Tier 4: `pwrs=0.3059`, `cap_pwrs=0.6258`, `resolution_rate=0.5`, `deadline_adherence=0.3`, `violation_count=0.0`, `step_efficiency=0.4`

### AgentKit (`runs=3`, all tiers)

- Tier 1: `pwrs=0.4964`, `cap_pwrs=0.7171`, `resolution_rate=1.0`, `deadline_adherence=0.4`, `violation_count=0.0`, `step_efficiency=1.0`
- Tier 2: `pwrs=0.4`, `cap_pwrs=0.7138`, `resolution_rate=0.8`, `deadline_adherence=0.4`, `violation_count=0.0`, `step_efficiency=0.5`
- Tier 3: `pwrs=0.41`, `cap_pwrs=0.453`, `resolution_rate=0.5`, `deadline_adherence=0.3667`, `violation_count=0.0`, `step_efficiency=0.9`
- Tier 4: `pwrs=0.3059`, `cap_pwrs=0.6258`, `resolution_rate=0.5`, `deadline_adherence=0.3`, `violation_count=0.0`, `step_efficiency=0.4`

### Zero-Shot Claude (`runs=1`, all tiers)

- Tier 1: `pwrs=0.496`, `cap_pwrs=0.684`, `resolution_rate=1.0`, `deadline_adherence=0.4`, `violation_count=0.0`, `step_efficiency=null`
- Tier 2: `pwrs=0.4`, `cap_pwrs=0.807`, `resolution_rate=1.0`, `deadline_adherence=0.4`, `violation_count=0.6`, `step_efficiency=null`
- Tier 3: `pwrs=0.45`, `cap_pwrs=0.49`, `resolution_rate=0.367`, `deadline_adherence=0.3`, `violation_count=0.2`, `step_efficiency=null`
- Tier 4: `pwrs=0.306`, `cap_pwrs=0.595`, `resolution_rate=0.6`, `deadline_adherence=0.3`, `violation_count=0.4`, `step_efficiency=null`

### ReAct Claude (`runs=1`, Tier 1 only)

- Tier 1: `pwrs=0.525`, `cap_pwrs=0.619`, `resolution_rate=0.8`, `deadline_adherence=0.467`, `violation_count=0.0`, `step_efficiency=0.4`

### Ablated Claude (`runs=1`, Tier 1 only)

- Tier 1: `pwrs=0.28`, `cap_pwrs=0.399`, `resolution_rate=0.6`, `deadline_adherence=0.267`, `violation_count=0.0`, `step_efficiency=0.34`

## Immediate Takeaways

- The modular package reproduces the current project behavior.
- `agentkit` remains effectively identical to the deterministic baseline.
- `zero_shot` improves partial coverage in some tiers but incurs violations and was vulnerable to Claude rate limits during the wider run.
- `react` on Tier 1 outperformed the local deterministic baseline on PWRS, but it is much slower and more expensive to evaluate.
- `ablated` performed materially worse than `react` in the Tier 1 modular run, which supports keeping the validation layer.
