"""
RescueBench Agent Implementation - Group 2
Dynamic Emergency Response Allocation Agent

Components:
  - WorldState:     Manages the live JSON simulation world (map, vehicles, incidents)
  - WorldTool:      The agent's interface for querying/mutating the simulation
  - ValidatorTool:  Deterministic safety layer that rejects physically impossible actions
  - Agent:          ReAct orchestration loop powered by Google Gemini API
  - Scenario:       Tier 1 "Basic Triage" scenario (no dynamic triggers, simple dispatches)
  - compute_metrics: Standalone function that consolidates all evaluation metrics

Usage:
    pip install google-generativeai
    export GEMINI_API_KEY="your_key_here"
    python3 Agent_Implementation2.py
"""

import os
import json
import math
import heapq
import copy
import re
import time
import warnings
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# GEMINI CONFIG (OPTIONAL)
# ─────────────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = "REDACTED_GEMINI_API_KEY"


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
            "resolved_at": None,
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
        graph: dict[str, list[tuple[str, int]]] = {k: [] for k in self.nodes}
        for a, b, t in self.edges:
            if frozenset([a, b]) not in self.blocked_edges:
                graph[a].append((b, t))
                graph[b].append((a, t))
        return graph

    def dijkstra(self, source: str, target: str) -> tuple[float, list[str]]:
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
# ─────────────────────────────────────────────────────────────────────────────

class WorldTool:
    def __init__(self, world: WorldState):
        self.world = world

    def get_map_state(self) -> dict:
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
        return copy.deepcopy(self.world.vehicles)

    def get_incidents(self) -> dict:
        return {iid: inc for iid, inc in self.world.incidents.items() if not inc["resolved"]}

    def get_shortest_path(self, from_node: str, to_node: str) -> dict:
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
        inc["resolved_at"] = arrival_time
        return result

    def report_status(self) -> dict:
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
# ─────────────────────────────────────────────────────────────────────────────

class ValidatorTool:
    def __init__(self, world: WorldState):
        self.world = world
        self.violation_count: int = 0

    def validate_dispatch(
        self,
        vehicle_id: str,
        incident_id: str,
        hospital_node: str | None = None,
    ) -> tuple[bool, str]:
        v   = self.world.vehicles.get(vehicle_id)
        inc = self.world.incidents.get(incident_id)

        if not v:
            return self._fail(f"Vehicle '{vehicle_id}' does not exist.")
        if not inc:
            return self._fail(f"Incident '{incident_id}' does not exist.")
        if not v["available"]:
            return self._fail(f"Vehicle '{vehicle_id}' is not available (busy until t={v['busy_until']}).")
        if inc["resolved"]:
            return self._fail(f"Incident '{incident_id}' is already resolved.")

        missing = set(inc["required_capabilities"]) - set(v["capabilities"])
        if missing:
            return self._fail(f"Vehicle '{vehicle_id}' lacks required capabilities {list(missing)}.")

        if inc["patients"] > 0 and "patient_transport" in v["capabilities"]:
            if inc["patients"] > v["capacity"] - v["current_load"]:
                return self._fail(f"Vehicle '{vehicle_id}' cannot carry {inc['patients']} patients.")

        cost, _ = self.world.dijkstra(v["location"], inc["location"])
        if math.isinf(cost):
            return self._fail(f"No passable route from {v['location']} to incident.")

        if hospital_node is not None:
            hosp = self.world.nodes.get(hospital_node)
            if not hosp:
                return self._fail(f"Hospital node '{hospital_node}' does not exist.")
            if not hosp["hospital"]:
                return self._fail(f"Node '{hospital_node}' is not a hospital.")
            if hosp["hospital_current"] >= hosp["hospital_capacity"]:
                return self._fail(f"Hospital at '{hospital_node}' is at full capacity.")
            hosp_cost, _ = self.world.dijkstra(inc["location"], hospital_node)
            if math.isinf(hosp_cost):
                return self._fail(f"No passable route from incident to hospital.")

        return True, "OK"

    def _fail(self, msg: str) -> tuple[bool, str]:
        self.violation_count += 1
        return False, f"VALIDATOR ERROR: {msg}"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: TOOL SCHEMA (Gemini Function Declarations Format)
# ─────────────────────────────────────────────────────────────────────────────

