"""
RescueBench Agent Implementation - Group 2
Dynamic Emergency Response Allocation Agent

Components:
  - WorldState:     Manages the live JSON simulation world (map, vehicles, incidents)
  - WorldTool:      The agent's interface for querying/mutating the simulation
  - ValidatorTool:  Deterministic safety layer that rejects physically impossible actions
  - Agent:          ReAct orchestration loop powered by Anthropic Claude API
  - Scenario:       Tier 1 "Basic Triage" scenario (no dynamic triggers, simple dispatches)
  - compute_metrics: Standalone function that consolidates all evaluation metrics

Usage:
  pip install anthropic
  python agent.py
"""

import os
import json
import math
import heapq
import copy
from typing import Any
import anthropic

# ─────────────────────────────────────────────────────────────────────────────
# PASTE YOUR API KEY HERE
# ─────────────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = ...


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: WORLD STATE
# Holds the full simulation: city graph, vehicles, incidents, blocked edges.
# ─────────────────────────────────────────────────────────────────────────────

EXAMPLE_SCENARIO: dict = {
    "scenario_id": "tier1_basic_triage",
    "name": "RescueBench Tier 1 - Basic Triage",
    "description": (
        "Level 1 benchmark scenario focusing on basic triage and simple VRP mechanics. "
        "Dynamic triggers are disabled. Two incidents require straightforward single-unit "
        "dispatches without complex capability sequencing."
    ),
    "current_time": 0,
    # Undirected edges: [node_a, node_b, travel_time_minutes]
    "edges": [
        ["node_depot_main",    "node_int_01",           5],
        ["node_depot_main",    "node_int_09",           8],
        ["node_int_01",        "node_int_02",           3],
        ["node_int_02",        "node_hospital_gen",     4],
        ["node_int_01",        "node_int_03",           6],
        ["node_int_03",        "node_int_04",          10],
        ["node_int_02",        "node_int_05",           8],   # suspension bridge
        ["node_int_04",        "node_gas_north",        2],
        ["node_int_05",        "node_shelter_east",     7],
        ["node_int_02",        "node_int_06",           5],
        ["node_int_06",        "node_hospital_south",   3],
        ["node_int_04",        "node_int_07",           4],
        ["node_int_07",        "node_gas_west",         2],
        ["node_int_05",        "node_int_08",           6],
        ["node_int_08",        "node_shelter_east",     4],
        ["node_int_06",        "node_int_09",           7],
        ["node_int_09",        "node_int_10",           3],
        ["node_int_10",        "node_int_04",           5],
        ["node_int_07",        "node_int_08",           9],
        ["node_int_03",        "node_int_07",           4],
    ],
    "blocked_edges": [],
    "nodes": {
        "node_depot_main":    {"name": "Main Depot",         "hospital": False, "hospital_capacity": 0,  "hospital_current": 0},
        "node_hospital_gen":  {"name": "General Hospital",   "hospital": True,  "hospital_capacity": 15, "hospital_current": 0},
        "node_hospital_south":{"name": "South Hospital",     "hospital": True,  "hospital_capacity": 8,  "hospital_current": 0},
        "node_gas_north":     {"name": "Gas Station North",  "hospital": False, "hospital_capacity": 0,  "hospital_current": 0},
        "node_gas_west":      {"name": "Gas Station West",   "hospital": False, "hospital_capacity": 0,  "hospital_current": 0},
        "node_shelter_east":  {"name": "Shelter East",       "hospital": False, "hospital_capacity": 0,  "hospital_current": 0},
        "node_int_01":        {"name": "Intersection 01",    "hospital": False, "hospital_capacity": 0,  "hospital_current": 0},
        "node_int_02":        {"name": "Intersection 02",    "hospital": False, "hospital_capacity": 0,  "hospital_current": 0},
        "node_int_03":        {"name": "Intersection 03",    "hospital": False, "hospital_capacity": 0,  "hospital_current": 0},
        "node_int_04":        {"name": "Intersection 04",    "hospital": False, "hospital_capacity": 0,  "hospital_current": 0},
        "node_int_05":        {"name": "Intersection 05",    "hospital": False, "hospital_capacity": 0,  "hospital_current": 0},
        "node_int_06":        {"name": "Intersection 06",    "hospital": False, "hospital_capacity": 0,  "hospital_current": 0},
        "node_int_07":        {"name": "Intersection 07",    "hospital": False, "hospital_capacity": 0,  "hospital_current": 0},
        "node_int_08":        {"name": "Intersection 08",    "hospital": False, "hospital_capacity": 0,  "hospital_current": 0},
        "node_int_09":        {"name": "Intersection 09",    "hospital": False, "hospital_capacity": 0,  "hospital_current": 0},
        "node_int_10":        {"name": "Intersection 10",    "hospital": False, "hospital_capacity": 0,  "hospital_current": 0},
    },
    "vehicles": {
        "MED_01": {
            "type": "ambulance",
            "location": "node_hospital_gen",
            "capacity": 2,
            "current_load": 0,
            "capabilities": ["medical_triage", "patient_transport"],
            "available": True,
            "busy_until": 0,
        },
        "MED_02": {
            "type": "ambulance",
            "location": "node_hospital_gen",
            "capacity": 2,
            "current_load": 0,
            "capabilities": ["medical_triage", "patient_transport"],
            "available": True,
            "busy_until": 0,
        },
        "FIRE_01": {
            "type": "fire_engine",
            "location": "node_depot_main",
            "capacity": 0,
            "current_load": 0,
            "capabilities": ["fire_suppression", "structural_rescue"],
            "available": True,
            "busy_until": 0,
        },
        "POLICE_01": {
            "type": "police_car",
            "location": "node_depot_main",
            "capacity": 1,
            "current_load": 0,
            "capabilities": ["traffic_control", "route_clearance"],
            "available": True,
            "busy_until": 0,
        },
    },
    "incidents": {
        "INC_MED_001": {
            "type": "minor_medical_emergency",
            "location": "node_int_08",
            "severity": 4,
            "patients": 1,
            "required_capabilities": ["medical_triage"],
            "deadline_minutes": 25,
            "resolved": False,
            "resolved_at": None,  # stamped by dispatch_vehicle for deadline evaluation
        },
        "INC_FIRE_002": {
            "type": "small_structural_fire",
            "location": "node_int_03",
            "severity": 6,
            "patients": 0,
            "required_capabilities": ["fire_suppression"],
            "deadline_minutes": 35,
            "resolved": False,
            "resolved_at": None,
        },
    },
    "dynamic_events": [],
}


