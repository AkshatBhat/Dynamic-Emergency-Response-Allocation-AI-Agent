# RescueBench Task Specifications

This document summarizes all 20 final RescueBench scenarios. The benchmark
inputs are the scenario JSON files in the tier folders. The expected output is
an action sequence of validated dispatch decisions that maximizes benchmark
metrics while respecting capabilities, deadlines, transport requirements, and
dynamic updates.

Common success criteria across all tasks:

- resolve as many incidents as possible
- satisfy required capabilities and quantity/capacity constraints
- meet deadlines where possible
- avoid invalid dispatches
- react correctly to any dynamic trigger events

## Tier 1: Basic Triage

These scenarios test basic dispatch and simple routing choices with no dynamic
triggers.

### `scenario1_tier1.json`

- Inputs: 2 incidents requiring `medical_triage` and `fire_suppression`
- Expected output: assign the correct medical and fire resources to the two
  incidents before deadlines
- Success focus: straightforward single-unit matching

### `scenario2_tier1.json`

- Inputs: 2 incidents requiring `traffic_control` and `bulk_supply`
- Expected output: use police and logistics resources correctly, including
  quantity-aware supply delivery
- Success focus: correct capability matching and quantity handling

### `scenario3_tier1.json`

- Inputs: 3 medical incidents requiring `medical_triage`
- Expected output: triage multiple concurrent medical calls with available
  ambulances
- Success focus: deadline-aware routing among several simple incidents

### `scenario4_tier1.json`

- Inputs: 3 incidents requiring `traffic_control` and `fire_suppression`
- Expected output: sequence fire and police resources across several incidents
- Success focus: basic multi-incident scheduling

### `scenario5_tier1.json`

- Inputs: 3 incidents requiring `fire_suppression`, `route_clearance`, and
  `patient_transport`
- Expected output: coordinate multiple resource types across mixed incidents
- Success focus: straightforward cross-capability coordination

## Tier 2: Constraint Satisfaction

These scenarios emphasize capacity constraints and multi-resource feasibility.

### `scenario6_tier2.json`

- Inputs: 1 incident requiring `traffic_control` and `fire_suppression`
- Expected output: dispatch the minimum correct capability combination
- Success focus: hard capability feasibility

### `scenario7_tier2.json`

- Inputs: 1 bus-rollover incident requiring `medical_triage`,
  `patient_transport`, `route_clearance`, and capacity `4`
- Expected output: compose multiple ambulances plus police support to satisfy
  the full requirement
- Success focus: multi-unit patient transport and quantity satisfaction

### `scenario8_tier2.json`

- Inputs: 1 incident requiring `medical_triage` and `fire_suppression`
- Expected output: satisfy a mixed-capability incident under deadline pressure
- Success focus: cross-role coordination

### `scenario9_tier2.json`

- Inputs: 1 incident requiring `medical_triage` and `patient_transport`
- Expected output: correctly sequence triage and transport behavior
- Success focus: transport-aware dispatch logic

### `scenario10_tier2.json`

- Inputs: 1 incident requiring `bulk_supply`, `medical_triage`, and capacity
  `2`
- Expected output: combine logistics and medical support under quantity
  constraints
- Success focus: mixed quantity and capability requirements

## Tier 3: Ethical Prioritization

These scenarios are designed to create meaningful prioritization ambiguity.

### `scenario11_tier3.json`

- Inputs: 3 medical incidents with high severity and combined required capacity
  `6`
- Expected output: choose a medically and ethically defensible triage order
- Success focus: scarce ambulance prioritization

### `scenario12_tier3.json`

- Inputs: 3 fire incidents with severity up to `10`
- Expected output: prioritize the most critical fire responses under limited
  fire suppression resources
- Success focus: severity/deadline tradeoff

### `scenario13_tier3.json`

- Inputs: 3 incidents mixing `medical_triage` and `traffic_control`
- Expected output: decide which high-stakes incident should receive the scarce
  shared resource first
- Success focus: ordering ambiguity with real performance consequences

### `scenario14_tier3.json`

- Inputs: 2 large logistics incidents requiring `bulk_supply` with total demand
  `70`
- Expected output: allocate supply capacity across competing high-severity
  incidents
- Success focus: ethically informed logistics prioritization

### `scenario15_tier3.json`

- Inputs: 3 incidents mixing `medical_triage` and `traffic_control`
- Expected output: choose a defensible incident order under trolley-style
  prioritization pressure
- Success focus: ethical ordering and scarce-resource preservation

## Tier 4: Dynamic Replanning

These scenarios require reacting to trigger events that alter the world during
execution.

### `scenario16_tier4.json`

- Inputs: 1 transport incident with 1 dynamic trigger
- Expected output: complete the mission while reacting correctly to a mid-run
  disruption
- Success focus: trigger-aware replanning

### `scenario17_tier4.json`

- Inputs: 1 mass-casualty transport incident with capacity `4` and 1 hospital
  diversion trigger
- Expected output: reroute active medical transports after hospital access is
  blocked
- Success focus: dynamic hospital diversion under quantity requirements

### `scenario18_tier4.json`

- Inputs: 1 mixed `medical_triage` plus `fire_suppression` incident with 2
  triggers
- Expected output: sustain progress despite multiple dynamic changes
- Success focus: multi-trigger replanning

### `scenario19_tier4.json`

- Inputs: 1 mixed `bulk_supply` plus `traffic_control` incident with 2 triggers
- Expected output: continue logistics execution under route/state disruption
- Success focus: dynamic logistics replanning

### `scenario20_tier4.json`

- Inputs: 2 incidents requiring `fire_suppression`, `medical_triage`,
  `patient_transport`, `route_clearance`, and `structural_rescue`, with 2
  triggers and combined capacity `3`
- Expected output: coordinate multiple vehicle classes while adapting to
  cascading disruptions
- Success focus: the most complex multi-resource dynamic scenario in the suite

## Notes on Ground Truth and Evaluation

- Inputs are fully specified by the scenario JSONs.
- Expected outputs are not a single gold dispatch script; agents are evaluated
  by outcome metrics.
- The evaluation harness defines success objectively through the metrics listed
  in [`README.md`](./README.md) and implemented in
  [`../rescuebench_agent/metrics.py`](../rescuebench_agent/metrics.py).
