from __future__ import annotations

from .world import WorldState

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "get_map_state",
        "description": (
            "Returns the full city map: nodes, their connections, blocked edges, "
            "and any active alerts from dynamic events."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_vehicles",
        "description": (
            "Returns current status of all vehicles, including availability, busy_until, "
            "next_available_location, onboard load, and mission state."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_incidents",
        "description": (
            "Returns all unresolved incidents including type, location, severity, "
            "required capabilities, uncovered capabilities, quantity demand if any, and deadline."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_shortest_path",
        "description": (
            "Calculate the shortest passable route between two nodes. "
            "Optionally filter for a specific vehicle type to respect road restrictions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "from_node": {
                    "type": "string",
                    "description": "Source node ID (e.g., 'node_depot_main').",
                },
                "to_node": {
                    "type": "string",
                    "description": "Destination node ID (e.g., 'node_int_08').",
                },
                "vehicle_type": {
                    "type": "string",
                    "description": (
                        "Optional vehicle type for road-restriction filtering "
                        "(e.g., 'ambulance', 'fire_engine')."
                    ),
                },
            },
            "required": ["from_node", "to_node"],
        },
    },
    {
        "name": "dispatch_vehicle",
        "description": (
            "Dispatch a vehicle to handle an incident. "
            "Dispatching reserves a concurrent mission; it does not immediately resolve the incident. "
            "For multi-capability or multi-quantity incidents, multiple vehicles may be dispatched. "
            "For ambulances transporting patients, include hospital_node."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vehicle_id": {
                    "type": "string",
                    "description": "Vehicle to dispatch (e.g., 'FIRE_01').",
                },
                "incident_id": {
                    "type": "string",
                    "description": "Target incident (e.g., 'INC_FIRE_001').",
                },
                "hospital_node": {
                    "type": "string",
                    "description": (
                        "Hospital node ID for patient transport. "
                        "Omit for non-transport missions."
                    ),
                },
            },
            "required": ["vehicle_id", "incident_id"],
        },
    },
    {
        "name": "advance_to_next_event",
        "description": (
            "Advance simulation time to the next vehicle release or dynamic trigger. "
            "Use this when no safe dispatch is currently possible because resources are busy."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "report_status",
        "description": (
            "Returns high-level summary of resolved/unresolved incidents, "
            "busy vehicles, next event time, and current simulation time."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]

SYSTEM_PROMPT = """You are the Dynamic Emergency Response Allocation Agent for RescueBench.
Your goal: resolve all active incidents before their deadlines, respecting all physical constraints.

CRITICAL RULES:
1. Call get_map_state, get_incidents, and get_vehicles at the start to understand the situation.
2. Always call get_shortest_path before dispatching to confirm routes are passable.
   NOTE: Some edges restrict which vehicle types can use them (e.g. suspension bridges).
3. Some incidents also have QUANTITY demand, such as medical load, patient transport load, or supply volume.
4. Quantity demand is composable across multiple compatible vehicles.
5. Dispatches are concurrent: you may dispatch multiple vehicles before advancing time.
6. When dispatching an ambulance carrying patients, ALWAYS include hospital_node.
7. Vehicles may become available again after completing their mission. If all useful resources are busy or already committed, call advance_to_next_event.
8. If you receive a VALIDATOR ERROR, read it carefully and correct your plan. Never repeat the same invalid action.
9. Prioritize higher-severity incidents. Break ties by tighter deadline.
10. After all dispatches, call report_status to confirm resolution.
11. DYNAMIC ALERTS: If a dispatch result or advance_to_next_event result includes dynamic_alerts, re-read the map and replan immediately.
"""

GEMINI_TOOLS = [
    {
        "function_declarations": [
            {
                "name": "get_map_state",
                "description": (
                    "Returns the full city map: nodes, their connections, blocked edges, "
                    "and any active alerts from dynamic events."
                ),
            },
            {
                "name": "get_vehicles",
                "description": (
                    "Returns vehicle status including availability, busy_until, "
                    "next_available_location, onboard load, and mission state."
                ),
            },
            {
                "name": "get_incidents",
                "description": (
                    "Returns all unresolved incidents including type, location, severity, "
                    "required capabilities, uncovered capabilities, quantity demand if any, and deadline."
                ),
            },
            {
                "name": "get_shortest_path",
                "description": (
                    "Calculate the shortest passable route between two nodes. "
                    "Optionally filter for a specific vehicle type to respect road restrictions."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "from_node": {"type": "STRING", "description": "Source node ID."},
                        "to_node": {"type": "STRING", "description": "Destination node ID."},
                        "vehicle_type": {
                            "type": "STRING",
                            "description": "Optional vehicle type for road-restriction filtering.",
                        },
                    },
                    "required": ["from_node", "to_node"],
                },
            },
            {
                "name": "dispatch_vehicle",
                "description": (
                    "Dispatch a vehicle to handle an incident. Dispatching reserves a concurrent mission. "
                    "For multi-capability or multi-quantity incidents, multiple vehicles may be dispatched. "
                    "Patient transport capacity is composable across multiple ambulances. "
                    "For ambulances transporting patients, include hospital_node."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "vehicle_id": {"type": "STRING", "description": "Vehicle to dispatch."},
                        "incident_id": {"type": "STRING", "description": "Target incident."},
                        "hospital_node": {
                            "type": "STRING",
                            "description": "Hospital node ID for patient transport.",
                        },
                    },
                    "required": ["vehicle_id", "incident_id"],
                },
            },
            {
                "name": "advance_to_next_event",
                "description": (
                    "Advance simulation time to the next vehicle release or dynamic trigger."
                ),
            },
            {
                "name": "report_status",
                "description": (
                    "Returns high-level summary of resolved/unresolved incidents, "
                    "busy vehicles, next event time, and current simulation time."
                ),
            },
        ]
    }
]


