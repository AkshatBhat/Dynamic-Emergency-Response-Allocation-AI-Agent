# Dynamic Emergency Response Allocation AI Agent

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

## Run the Visualizer

Default run (uses `base_city_world.json`):
```bash
python3 visualize_city.py
```

Run with another JSON file (example: Tier 1):
```bash
python3 -c "import visualize_city as v; w=v.load_world('tier1_basic_triage.json'); v.visualize_world(w)"
```

## Files

- `base_city_world.json`: full baseline city world.
- `tier1_basic_triage.json`: simplified Tier 1 scenario.
- `visualize_city.py`: graph visualization script.
- `RescueBench Base City Schema_ Conceptual Design Document.pdf`: schema/design reference.
- `RescueBench JSON Data Dictionary.pdf`: field-level JSON dictionary/reference.