class WorldState:
    """Mutable live state of the simulation. The WorldTool reads/writes here."""

    def __init__(self, scenario: dict):
        self.scenario_id: str = scenario["scenario_id"]
        self.current_time: int = scenario["current_time"]

        self.edges: list[list] = copy.deepcopy(scenario["edges"])
        self.blocked_edges: set[frozenset] = set()
        for be in scenario.get("blocked_edges", []):
            self.blocked_edges.add(frozenset(be))

        self.nodes: dict = copy.deepcopy(scenario["nodes"])
        self.vehicles: dict = copy.deepcopy(scenario["vehicles"])
        self.incidents: dict = copy.deepcopy(scenario["incidents"])
        self.dynamic_events: list = copy.deepcopy(scenario["dynamic_events"])
        self.event_log: list[str] = []

        self._apply_dynamic_events()

    def _apply_dynamic_events(self):
        """Fire any events scheduled at or before current_time."""
        for event in self.dynamic_events:
            if event["trigger_time"] <= self.current_time:
                if event["type"] == "block_edge":
                    self.blocked_edges.add(frozenset(event["edge"]))
                    self.event_log.append(event["description"])
                elif event["type"] == "hospital_full":
                    node = self.nodes[event["node"]]
                    node["hospital_current"] = node["hospital_capacity"]
                    self.event_log.append(event["description"])

    def build_graph(self) -> dict[str, list[tuple[str, int]]]:
        """Return adjacency list respecting blocked edges."""
        graph: dict[str, list[tuple[str, int]]] = {k: [] for k in self.nodes}
        for a, b, t in self.edges:
            if frozenset([a, b]) not in self.blocked_edges:
                graph[a].append((b, t))
                graph[b].append((a, t))
        return graph

    def dijkstra(self, source: str, target: str) -> tuple[float, list[str]]:
        """Shortest path with Dijkstra. Returns (cost, path). Cost=inf if unreachable."""
        graph = self.build_graph()
        dist = {n: math.inf for n in graph}
        prev: dict[str, str | None] = {n: None for n in graph}
        dist[source] = 0
        pq = [(0, source)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            for v, w in graph.get(u, []):
                nd = dist[u] + w
                if nd < dist[v]:
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))
        if math.isinf(dist[target]):
            return math.inf, []
        path, cur = [], target
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        path.reverse()
        return dist[target], path


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: WORLD TOOL
# The agent calls these functions as JSON tool calls.
# ─────────────────────────────────────────────────────────────────────────────