def build_zero_shot_prompt(scenario_dict: dict) -> str:
    """Build a single-shot prompt describing a scenario for the zero-shot baseline."""
    world = WorldState(scenario_dict)

    incident_lines = []
    for incident_id, incident in world.incidents.items():
        incident_lines.append(
            f"  - {incident_id}: type={incident['type']}, location={incident['location']}, "
            f"severity={incident['severity']}, deadline={incident['deadline_minutes']}min, "
            f"required_capabilities={incident['required_capabilities']}, "
            f"required_quantity={incident.get('required_quantity', 0)}, "
            f"quantity_capability={incident.get('quantity_capability')}"
        )

    vehicle_lines = []
    for vehicle_id, vehicle in world.vehicles.items():
        vehicle_lines.append(
            f"  - {vehicle_id}: type={vehicle['type']}, location={vehicle['location']}, "
            f"capabilities={vehicle['capabilities']}, capacity={vehicle['capacity']}, fuel={vehicle.get('fuel', 100)}"
        )

    node_lines = []
    for node_id, node_data in world.nodes.items():
        if node_data.get("hospital"):
            node_lines.append(f"  - {node_id}: HOSPITAL (capacity={node_data['hospital_capacity']})")
        elif node_data.get("type", "") == "depot":
            node_lines.append(f"  - {node_id}: depot")

    edge_lines = []
    for edge in world.edges_raw:
        if edge.get("allowed_vehicle_types") and len(edge["allowed_vehicle_types"]) < 4:
            edge_lines.append(
                f"  - {edge['id']}: {edge['source_node']} <-> {edge['target_node']}, "
                f"time={edge['base_travel_time']}min, restricted to {edge['allowed_vehicle_types']}"
            )

    prompt = (
        f"You are an emergency response coordinator for scenario: {world.name}\n\n"
        f"INCIDENTS:\n" + "\n".join(incident_lines) + "\n\n"
        f"VEHICLES:\n" + "\n".join(vehicle_lines) + "\n\n"
        f"KEY NODES:\n" + "\n".join(node_lines) + "\n\n"
    )
    if edge_lines:
        prompt += "RESTRICTED EDGES (not all vehicle types allowed):\n" + "\n".join(edge_lines) + "\n\n"

    prompt += (
        "Task: Output a JSON array of dispatch decisions. Each decision is:\n"
        '  {"vehicle_id": "...", "incident_id": "...", "hospital_node": "..." (or null)}\n\n'
        "Rules:\n"
        "1. Vehicles may be reused only after completing their mission, but your output should still respect current feasibility.\n"
        "2. For multi-capability incidents, send multiple vehicles as needed.\n"
        "3. Quantity demand can be split across multiple compatible vehicles.\n"
        "4. For ambulances carrying patients, include the hospital_node.\n"
        "5. Respect vehicle type restrictions on edges and fuel constraints.\n"
        "6. Prioritize higher-severity incidents.\n\n"
        "Output ONLY the JSON array, no other text."
    )
    return prompt