GEMINI_TOOLS = [
    {
        "function_declarations": [
            {
                "name": "get_map_state",
                "description": "Returns the full current city map: all nodes, their connections, blocked edges, and active alerts.",
            },
            {
                "name": "get_vehicles",
                "description": "Returns the current status (location, capabilities, capacity, availability) of all vehicles.",
            },
            {
                "name": "get_incidents",
                "description": "Returns all currently unresolved incidents including type, location, severity, required capabilities, and deadline.",
            },
            {
                "name": "get_shortest_path",
                "description": "Calculates the shortest passable route between two map nodes. Always call this before dispatching.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "from_node": {"type": "STRING", "description": "Source node ID (e.g., 'node_depot_main')."},
                        "to_node": {"type": "STRING", "description": "Destination node ID (e.g., 'node_int_08')."}
                    },
                    "required": ["from_node", "to_node"]
                }
            },
            {
                "name": "dispatch_vehicle",
                "description": "Dispatches a vehicle to handle an incident. If the vehicle is an ambulance, provide a hospital_node.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "vehicle_id": {"type": "STRING", "description": "The vehicle to dispatch (e.g., 'MED_01')."},
                        "incident_id": {"type": "STRING", "description": "The incident to respond to (e.g., 'INC_MED_001')."},
                        "hospital_node": {"type": "STRING", "description": "Node ID of the destination hospital for patient transport. Omit if not needed."}
                    },
                    "required": ["vehicle_id", "incident_id"]
                }
            },
            {
                "name": "report_status",
                "description": "Returns a high-level summary of resolved/unresolved incidents and vehicle availability.",
            }
        ]
    }
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
    def __init__(
        self,
        scenario: dict,
        model_name: str = "gemini-1.5-pro",
        use_gemini: bool = True,
        max_llm_calls: int = 30,
        allow_deterministic_fallback: bool = False,
        fallback_models: list[str] | None = None,
        max_retries: int = 3,
    ):
        self.world      = WorldState(scenario)
        self.world_tool = WorldTool(self.world)
        self.validator  = ValidatorTool(self.world)
        self.model_name = model_name
        self.use_gemini = use_gemini
        self.max_llm_calls = max_llm_calls
        self.allow_deterministic_fallback = allow_deterministic_fallback
        self.max_retries = max_retries
        self.step_count = 0
        self.max_steps  = 30
        self.chat = None
        self.model = None
        self.model_candidates = [model_name] + (fallback_models or [])
        # Keep order stable while removing duplicates.
        self.model_candidates = list(dict.fromkeys(self.model_candidates))
        self.active_model_index = 0

        if self.use_gemini:
            if not GEMINI_API_KEY:
                if self.allow_deterministic_fallback:
                    print("[Agent] GEMINI_API_KEY not set. Falling back to deterministic planner.")
                    self.use_gemini = False
                else:
                    raise RuntimeError("GEMINI_API_KEY is required when USE_GEMINI is enabled.")
            else:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", FutureWarning)
                        import google.generativeai as genai
                    genai.configure(api_key=GEMINI_API_KEY)
                    self._genai = genai
                    self._start_chat_for_model(self.model_candidates[self.active_model_index])
                except Exception as exc:
                    if self.allow_deterministic_fallback:
                        print(f"[Agent] Gemini setup failed ({exc}). Falling back to deterministic planner.")
                        self.use_gemini = False
                    else:
                        raise RuntimeError(f"Gemini setup failed: {exc}") from exc

    def _start_chat_for_model(self, model_name: str) -> None:
        self.model_name = model_name
        self.model = self._genai.GenerativeModel(
            model_name=self.model_name,
            tools=GEMINI_TOOLS,
            system_instruction=SYSTEM_PROMPT
        )
        self.chat = self.model.start_chat()
        print(f"[Agent] Using LLM model: {self.model_name}")

    def _switch_to_next_model(self) -> bool:
        if self.active_model_index + 1 >= len(self.model_candidates):
            return False
        self.active_model_index += 1
        next_model = self.model_candidates[self.active_model_index]
        print(f"[Agent] Switching to fallback LLM model: {next_model}")
        self._start_chat_for_model(next_model)
        return True

    @staticmethod
    def _retry_delay_seconds(exc: Exception) -> int:
        msg = str(exc).lower()
        match = re.search(r"retry in\s+([0-9]+(?:\.[0-9]+)?)s", msg)
        if not match:
            return 5
        return max(1, int(float(match.group(1))))

    def _send_with_retries(self, payload: Any, allow_model_switch: bool = False) -> Any:
        last_exc = None
        max_attempts = max(1, self.max_retries) + (max(0, len(self.model_candidates) - 1) if allow_model_switch else 0)
        for attempt in range(1, max_attempts + 1):
            try:
                return self.chat.send_message(payload)
            except Exception as exc:
                last_exc = exc
                if self._is_quota_or_rate_error(exc):
                    # Only switch models at startup; mid-conversation switches break chat history.
                    if allow_model_switch and self._switch_to_next_model():
                        continue
                    if attempt < max_attempts:
                        delay = self._retry_delay_seconds(exc)
                        print(f"[Agent] LLM throttled: {str(exc)[:200]}")
                        print(f"[Agent] Retrying in {delay}s (attempt {attempt}/{max_attempts}).")
                        time.sleep(delay)
                        continue
                raise
        raise RuntimeError(f"Gemini request failed after retries: {last_exc}") from last_exc

    def _dispatch_tool(self, name: str, inputs: dict) -> Any:
        if name == "get_map_state":
            return self.world_tool.get_map_state()
        if name == "get_vehicles":
            return self.world_tool.get_vehicles()
        if name == "get_incidents":
            return self.world_tool.get_incidents()
        if name == "get_shortest_path":
            return self.world_tool.get_shortest_path(**inputs)
        if name == "dispatch_vehicle":
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

    def _select_hospital(self, incident_node: str) -> str | None:
        best_node = None
        best_cost = math.inf
        for node_id, node in self.world.nodes.items():
            if not node.get("hospital"):
                continue
            if node["hospital_current"] >= node["hospital_capacity"]:
                continue
            cost, _ = self.world.dijkstra(incident_node, node_id)
            if cost < best_cost:
                best_cost = cost
                best_node = node_id
        return best_node

    def _select_vehicle(self, incident_id: str) -> tuple[str | None, str | None]:
        inc = self.world.incidents[incident_id]
        best_vehicle = None
        best_cost = math.inf

        for vehicle_id, v in self.world.vehicles.items():
            if not v["available"]:
                continue
            missing = set(inc["required_capabilities"]) - set(v["capabilities"])
            if missing:
                continue
            if inc["patients"] > 0 and "patient_transport" in v["capabilities"]:
                if inc["patients"] > v["capacity"] - v["current_load"]:
                    continue

            cost, _ = self.world.dijkstra(v["location"], inc["location"])
            if cost < best_cost:
                best_cost = cost
                best_vehicle = vehicle_id

        if best_vehicle is None:
            return None, None

        hospital_node = None
        vehicle = self.world.vehicles[best_vehicle]
        if inc["patients"] > 0 and "patient_transport" in vehicle["capabilities"]:
            hospital_node = self._select_hospital(inc["location"])
        return best_vehicle, hospital_node

    def _run_deterministic(self, start_step: int = 0) -> dict:
        print("\n[Agent] Running deterministic dispatch planner (no LLM calls).")

        local_steps = 0
        while local_steps < self.max_steps:
            incidents = self.world_tool.get_incidents()
            if not incidents:
                break

            # Prioritize severity first, then tighter deadlines.
            ranked = sorted(
                incidents.items(),
                key=lambda kv: (-kv[1]["severity"], kv[1]["deadline_minutes"])
            )

            dispatched = False
            for incident_id, _inc in ranked:
                vehicle_id, hospital_node = self._select_vehicle(incident_id)
                if vehicle_id is None:
                    continue

                valid, err_msg = self.validator.validate_dispatch(
                    vehicle_id=vehicle_id,
                    incident_id=incident_id,
                    hospital_node=hospital_node,
                )
                if not valid:
                    print(f"[Deterministic] Skipping invalid action: {err_msg}")
                    continue

                result = self.world_tool.dispatch_vehicle(
                    vehicle_id=vehicle_id,
                    incident_id=incident_id,
                    hospital_node=hospital_node,
                )
                local_steps += 1
                print(
                    f"[Deterministic] Dispatch {vehicle_id} -> {incident_id} | "
                    f"success={result.get('success', False)}"
                )
                dispatched = True
                break

            if not dispatched:
                print("[Deterministic] No valid dispatches possible for remaining incidents.")
                break

        self.step_count = max(self.step_count, start_step + local_steps)
        return compute_metrics(self.world, self.validator, self.step_count, self.model_name)

    @staticmethod
    def _is_quota_or_rate_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        signals = [
            "resource_exhausted",
            "quota",
            "rate limit",
            "429",
            "retry in",
        ]
        return any(token in msg for token in signals)

    def run(self) -> dict:
        print(f"\n{'='*70}")
        print(f"  RescueBench | {self.world.scenario_id} | Model: {self.model_name}")
        print(f"{'='*70}")

        if not self.use_gemini:
            return self._run_deterministic()

        llm_calls = 0
        try:
            # Send initial prompt to kick off the loop (allow model switching at startup)
            response = self._send_with_retries(self._build_initial_message(), allow_model_switch=True)
            llm_calls += 1
        except Exception as exc:
            print(f"[Agent] Gemini call failed at startup: {exc}")
            if self.allow_deterministic_fallback and self._is_quota_or_rate_error(exc):
                print("[Agent] Quota/rate limit detected. Switching to deterministic planner.")
                return self._run_deterministic()
            raise

        while self.step_count < self.max_steps:
            self.step_count += 1
            print(f"\n[Step {self.step_count}]")

            function_calls = []
            
            # Gemini returns parts which can be text, function calls, or both
            for part in response.parts:
                if part.text:
                    print(f"\n[Agent Reasoning]\n{part.text}")
                if part.function_call:
                    function_calls.append(part.function_call)

            # If the model didn't call any tools, it's finished reasoning
            if not function_calls:
                print("\n[Agent] No further tool calls. Mission complete.")
                break

            # Execute tools and prepare the results to send back
            tool_responses = []
            for fc in function_calls:
                name = fc.name
                
                # Convert the protobuf arguments into a standard Python dictionary
                args = {k: v for k, v in fc.args.items()} if fc.args else {}
                
                print(f"\n[Tool Call] {name}({json.dumps(args, indent=2)})")
                
                result = self._dispatch_tool(name, args)
                print(f"\n[Tool Result: {name}]\n{json.dumps(result, indent=2)}")
                
                # Gemini expects function results wrapped in this specific format
                tool_responses.append({
                    "function_response": {
                        "name": name, 
                        "response": result
                    }
                })

            if llm_calls >= self.max_llm_calls:
                if self.allow_deterministic_fallback:
                    print(
                        f"\n[Agent] Reached max_llm_calls={self.max_llm_calls}. "
                        "Switching to deterministic planner to reduce API usage."
                    )
                    return self._run_deterministic(start_step=self.step_count)
                raise RuntimeError(
                    f"Reached max_llm_calls={self.max_llm_calls}. "
                    "Increase MAX_LLM_CALLS to continue using only LLM mode."
                )

            # Send the tool outputs back to Gemini so it can continue planning (no model switch; chat history matters)
            try:
                response = self._send_with_retries(tool_responses, allow_model_switch=False)
                llm_calls += 1
            except Exception as exc:
                print(f"[Agent] Gemini call failed during loop: {exc}")
                if self.allow_deterministic_fallback and self._is_quota_or_rate_error(exc):
                    print("[Agent] Quota/rate limit detected. Switching to deterministic planner.")
                    return self._run_deterministic(start_step=self.step_count)
                raise

        return compute_metrics(self.world, self.validator, self.step_count, self.model_name)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6: METRICS