class WorldTool:
    """Exposes the simulation to the agent via structured function calls."""

    def __init__(self, world: WorldState):
        self.world = world

    def get_map_state(self) -> dict:
        """Return the full current map: nodes, edges, blocked routes."""
        graph = self.world.build_graph()
        return {
            "nodes": {
                nid: {**ndata, "connections": [n for n, _ in graph.get(nid, [])]}
                for nid, ndata in self.world.nodes.items()
            },
            "blocked_edges": [list(e) for e in self.world.blocked_edges],
            "active_alerts": self.world.event_log,
        }

    def get_vehicles(self) -> dict:
        """Return status of all vehicles."""
        return copy.deepcopy(self.world.vehicles)

    def get_incidents(self) -> dict:
        """Return all open incidents."""
        return {
            iid: inc for iid, inc in self.world.incidents.items() if not inc["resolved"]
        }

    def get_shortest_path(self, from_node: str, to_node: str) -> dict:
        """Calculate the shortest path and travel time between two nodes."""
        cost, path = self.world.dijkstra(from_node, to_node)
        if math.isinf(cost):
            return {"reachable": False, "path": [], "travel_time_minutes": None}
        return {"reachable": True, "path": path, "travel_time_minutes": cost}

    def dispatch_vehicle(
        self,
        vehicle_id: str,
        incident_id: str,
        hospital_node: str | None = None,
    ) -> dict:
        """
        Dispatch a vehicle to handle an incident.
        For ambulances transporting patients, hospital_node specifies the destination hospital.
        """
        v   = self.world.vehicles.get(vehicle_id)
        inc = self.world.incidents.get(incident_id)
        if not v or not inc:
            return {"success": False, "error": f"Unknown vehicle '{vehicle_id}' or incident '{incident_id}'."}

        cost, path = self.world.dijkstra(v["location"], inc["location"])
        if math.isinf(cost):
            return {"success": False, "error": f"No passable route from {v['location']} to incident at {inc['location']}."}

        result: dict[str, Any] = {
            "success": True,
            "vehicle_id": vehicle_id,
            "incident_id": incident_id,
            "route_to_incident": path,
            "travel_time_minutes": cost,
        }

        if "patient_transport" in v["capabilities"] and inc["patients"] > 0:
            if hospital_node is None:
                result["warning"] = "Patients need transport but no hospital_node was specified."
            else:
                hosp = self.world.nodes.get(hospital_node)
                if hosp and hosp["hospital"]:
                    hosp_cost, hosp_path = self.world.dijkstra(inc["location"], hospital_node)
                    if math.isinf(hosp_cost):
                        result["hospital_route_error"] = f"No route from incident to hospital node {hospital_node}."
                    else:
                        result["route_to_hospital"]            = hosp_path
                        result["hospital_travel_time_minutes"] = hosp_cost
                        result["total_trip_time_minutes"]      = cost + hosp_cost
                else:
                    result["hospital_route_error"] = f"Node {hospital_node} is not a hospital."

        arrival_time    = self.world.current_time + cost
        v["available"]  = False
        v["busy_until"] = arrival_time
        v["location"]   = inc["location"]
        inc["resolved"]    = True
        inc["resolved_at"] = arrival_time  # stamped for deadline evaluation
        return result

    def report_status(self) -> dict:
        """Return high-level summary: resolved/unresolved incidents and vehicle availability."""
        resolved           = [iid for iid, i in self.world.incidents.items() if i["resolved"]]
        unresolved         = [iid for iid, i in self.world.incidents.items() if not i["resolved"]]
        available_vehicles = [vid for vid, v in self.world.vehicles.items() if v["available"]]
        return {
            "resolved_incidents":   resolved,
            "unresolved_incidents": unresolved,
            "available_vehicles":   available_vehicles,
            "current_time":         self.world.current_time,
        }


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: VALIDATOR TOOL
# Deterministically checks LLM-proposed actions BEFORE they execute.
# ─────────────────────────────────────────────────────────────────────────────

