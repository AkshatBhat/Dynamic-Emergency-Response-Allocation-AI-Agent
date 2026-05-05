from __future__ import annotations

import json
import re

from ..metrics import compute_metrics
from ..prompts import build_zero_shot_prompt
from ..tools import ValidatorTool, WorldTool
from ..world import WorldState


def run_zero_shot(
    scenario_dict: dict,
    api_key: str,
    model: str = "claude-sonnet-4-5",
    provider: str = "anthropic",
) -> dict:
    """
    Zero-shot baseline: one LLM call, parse a JSON dispatch list, execute it
    without validator blocking, but still count violations deterministically.
    """
    world = WorldState(scenario_dict)
    world_tool = WorldTool(world)
    validator = ValidatorTool(world)
    prompt = build_zero_shot_prompt(scenario_dict)

    try:
        if provider == "gemini":
            import google.generativeai as genai

            genai.configure(api_key=api_key)
            gmodel = genai.GenerativeModel(model)
            gresponse = gmodel.generate_content(prompt)
            raw_text = gresponse.text if gresponse.text else ""
        else:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = response.content[0].text if response.content else ""
    except Exception as exc:
        print(f"  [ZeroShot] API error: {exc}")
        return compute_metrics(world, validator, 1, "zero_shot")

    decisions: list[dict] = []
    json_match = re.search(r"\[.*\]", raw_text, re.DOTALL)
    if json_match:
        try:
            decisions = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            print("  [ZeroShot] Could not parse JSON from response.")

    step_count = 1
    zero_shot_violations = 0

    for decision in decisions:
        vehicle_id = decision.get("vehicle_id", "")
        incident_id = decision.get("incident_id", "")
        hospital_node = decision.get("hospital_node")

        vehicle = world.vehicles.get(vehicle_id)
        incident = world.incidents.get(incident_id)
        if vehicle and incident:
            effective_needed = set(world.incident_effective_uncovered_capabilities(incident))
            contributes = set(vehicle.get("capabilities", [])) & effective_needed
            if world.vehicle_quantity_capacity(vehicle, incident, hospital_node if hospital_node else None) > 0:
                quantity_capability = world.quantity_capability(incident)
                if quantity_capability:
                    contributes.add(quantity_capability)
            if not contributes:
                zero_shot_violations += 1
                print(f"  [ZeroShot] Violation: {vehicle_id} contributes nothing to {incident_id}.")

        if vehicle and incident and not incident["resolved"]:
            world_tool.dispatch_vehicle(
                vehicle_id=vehicle_id,
                incident_id=incident_id,
                hospital_node=hospital_node if hospital_node else None,
            )
            step_count += 1

    while world.has_pending_events():
        world_tool.advance_to_next_event()

    result = compute_metrics(world, validator, step_count, "zero_shot")
    result["violation_count"] = zero_shot_violations
    return result
