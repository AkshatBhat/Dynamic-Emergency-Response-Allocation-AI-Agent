# Dynamic Emergency Response Allocation AI Agent

This repository contains both final course deliverables:

- the **RescueBench benchmark** and its evaluation materials
- the **modular RescueBench agent implementation** used in the final agent paper

The active code on `main` is the modular package in
[`rescuebench_agent/`](./rescuebench_agent). Legacy monolithic code and older
artifacts are preserved under
[`archived_legacy_not_current/`](./archived_legacy_not_current) and are kept
for reference only.

## What To Read First

- Benchmark overview and task suite:
  [`benchmark/README.md`](./benchmark/README.md)
- Agent overview and run instructions:
  [`rescuebench_agent/README.md`](./rescuebench_agent/README.md)
- Modular implementation notes:
  [`rescuebench_agent/docs/`](./rescuebench_agent/docs)

## Submission Materials

### Benchmark paper materials

- Final benchmark paper:
  [`benchmark_papers/Group2_Final_Benchmark_Paper.pdf`](./benchmark_papers/Group2_Final_Benchmark_Paper.pdf)
- Benchmark scenarios and resources:
  [`benchmark/`](./benchmark)
- Benchmark task specifications:
  [`benchmark/TASK_SPECIFICATIONS.md`](./benchmark/TASK_SPECIFICATIONS.md)

### Agent paper materials

- Final agent paper:
  [`agent_papers/Group2_Final_Agent_Paper.pdf`](./agent_papers/Group2_Final_Agent_Paper.pdf)
- Agent implementation:
  [`rescuebench_agent/`](./rescuebench_agent)
- Agent implementation notes:
  [`rescuebench_agent/docs/`](./rescuebench_agent/docs)

### Presentation materials

- Slides:
  [`presentations/CS 498 DK3_4_ Dynamic Emergency Response Allocation Agent.pdf`](./presentations/CS%20498%20DK3_4_%20Dynamic%20Emergency%20Response%20Allocation%20Agent.pdf)
- Supporting notes:
  [`presentations/`](./presentations)

## Setup

1. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   ```
2. Activate it:
   ```bash
   source .venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

Optional environment variables for LLM-backed modes:

- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`

## Quick Start

Run the deterministic benchmark baseline:

```bash
python3 -m rescuebench_agent --mode deterministic --tier all --runs 1
```

Run the modular `agentkit` implementation:

```bash
python3 -m rescuebench_agent --mode agentkit --tier all --runs 1
```

Run the full benchmark suite for a single tier:

```bash
python3 -m rescuebench_agent --mode all --tier 1 --runs 1
```

The benchmark runner writes aggregated output to
`rescuebench_agent/benchmark_results.json`.

## Reproducing Final Results

The package supports the same modes discussed in the final papers:

- `deterministic`
- `zero_shot`
- `react`
- `ablated`
- `agentkit`

Example reproductions:

```bash
python3 -m rescuebench_agent --mode deterministic --tier all --runs 3
python3 -m rescuebench_agent --mode agentkit --tier all --runs 3 --provider anthropic
python3 -m rescuebench_agent --mode zero_shot --tier all --runs 1 --provider anthropic
```

Use [`rescuebench_agent/README.md`](./rescuebench_agent/README.md) for a fuller
description of modes, outputs, and expected dependencies.

## Benchmark Utilities

Visualizer:

```bash
python3 benchmark/visualize_city.py
```

Conceptual and schema references:

- [`benchmark/RescueBench Base City Schema_ Conceptual Design Document.pdf`](./benchmark/RescueBench%20Base%20City%20Schema_%20Conceptual%20Design%20Document.pdf)
- [`benchmark/RescueBench JSON Data Dictionary.pdf`](./benchmark/RescueBench%20JSON%20Data%20Dictionary.pdf)

## Repository Layout

- [`benchmark/`](./benchmark): benchmark scenarios, schema docs, visualizer, and benchmark documentation
- [`rescuebench_agent/`](./rescuebench_agent): active modular agent implementation and benchmark runner
- [`agent_papers/`](./agent_papers): benchmarked agent paper PDFs
- [`benchmark_papers/`](./benchmark_papers): benchmark paper PDFs
- [`presentations/`](./presentations): presentation deck and speaking materials
- [`assignments/`](./assignments): earlier milestone submissions
- [`archived_legacy_not_current/`](./archived_legacy_not_current): archived monolithic code, old drafts, and saved run outputs