class ValidatorTool:
    """
    Safety layer that catches physically impossible or constraint-violating
    actions before they touch the world state.
    """

    def __init__(self, world: WorldState):
        self.world = world
        self.violation_count: int = 0

    def validate_dispatch(
        self,
        vehicle_id: str,
        incident_id: str,
        hospital_node: str | None = None,
    ) -> tuple[bool, str]:
        """Returns (is_valid, error_message)."""
        v   = self.world.vehicles.get(vehicle_id)
        inc = self.world.incidents.get(incident_id)

        if not v:
            return self._fail(f"Vehicle '{vehicle_id}' does not exist.")
        if not inc:
            return self._fail(f"Incident '{incident_id}' does not exist.")
        if not v["available"]:
            return self._fail(
                f"Vehicle '{vehicle_id}' is not available (busy until t={v['busy_until']})."
            )
        if inc["resolved"]:
            return self._fail(f"Incident '{incident_id}' is already resolved.")

        missing = set(inc["required_capabilities"]) - set(v["capabilities"])
        if missing:
            return self._fail(
                f"Vehicle '{vehicle_id}' (caps: {v['capabilities']}) lacks required "
                f"capabilities {list(missing)} for incident '{incident_id}'."
            )

        if inc["patients"] > 0 and "patient_transport" in v["capabilities"]:
            if inc["patients"] > v["capacity"] - v["current_load"]:
                return self._fail(
                    f"Vehicle '{vehicle_id}' cannot carry {inc['patients']} patients "
                    f"(capacity remaining: {v['capacity'] - v['current_load']})."
                )

        cost, _ = self.world.dijkstra(v["location"], inc["location"])
        if math.isinf(cost):
            return self._fail(
                f"No passable route from {v['location']} to incident at {inc['location']}. "
                f"Blocked edges: {[list(e) for e in self.world.blocked_edges]}"
            )

        if hospital_node is not None:
            hosp = self.world.nodes.get(hospital_node)
            if not hosp:
                return self._fail(f"Hospital node '{hospital_node}' does not exist on the map.")
            if not hosp["hospital"]:
                return self._fail(f"Node '{hospital_node}' ({hosp['name']}) is not a hospital.")
            if hosp["hospital_current"] >= hosp["hospital_capacity"]:
                return self._fail(
                    f"Hospital at '{hospital_node}' ({hosp['name']}) is at full capacity "
                    f"({hosp['hospital_current']}/{hosp['hospital_capacity']}). Choose another hospital."
                )
            hosp_cost, _ = self.world.dijkstra(inc["location"], hospital_node)
            if math.isinf(hosp_cost):
                return self._fail(
                    f"No passable route from incident at {inc['location']} "
                    f"to hospital at '{hospital_node}'."
                )

        return True, "OK"

    def _fail(self, msg: str) -> tuple[bool, str]:
        self.violation_count += 1
        return False, f"VALIDATOR ERROR: {msg}"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: TOOL SCHEMA  (Anthropic tool_use format)
