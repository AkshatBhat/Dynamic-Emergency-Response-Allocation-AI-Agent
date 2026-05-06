# Submission Guide

This document maps the repository contents to the final benchmark paper and
final agent paper submission requirements.

## Final Benchmark Paper Materials

### Final paper PDF

- [`benchmark_papers/Group2_Final_Benchmark_Paper.pdf`](./benchmark_papers/Group2_Final_Benchmark_Paper.pdf)

### Task specifications

- [`benchmark/TASK_SPECIFICATIONS.md`](./benchmark/TASK_SPECIFICATIONS.md)
- Scenario JSON files under [`benchmark/`](./benchmark)

These provide the final 20-task suite, inputs, expected agent behavior, and
success criteria through the benchmark metrics.

### Evaluation code

- [`rescuebench_agent/benchmark.py`](./rescuebench_agent/benchmark.py)
- [`rescuebench_agent/cli.py`](./rescuebench_agent/cli.py)
- [`rescuebench_agent/metrics.py`](./rescuebench_agent/metrics.py)

These files define how scenarios are loaded, executed, and scored.

### Data/resources

- [`benchmark/base_city_world.json`](./benchmark/base_city_world.json)
- Tier scenario folders inside [`benchmark/`](./benchmark)
- [`benchmark/RescueBench Base City Schema_ Conceptual Design Document.pdf`](./benchmark/RescueBench%20Base%20City%20Schema_%20Conceptual%20Design%20Document.pdf)
- [`benchmark/RescueBench JSON Data Dictionary.pdf`](./benchmark/RescueBench%20JSON%20Data%20Dictionary.pdf)

### Usage documentation

- [`benchmark/README.md`](./benchmark/README.md)
- Root [`README.md`](./README.md)

## Final Agent Paper Materials

### Final paper PDF

- [`agent_papers/Group2_Final_Agent_Paper.pdf`](./agent_papers/Group2_Final_Agent_Paper.pdf)

### Agent implementation

- [`rescuebench_agent/`](./rescuebench_agent)

Key files:

- [`rescuebench_agent/agents/rescue_agent.py`](./rescuebench_agent/agents/rescue_agent.py)
- [`rescuebench_agent/world.py`](./rescuebench_agent/world.py)
- [`rescuebench_agent/tools.py`](./rescuebench_agent/tools.py)
- [`rescuebench_agent/modes/`](./rescuebench_agent/modes)

### Requirements / dependencies

- [`requirements.txt`](./requirements.txt)

### README and reproduction instructions

- [`rescuebench_agent/README.md`](./rescuebench_agent/README.md)
- Root [`README.md`](./README.md)

### Evaluation scripts

- [`rescuebench_agent/benchmark.py`](./rescuebench_agent/benchmark.py)
- [`rescuebench_agent/cli.py`](./rescuebench_agent/cli.py)

## Reproduction Commands

Setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Deterministic benchmark baseline:

```bash
python3 -m rescuebench_agent --mode deterministic --tier all --runs 1
```

Hybrid agent:

```bash
python3 -m rescuebench_agent --mode agentkit --tier all --runs 1
```

Zero-shot LLM baseline:

```bash
python3 -m rescuebench_agent --mode zero_shot --tier all --runs 1 --provider anthropic
```

## Additional Project Materials

- Presentation deck and notes: [`presentations/`](./presentations)
- Earlier milestone submissions: [`assignments/`](./assignments)
- Archived legacy implementation and old artifacts:
  [`archived_legacy_not_current/`](./archived_legacy_not_current)