# ─────────────────────────────────────────────────────────────────────────────

def compute_metrics(
    world: WorldState,
    validator: ValidatorTool,
    step_count: int,
    model_name: str,
) -> dict:
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
            deadline_results[iid] = {"resolved": False, "met_deadline": False}

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


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    use_gemini_env = os.getenv("USE_GEMINI", "1").strip().lower() in {"1", "true", "yes", "on"}
    max_llm_calls_env = int(os.getenv("MAX_LLM_CALLS", "30"))
    allow_det_fallback_env = os.getenv("ALLOW_DETERMINISTIC_FALLBACK", "0").strip().lower() in {"1", "true", "yes", "on"}
    max_retries_env = int(os.getenv("GEMINI_MAX_RETRIES", "3"))
    model_name_env = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
    fallback_models_env = [
        m.strip() for m in os.getenv(
            "GEMINI_FALLBACK_MODELS",
            "gemini-2.0-flash-lite,gemini-2.5-flash"
        ).split(",") if m.strip()
    ]

    agent = Agent(
        scenario=EXAMPLE_SCENARIO,
        model_name=model_name_env,
        use_gemini=use_gemini_env,
        max_llm_calls=max_llm_calls_env,
        allow_deterministic_fallback=allow_det_fallback_env,
        fallback_models=fallback_models_env,
        max_retries=max_retries_env,
    )
    final_scores = agent.run()