# ─────────────────────────────────────────────────────────────────────────────

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "get_map_state",
        "description": (
            "Returns the full current city map: all nodes, their connections, "
            "blocked edges, and active alerts."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_vehicles",
        "description": (
            "Returns the current status (location, capabilities, capacity, availability) "
            "of all vehicles."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_incidents",
        "description": (
            "Returns all currently unresolved incidents including type, location, "
            "severity, required capabilities, and deadline."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_shortest_path",
        "description": (
            "Calculates the shortest passable route between two map nodes using "
            "Dijkstra's algorithm. Always call this before dispatching to confirm routes."
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
            },
            "required": ["from_node", "to_node"],
        },
    },
    {
        "name": "dispatch_vehicle",
        "description": (
            "Dispatches a vehicle to handle an incident. "
            "If the vehicle is an ambulance transporting patients, provide hospital_node. "
            "The action will be validated before execution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vehicle_id": {
                    "type": "string",
                    "description": "The vehicle to dispatch (e.g., 'MED_01').",
                },
                "incident_id": {
                    "type": "string",
                    "description": "The incident to respond to (e.g., 'INC_MED_001').",
                },
                "hospital_node": {
                    "type": "string",
                    "description": (
                        "Node ID of the destination hospital for patient transport. "
                        "Omit for non-transport missions."
                    ),
                },
            },
            "required": ["vehicle_id", "incident_id"],
        },
    },
    {
        "name": "report_status",
        "description": (
            "Returns a high-level summary of resolved/unresolved incidents "
            "and vehicle availability."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5: AGENT ORCHESTRATION LOOP (ReAct)
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are the Dynamic Emergency Response Allocation Agent operating inside RescueBench.
Your mission is to resolve all active incidents before their deadlines while respecting physical constraints.

RULES:
1. Always call get_map_state and get_incidents at the start to understand the situation.
2. Always call get_shortest_path before dispatching to verify a route is passable.
3. When dispatching an ambulance carrying patients, ALWAYS provide a hospital_node.
4. If you receive a VALIDATOR ERROR, read it carefully and correct your plan. Never repeat the same invalid action.
5. Reason step-by-step before every dispatch. State your logic explicitly.
6. Prioritize higher-severity incidents, but consider deadlines.
7. Call report_status when you believe all incidents are resolved.
"""


class Agent:
    """
    ReAct agent loop that:
      1. Sends context + tool definitions to Claude
      2. Intercepts tool_use blocks from the response
      3. Runs Validator before executing WorldTool actions
      4. Feeds tool_result blocks back as a user message
      5. Loops until Claude stops calling tools (stop_reason == 'end_turn')
    """

    def __init__(self, scenario: dict, model: str = "claude-sonnet-4-5"):
        self.world      = WorldState(scenario)
        self.world_tool = WorldTool(self.world)
        self.validator  = ValidatorTool(self.world)
        self.model_name = model
        self.step_count = 0
        self.max_steps  = 30  # Safety cap

        # ─── UPDATED: Using the hardcoded API key variable ─────────────────────
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def _dispatch_tool(self, name: str, inputs: dict) -> Any:
        """Routes a tool_use block to the correct WorldTool method."""
        if name == "get_map_state":
            return self.world_tool.get_map_state()
        if name == "get_vehicles":
            return self.world_tool.get_vehicles()
        if name == "get_incidents":
            return self.world_tool.get_incidents()
        if name == "get_shortest_path":
            return self.world_tool.get_shortest_path(**inputs)
        if name == "dispatch_vehicle":
            # Validate BEFORE execution
            valid, err_msg = self.validator.validate_dispatch(
                vehicle_id=inputs["vehicle_id"],
                incident_id=inputs["incident_id"],
                hospital_node=inputs.get("hospital_node"),
            )
            if not valid:
                return {"success": False, "validator_error": err_msg}
            return self.world_tool.dispatch_vehicle(**inputs)
        if name == "report_status":
            return self.world_tool.report_status()
        return {"error": f"Unknown tool: {name}"}

    def _build_initial_message(self) -> str:
        return (
            f"SCENARIO: {self.world.scenario_id}\n"
            "Active Alerts:\n" +
            "\n".join(f"  - {e}" for e in self.world.event_log) +
            "\n\nBegin your emergency response. Use your tools to assess the situation and dispatch resources."
        )

    def run(self) -> dict:
        """Execute the full ReAct loop. Returns a summary dict."""
        print(f"\n{'='*70}")
        print(f"  RescueBench | {self.world.scenario_id} | Model: {self.model_name}")
        print(f"{'='*70}")

        # Conversation history passed in full on every API call (Claude is stateless)
        messages: list[dict] = [
            {"role": "user", "content": self._build_initial_message()}
        ]

        while self.step_count < self.max_steps:
            self.step_count += 1
            print(f"\n[Step {self.step_count}]")

            response = self.client.messages.create(
                model=self.model_name,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            # Append assistant turn to history
            messages.append({"role": "assistant", "content": response.content})

            # ── Parse response blocks ─────────────────────────────────────
            tool_use_blocks: list = []

            for block in response.content:
                if block.type == "text" and block.text:
                    print(f"\n[Agent Reasoning]\n{block.text}")
                if block.type == "tool_use":
                    args = block.input if isinstance(block.input, dict) else {}
                    print(f"\n[Tool Call] {block.name}({json.dumps(args, indent=2)})")
                    tool_use_blocks.append(block)

            # No tool calls → agent finished
            if not tool_use_blocks or response.stop_reason == "end_turn":
                print("\n[Agent] No further tool calls. Mission complete.")
                break

            # ── Execute tools and send tool_result blocks back ────────────
            tool_results: list[dict] = []
            for block in tool_use_blocks:
                result     = self._dispatch_tool(block.name, block.input or {})
                result_str = json.dumps(result, indent=2)
                print(f"\n[Tool Result: {block.name}]\n{result_str}")
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     result_str,
                })

            messages.append({"role": "user", "content": tool_results})

        return compute_metrics(self.world, self.validator, self.step_count, self.model_name)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6: METRICS
# Standalone function that consolidates all evaluation metrics for a run.
# ─────────────────────────────────────────────────────────────────────────────

def compute_metrics(
    world: WorldState,
    validator: ValidatorTool,
    step_count: int,
    model_name: str,
) -> dict:
    """
    Consolidates all RescueBench evaluation metrics into a single dict.

    Metrics
    -------
    priority_weighted_resolution  (PWRS)
        Fraction of total severity weight that was resolved.
        Core benchmark metric — penalises leaving high-severity incidents open.

    resolution_rate
        Simple count-based fraction of incidents resolved, regardless of severity.

    deadline_adherence
        Per-incident flag: was the vehicle dispatched in time to arrive before
        the deadline?  Also reported as an aggregate rate.

    violation_count
        Number of times the Validator rejected a proposed action.
        Lower is better; measures constraint-awareness of the planner.

    step_efficiency
        Incidents resolved per agent step taken.
        Higher is better; rewards concise reasoning chains.
    """
    incidents = world.incidents

    total_weight    = sum(i["severity"]  for i in incidents.values())
    resolved_weight = sum(i["severity"]  for i in incidents.values() if i["resolved"])
    pwrs            = resolved_weight / total_weight if total_weight > 0 else 0.0

    total_incidents = len(incidents)
    resolved_count  = sum(1 for i in incidents.values() if i["resolved"])
    resolution_rate = resolved_count / total_incidents if total_incidents > 0 else 0.0

    deadline_results: dict[str, dict] = {}
    met_count = 0
    for iid, inc in incidents.items():
        if inc["resolved"] and inc.get("resolved_at") is not None:
            met = inc["resolved_at"] <= inc["deadline_minutes"]
            deadline_results[iid] = {
                "resolved":        True,
                "resolved_at_min": inc["resolved_at"],
                "deadline_min":    inc["deadline_minutes"],
                "met_deadline":    met,
            }
            if met:
                met_count += 1
        else:
            deadline_results[iid] = {
                "resolved":     False,
                "met_deadline": False,
            }

    deadline_adherence_rate = met_count / total_incidents if total_incidents > 0 else 0.0

    step_efficiency = resolved_count / step_count if step_count > 0 else 0.0

    scores = {
        "scenario_id":                  world.scenario_id,
        "model":                        model_name,
        "steps_taken":                  step_count,
        "priority_weighted_resolution": round(pwrs, 4),
        "resolution_rate":              round(resolution_rate, 4),
        "deadline_adherence_rate":      round(deadline_adherence_rate, 4),
        "deadline_per_incident":        deadline_results,
        "violation_count":              validator.violation_count,
        "step_efficiency":              round(step_efficiency, 4),
        "incidents_resolved": {
            iid: inc["resolved"] for iid, inc in incidents.items()
        },
    }

    print(f"\n{'='*70}")
    print("  FINAL SCORES")
    print(f"{'='*70}")
    print(json.dumps(scores, indent=2))
    return scores



DEFAULT_GRADE_WEIGHTS = {
    "priority_weighted_resolution": 0.4,
    "resolution_rate": 0.2,
    "deadline_adherence_rate": 0.2,
    "violation_count": 0.1,
    "step_efficiency": 0.1,
}
def grade(metrics, parameter_weights=DEFAULT_GRADE_WEIGHTS):
    """
    Compute a single numeric grade (0-100) from the metrics produced by
    `compute_metrics` using the provided `parameter_weights`.

    Expected `parameter_weights` shape (examples):
      {
        'priority_weighted_resolution': 0.4,
        'resolution_rate': 0.2,
        'deadline_adherence_rate': 0.2,
        'violation_count': 0.1,
        'step_efficiency': 0.1,
        # optional scaling params:
        'violation_max': 10,           # violations at or above this -> 0 score
        'step_efficiency_max': 1.0,    # used to normalize step_efficiency
      }

    Returns a dict with:
      {
        'grade': float,            # 0..100
        'component_scores': {k: score},
        'used_weights': {k: weight},
      }

    The function is defensive: missing weights fall back to sensible defaults
    and unknown keys in `parameter_weights` are ignored.
    """


    weights = {k: float(parameter_weights.get(k, parameter_weights[k])) if isinstance(parameter_weights, dict) and k in parameter_weights else parameter_weights[k] for k in parameter_weights}

    violation_max = float(parameter_weights.get("violation_max", 10)) if isinstance(parameter_weights, dict) else 10.0
    step_eff_max  = float(parameter_weights.get("step_efficiency_max", 1.0)) if isinstance(parameter_weights, dict) else 1.0


    pwrs = float(metrics.get("priority_weighted_resolution", 0.0))
    res_rate = float(metrics.get("resolution_rate", 0.0))
    deadline_rate = float(metrics.get("deadline_adherence_rate", 0.0))
    violations = float(metrics.get("violation_count", 0.0))
    step_eff = float(metrics.get("step_efficiency", 0.0))


    comp_scores: dict[str, float] = {}
    comp_scores["priority_weighted_resolution"] = max(0.0, min(1.0, pwrs))
    comp_scores["resolution_rate"] = max(0.0, min(1.0, res_rate))
    comp_scores["deadline_adherence_rate"] = max(0.0, min(1.0, deadline_rate))


    if violation_max <= 0:
        viol_score = 0.0 if violations > 0 else 1.0
    else:
        viol_score = max(0.0, 1.0 - (violations / violation_max))
    comp_scores["violation_count"] = viol_score

    if step_eff_max <= 0:
        step_score = 0.0
    else:
        step_score = max(0.0, min(1.0, step_eff / step_eff_max))
    comp_scores["step_efficiency"] = step_score


    total_weight = sum(weights.values())
    if total_weight <= 0:
        return {"grade": 0.0, "component_scores": comp_scores, "used_weights": weights}

    weighted_sum = 0.0
    for k, w in weights.items():
        score = comp_scores.get(k, 0.0)
        weighted_sum += w * score

    normalized = weighted_sum / total_weight
    grade_score = round(float(normalized) * 100.0, 2)

    return {"grade": grade_score, "component_scores": comp_scores, "used_weights": weights}

# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    agent = Agent(
        scenario=EXAMPLE_SCENARIO,
        model="claude-sonnet-4-5",  # swap to "claude-opus-4-5" for stronger planning
    )
    final_scores = agent.run()
    print(grade(final_scores))