# Dynamic Emergency Response Allocation AI Agent

This repository contains the RescueBench benchmark scenarios and the
grader-facing modular agent implementation in
[`rescuebench_agent/`](./rescuebench_agent).

## Main Code Path

The active implementation on `main` is the modular package:

- [`rescuebench_agent/`](./rescuebench_agent)
- benchmark scenarios: [`benchmark/`](./benchmark)
- final agent paper draft: [`new-agent-paper/`](./new-agent-paper)

Legacy material that is no longer meant to be the primary review surface has
been moved under
[`archived_legacy_not_current/`](./archived_legacy_not_current).

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

## Run The Modular Agent

Run the modular benchmark package:

```bash
python3 -m rescuebench_agent --mode agentkit --tier all --runs 1
```

Run the deterministic baseline:

```bash
python3 -m rescuebench_agent --mode deterministic --tier all --runs 1
```

## Visualizer

Default run:

```bash
python3 visualize_city.py
```

## Repo Layout

- [`rescuebench_agent/`](./rescuebench_agent): active modular implementation
- [`benchmark/`](./benchmark): RescueBench scenario files
- [`new-agent-paper/`](./new-agent-paper): current paper draft and assets
- [`archived_legacy_not_current/`](./archived_legacy_not_current): legacy
  monolith, older paper artifacts, and saved run outputs
- [`visualize_city.py`](./visualize_city.py): city graph visualization script

## Reference Documents

- [`RescueBench Base City Schema_ Conceptual Design Document.pdf`](./RescueBench%20Base%20City%20Schema_%20Conceptual%20Design%20Document.pdf)
- [`RescueBench JSON Data Dictionary.pdf`](./RescueBench%20JSON%20Data%20Dictionary.pdf)
