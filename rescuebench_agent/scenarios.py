from __future__ import annotations

import copy
import json
from pathlib import Path


def load_scenario(json_path: str | Path) -> dict:
    """
    Load a benchmark JSON file and convert it into the internal scenario format
    consumed by WorldState.
    """
    json_path = Path(json_path)
    with json_path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    meta = raw.get("metadata", {})
    scenario_id = json_path.stem

    nodes: dict = {}
    for node in raw.get("nodes", []):
        node_id = node["id"]
        node_type = node.get("type", "standard_intersection")
        nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            "hospital": node_type == "hospital",
            "hospital_capacity": node.get("current_capacity", 0) if node_type == "hospital" else 0,
            "hospital_current": 0,
            "current_capacity": node.get("current_capacity", 0),
        }

    vehicle_classes: dict = raw.get("vehicle_classes", {})

    vehicles: dict = {}
    for vehicle in raw.get("active_fleet", []):
        vehicle_type = vehicle["vehicle_type"]
        vehicle_class = vehicle_classes.get(vehicle_type, {})
        vehicles[vehicle["unit_id"]] = {
            "type": vehicle_type,
            "location": vehicle["current_location"],
            "home_depot": vehicle.get("home_depot", vehicle["current_location"]),
            "capacity": vehicle_class.get("max_capacity", 0),
            "current_load": vehicle.get("current_capacity_used", 0),
            "capabilities": list(vehicle_class.get("capabilities", [])),
            "speed_multiplier": vehicle_class.get("speed_multiplier", 1.0),
            "available": vehicle.get("status", "idle") == "idle",
            "busy_until": 0,
            "fuel": vehicle.get("current_fuel", 100),
        }

    incidents: dict = {}
    for incident in raw.get("incidents", []):
        required_quantity = incident.get("required_capacity", 0)
        incidents[incident["incident_id"]] = {
            "type": incident["type"],
            "location": incident["location_node"],
            "severity": incident["severity_weight"],
            "patients": required_quantity,
            "required_quantity": required_quantity,
            "required_capabilities": list(incident["required_capabilities"]),
            "deadline_minutes": incident["deadline_min"],
            "resolved": False,
            "resolved_at": None,
            "covered_capabilities": [],
            "committed_capabilities": [],
        }

    edges_raw: list[dict] = copy.deepcopy(raw.get("edges", []))

    dynamic_triggers: list[dict] = []
    for trigger in raw.get("dynamic_triggers", []):
        dynamic_triggers.append(
            {
                "trigger_time": trigger["trigger_time"],
                "event_type": trigger.get("event_type", "unknown"),
                "target_edge": trigger.get("target_edge", ""),
                "new_status": trigger.get("new_status", "blocked"),
                "message": trigger.get("message_to_agent", ""),
                "fired": False,
            }
        )

    return {
        "scenario_id": scenario_id,
        "name": meta.get("scenario_name", scenario_id),
        "description": meta.get("description", ""),
        "current_time": meta.get("global_clock_min", 0),
        "edges_raw": edges_raw,
        "nodes": nodes,
        "vehicles": vehicles,
        "incidents": incidents,
        "dynamic_triggers": dynamic_triggers,
        "vehicle_classes": vehicle_classes,
    }
