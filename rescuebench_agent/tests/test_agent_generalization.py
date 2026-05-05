from __future__ import annotations

import copy
import unittest

from rescuebench_agent.agents.rescue_agent import run_agentkit
from rescuebench_agent.modes.deterministic import run_deterministic


def _node(node_id: str, node_type: str = "standard_intersection", hospital_capacity: int = 0) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "hospital": node_type == "hospital",
        "hospital_capacity": hospital_capacity if node_type == "hospital" else 0,
        "hospital_current": 0,
        "current_capacity": hospital_capacity,
    }


def _edge(edge_id: str, source: str, target: str, travel: float, allowed: list[str]) -> dict:
    return {
        "id": edge_id,
        "source_node": source,
        "target_node": target,
        "base_travel_time": travel,
        "status": "clear",
        "allowed_vehicle_types": allowed,
    }


def _vehicle(
    vehicle_type: str,
    location: str,
    capabilities: list[str],
    *,
    capacity: int = 0,
    speed_multiplier: float = 1.0,
    fuel: float = 100.0,
    current_load: int = 0,
) -> dict:
    return {
        "type": vehicle_type,
        "location": location,
        "home_depot": location,
        "capacity": capacity,
        "current_load": current_load,
        "capabilities": capabilities,
        "speed_multiplier": speed_multiplier,
        "available": True,
        "busy_until": 0.0,
        "fuel": fuel,
    }


def _incident(
    location: str,
    severity: int,
    deadline: float,
    capabilities: list[str],
    *,
    required_quantity: int = 0,
) -> dict:
    return {
        "type": "custom_incident",
        "location": location,
        "severity": severity,
        "patients": required_quantity,
        "required_quantity": required_quantity,
        "required_capabilities": capabilities,
        "deadline_minutes": deadline,
        "resolved": False,
        "resolved_at": None,
        "covered_capabilities": [],
        "committed_capabilities": [],
    }


class AgentGeneralizationTests(unittest.TestCase):
    def test_custom_quantity_capability_not_in_benchmark_schema(self) -> None:
        scenario = {
            "scenario_id": "custom_water_delivery",
            "name": "Custom Water Delivery",
            "current_time": 0,
            "edges_raw": [
                _edge("edge_depot_site", "node_depot", "node_site", 4, ["utility_truck", "ops_van"]),
            ],
            "nodes": {
                "node_depot": _node("node_depot", "depot"),
                "node_site": _node("node_site"),
            },
            "vehicles": {
                "TRUCK_1": _vehicle(
                    "utility_truck",
                    "node_depot",
                    ["water_delivery"],
                    capacity=10,
                ),
                "OPS_1": _vehicle(
                    "ops_van",
                    "node_depot",
                    ["site_assessment"],
                ),
            },
            "incidents": {
                "INC_WATER_1": _incident(
                    "node_site",
                    severity=5,
                    deadline=15,
                    capabilities=["water_delivery", "site_assessment"],
                    required_quantity=6,
                ),
            },
            "dynamic_triggers": [],
        }

        result = run_agentkit(
            copy.deepcopy(scenario),
            api_key=None,
            use_llm_for_ethics=False,
            use_llm_for_planning=False,
        )

        self.assertEqual(result["resolution_rate"], 1.0)
        self.assertEqual(result["deadline_adherence"], 1.0)
        self.assertEqual(result["incidents_resolved"]["INC_WATER_1"], True)

    def test_agent_preserves_unique_vehicle_for_unique_incident(self) -> None:
        scenario = {
            "scenario_id": "custom_unique_provider",
            "name": "Custom Unique Provider",
            "current_time": 0,
            "edges_raw": [
                _edge("edge_multi_a", "node_multi", "node_a", 2, ["rescue_hybrid"]),
                _edge("edge_multi_b", "node_multi", "node_b", 4, ["rescue_hybrid"]),
                _edge("edge_med_a", "node_med", "node_a", 3, ["medic"]),
                _edge("edge_med_b", "node_med", "node_b", 6, ["medic"]),
                _edge("edge_a_b", "node_a", "node_b", 8, ["rescue_hybrid", "medic"]),
            ],
            "nodes": {
                "node_multi": _node("node_multi", "depot"),
                "node_med": _node("node_med", "depot"),
                "node_a": _node("node_a"),
                "node_b": _node("node_b"),
            },
            "vehicles": {
                "MULTI_1": _vehicle(
                    "rescue_hybrid",
                    "node_multi",
                    ["medical_triage", "hazmat"],
                ),
                "MED_1": _vehicle(
                    "medic",
                    "node_med",
                    ["medical_triage"],
                ),
            },
            "incidents": {
                "INC_HIGH_TRIAGE": _incident(
                    "node_a",
                    severity=9,
                    deadline=10,
                    capabilities=["medical_triage"],
                ),
                "INC_HAZMAT": _incident(
                    "node_b",
                    severity=8,
                    deadline=5,
                    capabilities=["hazmat"],
                ),
            },
            "dynamic_triggers": [],
        }

        deterministic = run_deterministic(copy.deepcopy(scenario))
        agentkit = run_agentkit(
            copy.deepcopy(scenario),
            api_key=None,
            use_llm_for_ethics=False,
            use_llm_for_planning=False,
        )

        self.assertLess(deterministic["pwrs"], agentkit["pwrs"])
        self.assertEqual(agentkit["resolution_rate"], 1.0)
        self.assertEqual(agentkit["deadline_adherence"], 1.0)

    def test_agent_handles_custom_diversion_trigger(self) -> None:
        scenario = {
            "scenario_id": "custom_diversion",
            "name": "Custom Diversion",
            "current_time": 0,
            "edges_raw": [
                _edge("edge_depot_crash", "node_depot", "node_crash", 4, ["ambulance"]),
                _edge("edge_crash_primary", "node_crash", "node_hospital_primary", 4, ["ambulance"]),
                _edge("edge_crash_backup", "node_crash", "node_hospital_backup", 6, ["ambulance"]),
            ],
            "nodes": {
                "node_depot": _node("node_depot", "depot"),
                "node_crash": _node("node_crash"),
                "node_hospital_primary": _node("node_hospital_primary", "hospital", hospital_capacity=5),
                "node_hospital_backup": _node("node_hospital_backup", "hospital", hospital_capacity=5),
            },
            "vehicles": {
                "AMB_1": _vehicle(
                    "ambulance",
                    "node_depot",
                    ["patient_transport"],
                    capacity=2,
                ),
            },
            "incidents": {
                "INC_DIVERT_1": _incident(
                    "node_crash",
                    severity=7,
                    deadline=15,
                    capabilities=["patient_transport"],
                    required_quantity=2,
                ),
            },
            "dynamic_triggers": [
                {
                    "trigger_time": 5,
                    "event_type": "road_flood",
                    "target_edge": "edge_crash_primary",
                    "new_status": "blocked",
                    "message": "Primary hospital route flooded. Divert immediately.",
                    "fired": False,
                }
            ],
        }

        agentkit = run_agentkit(
            copy.deepcopy(scenario),
            api_key=None,
            use_llm_for_ethics=False,
            use_llm_for_planning=False,
        )

        self.assertEqual(agentkit["resolution_rate"], 1.0)
        self.assertEqual(agentkit["deadline_adherence"], 1.0)
        self.assertEqual(agentkit["incidents_resolved"]["INC_DIVERT_1"], True)


if __name__ == "__main__":
    unittest.main()
