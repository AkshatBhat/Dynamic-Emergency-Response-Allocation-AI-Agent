"""
RescueBench Benchmark Runner
Group 2 — CS 498, UIUC

Comprehensive evaluation harness for the RescueBench emergency-response agent
across all 20 benchmark scenarios (Tier 1-4) in four evaluation modes:
  - deterministic : Greedy rule-based planner (no API needed)
  - react         : Full ReAct loop with ValidatorTool
  - zero_shot     : Single LLM prompt → parse JSON dispatch list → execute
  - ablated       : ReAct loop WITHOUT ValidatorTool

Key enhancements over the base agent:
  1. JSON scenario loader — converts benchmark JSON to internal WorldState format
  2. Vehicle-type-aware Dijkstra — respects per-edge allowed_vehicle_types
  3. Multi-dispatch per incident — tracks covered_capabilities; resolves when
     ALL required capabilities are covered
  4. Dynamic trigger support — triggers fire as simulation clock advances
  5. Cap-PWRS metric — partial credit for partially-covered multi-cap incidents

Usage:
  python run_benchmark.py --mode all --tier all --runs 3
  python run_benchmark.py --mode react --tier 1 --api-key sk-ant-...
  python run_benchmark.py --mode deterministic --tier 2
"""

import os
import json
import math
import heapq
import copy
import re
import time
import argparse
import glob
from typing import Any

# Load .env automatically if present (never required — env vars also work)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: BENCHMARK FILE PATHS
# ─────────────────────────────────────────────────────────────────────────────

BENCHMARK_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "benchmark")

TIER_DIRS = {
    1: "tier1_basic_triage",
    2: "tier2_constraint_satisfaction",
    3: "tier3_ethical_prioritization",
    4: "tier4_dynamic_replanning",
}


def get_scenario_files(tier: int) -> list[str]:
    """Return sorted list of JSON scenario file paths for the given tier."""
    tier_dir = os.path.join(BENCHMARK_BASE, TIER_DIRS[tier])
    files = sorted(glob.glob(os.path.join(tier_dir, "*.json")))
    return files


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: JSON SCENARIO LOADER
# Converts the benchmark JSON format into the internal WorldState dict format.
# ─────────────────────────────────────────────────────────────────────────────

def load_scenario(json_path: str) -> dict:
    """
    Load a benchmark JSON file and convert it into the internal scenario dict
    format consumed by WorldState.

    The benchmark JSON uses:
      - nodes[]           → array of {id, type, current_capacity}
      - edges[]           → array of {id, source_node, target_node,
                                       base_travel_time, status,
                                       allowed_vehicle_types}
      - active_fleet[]    → array of vehicle objects
      - incidents[]       → array of incident objects
      - dynamic_triggers[]→ array of trigger objects
      - vehicle_classes   → dict of vehicle type definitions

    Internal format (WorldState.__init__ keys):
      scenario_id, name, description, current_time,
      edges_raw (list of dicts, kept as-is for vehicle-aware Dijkstra),
      nodes (dict), vehicles (dict), incidents (dict),
      dynamic_triggers (list), vehicle_classes (dict)
    """
    with open(json_path, "r") as fh:
        raw = json.load(fh)

    meta = raw.get("metadata", {})
    scenario_id = os.path.splitext(os.path.basename(json_path))[0]

    # ── Nodes ────────────────────────────────────────────────────────────────
    nodes: dict = {}
    for n in raw.get("nodes", []):
        nid = n["id"]
        ntype = n.get("type", "standard_intersection")
        nodes[nid] = {
            "id": nid,
            "type": ntype,
            "hospital": ntype == "hospital",
            "hospital_capacity": n.get("current_capacity", 0) if ntype == "hospital" else 0,
            "hospital_current": 0,
            "current_capacity": n.get("current_capacity", 0),
        }

    # ── Vehicle classes ───────────────────────────────────────────────────────
    vehicle_classes: dict = raw.get("vehicle_classes", {})

    # ── Fleet ────────────────────────────────────────────────────────────────
    vehicles: dict = {}
    for v in raw.get("active_fleet", []):
        vtype = v["vehicle_type"]
        vc = vehicle_classes.get(vtype, {})
        vehicles[v["unit_id"]] = {
            "type": vtype,
            "location": v["current_location"],
            "home_depot": v.get("home_depot", v["current_location"]),
            "capacity": vc.get("max_capacity", 0),
            "current_load": v.get("current_capacity_used", 0),
            "capabilities": list(vc.get("capabilities", [])),
            "speed_multiplier": vc.get("speed_multiplier", 1.0),
            "available": v.get("status", "idle") == "idle",
            "busy_until": 0,
            "fuel": v.get("current_fuel", 100),
        }

    # ── Incidents ─────────────────────────────────────────────────────────────
    incidents: dict = {}
    for inc in raw.get("incidents", []):
        incidents[inc["incident_id"]] = {
            "type": inc["type"],
            "location": inc["location_node"],
            "severity": inc["severity_weight"],
            "patients": inc.get("required_capacity", 0),
            "required_capabilities": list(inc["required_capabilities"]),
            "deadline_minutes": inc["deadline_min"],
            "resolved": False,
            "resolved_at": None,
            "covered_capabilities": [],   # tracks partial coverage (multi-dispatch)
        }

    # ── Edges (stored as raw dicts for vehicle-type-aware routing) ────────────
    edges_raw: list[dict] = copy.deepcopy(raw.get("edges", []))

    # ── Dynamic triggers ──────────────────────────────────────────────────────
    dynamic_triggers: list[dict] = []
    for t in raw.get("dynamic_triggers", []):
        dynamic_triggers.append({
            "trigger_time": t["trigger_time"],
            "event_type": t.get("event_type", "unknown"),
            "target_edge": t.get("target_edge", ""),
            "new_status": t.get("new_status", "blocked"),
            "message": t.get("message_to_agent", ""),
            "fired": False,
        })

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


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: ENHANCED WORLD STATE
# Adds vehicle-type-aware routing, multi-dispatch tracking, and dynamic triggers.
# ─────────────────────────────────────────────────────────────────────────────

class WorldState:
    """
    Mutable live simulation state.

    Enhancements over the base WorldState:
      - build_graph(vehicle_type) respects allowed_vehicle_types per edge
      - dijkstra(src, tgt, vehicle_type) uses vehicle-specific graph
      - Incidents track covered_capabilities; resolved when all required caps covered
      - advance_clock(t) fires dynamic triggers at the correct wall-clock time
    """

    def __init__(self, scenario: dict):
        self.scenario_id: str = scenario["scenario_id"]
        self.name: str = scenario["name"]
        self.current_time: float = scenario["current_time"]

        self.edges_raw: list[dict] = copy.deepcopy(scenario["edges_raw"])
        # Map edge_id → edge dict for fast trigger updates
        self._edge_by_id: dict[str, dict] = {e["id"]: e for e in self.edges_raw}

        self.nodes: dict = copy.deepcopy(scenario["nodes"])
        self.vehicles: dict = copy.deepcopy(scenario["vehicles"])
        self.incidents: dict = copy.deepcopy(scenario["incidents"])
        self.dynamic_triggers: list[dict] = copy.deepcopy(scenario["dynamic_triggers"])
        self.event_log: list[str] = []

    # ── Graph construction ────────────────────────────────────────────────────

    def build_graph(self, vehicle_type: str | None = None) -> dict[str, list[tuple[str, float]]]:
        """
        Build an undirected adjacency list.
        If vehicle_type is given, only include edges that list it in allowed_vehicle_types.
        Blocked edges (status != 'clear') are excluded entirely.
        """
        graph: dict[str, list[tuple[str, float]]] = {nid: [] for nid in self.nodes}
        for e in self.edges_raw:
            if e.get("status", "clear") != "clear":
                continue
            if vehicle_type and vehicle_type not in e.get("allowed_vehicle_types", []):
                continue
            src, tgt, t = e["source_node"], e["target_node"], e["base_travel_time"]
            if src in graph:
                graph[src].append((tgt, t))
            if tgt in graph:
                graph[tgt].append((src, t))
        return graph

    def dijkstra(
        self,
        source: str,
        target: str,
        vehicle_type: str | None = None,
    ) -> tuple[float, list[str]]:
        """
        Shortest path with vehicle-type-aware graph.
        Returns (cost, path).  cost == math.inf means unreachable.
        """
        graph = self.build_graph(vehicle_type)
        dist = {n: math.inf for n in graph}
        prev: dict[str, str | None] = {n: None for n in graph}
        if source not in dist:
            return math.inf, []
        dist[source] = 0.0
        pq: list[tuple[float, str]] = [(0.0, source)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            if u == target:
                break
            for v, w in graph.get(u, []):
                nd = dist[u] + w
                if nd < dist[v]:
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))
        if math.isinf(dist.get(target, math.inf)):
            return math.inf, []
        path: list[str] = []
        cur: str | None = target
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        path.reverse()
        return dist[target], path

    # ── Multi-dispatch incident resolution ────────────────────────────────────

    def cover_incident(self, incident_id: str, capabilities: list[str]) -> bool:
        """
        Record that a vehicle with *capabilities* has been dispatched to *incident_id*.
        Updates covered_capabilities.
        Returns True if the incident is now fully resolved (all required caps covered).
        """
        inc = self.incidents.get(incident_id)
        if not inc or inc["resolved"]:
            return False
        # Add any new capabilities this vehicle contributes
        current = set(inc["covered_capabilities"])
        required = set(inc["required_capabilities"])
        new_covered = current | (set(capabilities) & required)
        inc["covered_capabilities"] = list(new_covered)
        # Check if fully covered
        if required <= new_covered:
            return True
        return False

    # ── Dynamic trigger processing ────────────────────────────────────────────

    def advance_clock(self, new_time: float) -> list[str]:
        """
        Advance the simulation clock to *new_time*, firing any triggers that
        are scheduled at or before the new time.
        Returns list of alert messages from fired triggers.
        """
        alerts: list[str] = []
        self.current_time = new_time
        for trigger in self.dynamic_triggers:
            if trigger["fired"]:
                continue
            if trigger["trigger_time"] <= self.current_time:
                self._fire_trigger(trigger)
                trigger["fired"] = True
                if trigger["message"]:
                    alerts.append(trigger["message"])
                    self.event_log.append(trigger["message"])
        return alerts

    def _fire_trigger(self, trigger: dict) -> None:
        """Apply a dynamic trigger's effect to the world."""
        edge_id = trigger.get("target_edge", "")
        if edge_id and edge_id in self._edge_by_id:
            self._edge_by_id[edge_id]["status"] = trigger.get("new_status", "blocked")

    # ── Convenience queries ───────────────────────────────────────────────────

    def open_incidents(self) -> dict:
        """Return all unresolved incidents."""
        return {iid: inc for iid, inc in self.incidents.items() if not inc["resolved"]}

    def available_vehicles(self) -> dict:
        """Return all available (idle) vehicles."""
        return {vid: v for vid, v in self.vehicles.items() if v["available"]}


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: WORLD TOOL
# Agent-facing interface for querying / mutating the simulation.
# ─────────────────────────────────────────────────────────────────────────────

class WorldTool:
    """Exposes simulation state to the agent via structured function calls."""

    def __init__(self, world: WorldState):
        self.world = world

    def get_map_state(self) -> dict:
        graph = self.world.build_graph()
        return {
            "nodes": {
                nid: {**ndata, "connections": [n for n, _ in graph.get(nid, [])]}
                for nid, ndata in self.world.nodes.items()
            },
            "blocked_edges": [
                e["id"] for e in self.world.edges_raw if e.get("status", "clear") != "clear"
            ],
            "active_alerts": list(self.world.event_log),
        }

    def get_vehicles(self) -> dict:
        return copy.deepcopy(self.world.vehicles)

    def get_incidents(self) -> dict:
        return {
            iid: {
                **inc,
                "uncovered_capabilities": list(
                    set(inc["required_capabilities"]) - set(inc.get("covered_capabilities", []))
                ),
            }
            for iid, inc in self.world.incidents.items()
            if not inc["resolved"]
        }

    def get_shortest_path(self, from_node: str, to_node: str, vehicle_type: str | None = None) -> dict:
        cost, path = self.world.dijkstra(from_node, to_node, vehicle_type)
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
        Dispatch a vehicle to an incident. Supports multi-dispatch: if a vehicle
        covers only SOME required capabilities, the incident remains open for
        additional units to cover remaining capabilities.
        """
        v = self.world.vehicles.get(vehicle_id)
        inc = self.world.incidents.get(incident_id)
        if not v or not inc:
            return {
                "success": False,
                "error": f"Unknown vehicle '{vehicle_id}' or incident '{incident_id}'.",
            }

        vtype = v.get("type")
        cost, path = self.world.dijkstra(v["location"], inc["location"], vtype)
        if math.isinf(cost):
            return {
                "success": False,
                "error": f"No passable route from {v['location']} to {inc['location']} "
                         f"for vehicle type '{vtype}'.",
            }

        arrival_time = self.world.current_time + cost

        # Advance the simulation clock to the vehicle's arrival time.
        # This fires any dynamic triggers that occur during transit.
        alerts = self.world.advance_clock(arrival_time)

        result: dict = {
            "success": True,
            "vehicle_id": vehicle_id,
            "incident_id": incident_id,
            "route": path,
            "travel_time_minutes": cost,
            "arrival_time": arrival_time,
        }
        if alerts:
            result["dynamic_alerts"] = alerts

        # Update vehicle state
        v["available"] = False
        v["busy_until"] = arrival_time
        v["location"] = inc["location"]

        # Multi-dispatch: update covered capabilities for the incident
        now_resolved = self.world.cover_incident(incident_id, v["capabilities"])
        if now_resolved:
            inc["resolved"] = True
            inc["resolved_at"] = arrival_time
            result["incident_resolved"] = True
        else:
            result["incident_resolved"] = False
            result["covered_so_far"] = list(inc["covered_capabilities"])
            result["still_needed"] = list(
                set(inc["required_capabilities"]) - set(inc["covered_capabilities"])
            )

        # Hospital routing for patient transport
        if "patient_transport" in v["capabilities"] and inc["patients"] > 0:
            if hospital_node:
                hosp = self.world.nodes.get(hospital_node)
                if hosp and hosp.get("hospital"):
                    hosp_cost, hosp_path = self.world.dijkstra(
                        inc["location"], hospital_node, vtype
                    )
                    if not math.isinf(hosp_cost):
                        result["route_to_hospital"] = hosp_path
                        result["hospital_travel_time_minutes"] = hosp_cost
                        result["total_trip_time"] = cost + hosp_cost
                    else:
                        result["hospital_route_error"] = (
                            f"No route from {inc['location']} to {hospital_node} "
                            f"for vehicle type '{vtype}'."
                        )
                else:
                    result["hospital_route_error"] = f"Node '{hospital_node}' is not a hospital."
            else:
                result["warning"] = (
                    "Ambulance dispatched to patient incident but no hospital_node given."
                )

        return result

    def report_status(self) -> dict:
        resolved = [iid for iid, i in self.world.incidents.items() if i["resolved"]]
        unresolved = [iid for iid, i in self.world.incidents.items() if not i["resolved"]]
        available = [vid for vid, v in self.world.vehicles.items() if v["available"]]
        return {
            "resolved_incidents": resolved,
            "unresolved_incidents": unresolved,
            "available_vehicles": available,
            "current_time": self.world.current_time,
            "active_alerts": list(self.world.event_log),
        }


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5: VALIDATOR TOOL (Multi-vehicle aware version)
# Checks a proposed dispatch is physically and logically valid.
#
# Key change from single-dispatch validator:
#   Instead of requiring the vehicle to have ALL required capabilities,
#   we only require that the vehicle contributes AT LEAST ONE capability
#   that is still UNCOVERED for that incident. This enables sequential
#   multi-vehicle dispatch for multi-capability incidents.
# ─────────────────────────────────────────────────────────────────────────────

class ValidatorTool:
    """Deterministic safety layer — runs BEFORE WorldTool mutates state."""

    def __init__(self, world: WorldState):
        self.world = world
        self.violation_count: int = 0

    def validate_dispatch(
        self,
        vehicle_id: str,
        incident_id: str,
        hospital_node: str | None = None,
    ) -> tuple[bool, str]:
        v = self.world.vehicles.get(vehicle_id)
        inc = self.world.incidents.get(incident_id)

        if not v:
            return self._fail(f"Vehicle '{vehicle_id}' does not exist.")
        if not inc:
            return self._fail(f"Incident '{incident_id}' does not exist.")
        if not v["available"]:
            return self._fail(
                f"Vehicle '{vehicle_id}' is busy until t={v['busy_until']:.1f}."
            )
        if inc["resolved"]:
            return self._fail(f"Incident '{incident_id}' is already fully resolved.")

        # Multi-vehicle check: vehicle must cover at least one UNCOVERED required cap
        required = set(inc["required_capabilities"])
        already_covered = set(inc.get("covered_capabilities", []))
        still_needed = required - already_covered
        vehicle_caps = set(v["capabilities"])
        contribution = vehicle_caps & still_needed
        if not contribution:
            return self._fail(
                f"Vehicle '{vehicle_id}' (caps: {sorted(vehicle_caps)}) contributes "
                f"nothing new to incident '{incident_id}'. "
                f"Still needed: {sorted(still_needed)}. "
                f"Already covered: {sorted(already_covered)}."
            )

        # Capacity check for patient transport
        if inc["patients"] > 0 and "patient_transport" in v["capabilities"]:
            available_cap = v["capacity"] - v["current_load"]
            if inc["patients"] > available_cap:
                return self._fail(
                    f"Vehicle '{vehicle_id}' cannot carry {inc['patients']} patients "
                    f"(available capacity: {available_cap})."
                )

        # Route reachability (vehicle-type-aware)
        vtype = v.get("type")
        cost, _ = self.world.dijkstra(v["location"], inc["location"], vtype)
        if math.isinf(cost):
            return self._fail(
                f"No passable route from {v['location']} to {inc['location']} "
                f"for vehicle type '{vtype}'."
            )

        # Hospital validation
        if hospital_node is not None:
            hosp = self.world.nodes.get(hospital_node)
            if not hosp:
                return self._fail(f"Hospital node '{hospital_node}' does not exist.")
            if not hosp.get("hospital"):
                return self._fail(f"Node '{hospital_node}' is not a hospital.")
            if hosp["hospital_current"] >= hosp["hospital_capacity"] and hosp["hospital_capacity"] > 0:
                return self._fail(
                    f"Hospital '{hospital_node}' is at full capacity "
                    f"({hosp['hospital_current']}/{hosp['hospital_capacity']})."
                )
            hosp_cost, _ = self.world.dijkstra(inc["location"], hospital_node, vtype)
            if math.isinf(hosp_cost):
                return self._fail(
                    f"No route from {inc['location']} to hospital '{hospital_node}' "
                    f"for vehicle type '{vtype}'."
                )

        return True, "OK"

    def _fail(self, msg: str) -> tuple[bool, str]:
        self.violation_count += 1
        return False, f"VALIDATOR ERROR: {msg}"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6: METRICS COMPUTATION
# PWRS: traditional (resolved/total severity weight)
# Cap-PWRS: partial credit for partial capability coverage
# ─────────────────────────────────────────────────────────────────────────────

def compute_metrics(
    world: WorldState,
    validator: ValidatorTool,
    step_count: int,
    mode: str,
) -> dict:
    """
    Compute all RescueBench evaluation metrics for a completed run.

    Metrics
    -------
    PWRS (Priority-Weighted Resolution Score):
        sum(severity_i * resolved_i) / sum(severity_i)
        Binary — incident is either resolved (1) or not (0).

    Cap-PWRS (Capability-Coverage PWRS):
        For each incident:
            capability_coverage_i = |covered_caps_i ∩ required_caps_i| / |required_caps_i|
        Cap-PWRS = sum(severity_i * capability_coverage_i) / sum(severity_i)
        Gives partial credit for multi-vehicle progress on multi-cap incidents.

    resolution_rate: count-based fraction of incidents resolved.

    deadline_adherence: fraction of incidents whose assigned vehicle arrived
        at or before the deadline.

    violation_count: number of Validator rejections (0 for deterministic).

    step_efficiency: incidents_resolved / steps_taken (higher = more concise).
    """
    incidents = world.incidents
    total_weight = sum(i["severity"] for i in incidents.values())

    # ── PWRS (deadline-aware binary, per benchmark paper definition) ─────────
    # I_i = 1 only if resolved AND arrived before deadline (benchmark paper §4)
    resolved_weight = sum(
        i["severity"] for i in incidents.values()
        if i["resolved"] and i.get("resolved_at") is not None
        and i["resolved_at"] <= i["deadline_minutes"]
    )
    pwrs = resolved_weight / total_weight if total_weight > 0 else 0.0

    # ── Cap-PWRS (partial credit, deadline-aware) ─────────────────────────────
    # Partial credit for capability coverage, zeroed out if deadline exceeded.
    cap_pwrs_numerator = 0.0
    for inc in incidents.values():
        required = set(inc["required_capabilities"])
        covered = set(inc.get("covered_capabilities", []))
        cap_coverage = len(required & covered) / len(required) if required else 1.0
        # Penalize deadline miss: if fully resolved but late, treat as partial
        if inc["resolved"] and inc.get("resolved_at") is not None:
            if inc["resolved_at"] > inc["deadline_minutes"]:
                lateness = inc["resolved_at"] - inc["deadline_minutes"]
                grace_window = inc["deadline_minutes"]
                time_penalty = max(0.0, 1.0 - (lateness / grace_window))
                cap_coverage *= time_penalty
        cap_pwrs_numerator += inc["severity"] * cap_coverage
    cap_pwrs = cap_pwrs_numerator / total_weight if total_weight > 0 else 0.0

    # ── Resolution rate ────────────────────────────────────────────────────────
    total_incidents = len(incidents)
    resolved_count = sum(1 for i in incidents.values() if i["resolved"])
    resolution_rate = resolved_count / total_incidents if total_incidents > 0 else 0.0

    # ── Deadline adherence ────────────────────────────────────────────────────
    met_count = 0
    deadline_details: dict = {}
    for iid, inc in incidents.items():
        if inc["resolved"] and inc.get("resolved_at") is not None:
            met = inc["resolved_at"] <= inc["deadline_minutes"]
            if met:
                met_count += 1
            deadline_details[iid] = {
                "resolved": True,
                "resolved_at": inc["resolved_at"],
                "deadline": inc["deadline_minutes"],
                "met_deadline": met,
            }
        else:
            deadline_details[iid] = {"resolved": False, "met_deadline": False}

    deadline_adherence = met_count / total_incidents if total_incidents > 0 else 0.0

    # ── Step efficiency ────────────────────────────────────────────────────────
    step_efficiency = resolved_count / step_count if step_count > 0 else 0.0

    return {
        "scenario_id": world.scenario_id,
        "mode": mode,
        "steps_taken": step_count,
        "pwrs": round(pwrs, 4),
        "cap_pwrs": round(cap_pwrs, 4),
        "resolution_rate": round(resolution_rate, 4),
        "deadline_adherence": round(deadline_adherence, 4),
        "violation_count": validator.violation_count,
        "step_efficiency": round(step_efficiency, 4) if mode != "zero_shot" else None,
        "deadline_per_incident": deadline_details,
        "incidents_resolved": {iid: i["resolved"] for iid, i in incidents.items()},
    }


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7: DETERMINISTIC PLANNER
# Greedy rule-based dispatcher — no LLM required.
# Sort incidents by (severity DESC, deadline ASC).
# For each incident, find the nearest available vehicle that contributes
# at least one uncovered required capability.
# ─────────────────────────────────────────────────────────────────────────────

def run_deterministic(scenario_dict: dict) -> dict:
    """
    Run the greedy deterministic planner on a scenario.

    Algorithm:
      1. Rank open incidents by (severity DESC, deadline ASC)
      2. For the top incident, find the nearest idle vehicle that contributes
         at least one uncovered capability
      3. Dispatch (no validation needed — the planner is inherently valid)
      4. Repeat until all incidents resolved or no valid dispatches remain
    """
    world = WorldState(scenario_dict)
    world_tool = WorldTool(world)
    validator = ValidatorTool(world)
    step_count = 0
    max_steps = 100  # safety cap

    while step_count < max_steps:
        open_incs = world.open_incidents()
        if not open_incs:
            break

        # Rank by severity DESC, deadline ASC
        ranked = sorted(
            open_incs.items(),
            key=lambda kv: (-kv[1]["severity"], kv[1]["deadline_minutes"]),
        )

        dispatched = False
        for incident_id, inc in ranked:
            already_covered = set(inc.get("covered_capabilities", []))
            still_needed = set(inc["required_capabilities"]) - already_covered

            if not still_needed:
                # All capabilities covered, mark resolved
                inc["resolved"] = True
                inc["resolved_at"] = world.current_time
                dispatched = True
                break

            # Find the nearest available vehicle that contributes to still_needed
            best_vehicle_id: str | None = None
            best_cost: float = math.inf
            best_hospital: str | None = None

            for vid, v in world.vehicles.items():
                if not v["available"]:
                    continue
                vtype = v.get("type")
                vehicle_caps = set(v["capabilities"])
                contribution = vehicle_caps & still_needed
                if not contribution:
                    continue

                # Check capacity for patient transport
                if inc["patients"] > 0 and "patient_transport" in vehicle_caps:
                    if inc["patients"] > v["capacity"] - v["current_load"]:
                        continue

                cost, _ = world.dijkstra(v["location"], inc["location"], vtype)
                if math.isinf(cost):
                    continue

                if cost < best_cost:
                    best_cost = cost
                    best_vehicle_id = vid

                    # Determine hospital if needed
                    if "patient_transport" in vehicle_caps and inc["patients"] > 0:
                        hosp_node = _nearest_hospital(world, inc["location"], vtype)
                        best_hospital = hosp_node

            if best_vehicle_id is None:
                continue  # No vehicle can help this incident right now

            # Execute dispatch
            result = world_tool.dispatch_vehicle(
                vehicle_id=best_vehicle_id,
                incident_id=incident_id,
                hospital_node=best_hospital,
            )
            step_count += 1
            resolved_flag = result.get("incident_resolved", result.get("success", False))
            print(
                f"  [Deterministic] {best_vehicle_id} → {incident_id} | "
                f"t={best_cost:.1f}min | resolved={resolved_flag}"
            )
            dispatched = True
            break  # Re-rank after each dispatch

        if not dispatched:
            print("  [Deterministic] No valid dispatches possible; stopping.")
            break

    return compute_metrics(world, validator, step_count, "deterministic")


def _nearest_hospital(world: WorldState, from_node: str, vtype: str | None) -> str | None:
    """Return the nearest open hospital node, or None if none reachable."""
    best_node: str | None = None
    best_cost: float = math.inf
    for nid, nd in world.nodes.items():
        if not nd.get("hospital"):
            continue
        if nd["hospital_current"] >= nd["hospital_capacity"] and nd["hospital_capacity"] > 0:
            continue
        cost, _ = world.dijkstra(from_node, nid, vtype)
        if cost < best_cost:
            best_cost = cost
            best_node = nid
    return best_node


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8: REACT AGENT LOOP
# Full ReAct loop using the Anthropic Claude API with optional ValidatorTool.
# ─────────────────────────────────────────────────────────────────────────────

# Tool schema definitions sent to the Claude API
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
            "Returns current status (location, capabilities, capacity, availability) "
            "of all vehicles. Also shows which capabilities remain uncovered per incident."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_incidents",
        "description": (
            "Returns all unresolved incidents including type, location, severity, "
            "required capabilities, uncovered capabilities, and deadline."
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
            "For multi-capability incidents, multiple vehicles may be dispatched sequentially. "
            "Each vehicle only needs to cover at least one uncovered required capability. "
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
        "name": "report_status",
        "description": (
            "Returns high-level summary of resolved/unresolved incidents, "
            "vehicle availability, and current simulation time."
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
3. For MULTI-CAPABILITY incidents (e.g., requiring both fire_suppression AND traffic_control):
   - No single vehicle may cover all capabilities.
   - Dispatch ONE vehicle for each capability it can contribute.
   - The incident resolves automatically when all required capabilities are covered.
4. When dispatching an ambulance carrying patients, ALWAYS include hospital_node.
5. If you receive a VALIDATOR ERROR, read it carefully and correct your plan. Never repeat the same invalid action.
6. Prioritize higher-severity incidents. Break ties by tighter deadline.
7. After all dispatches, call report_status to confirm resolution.
8. DYNAMIC ALERTS: If a dispatch result includes dynamic_alerts, re-read the map and replan immediately.
"""

# Gemini-compatible tool schema (plain dicts, no protos required)
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
                    "Returns current status (location, capabilities, capacity, availability) "
                    "of all vehicles."
                ),
            },
            {
                "name": "get_incidents",
                "description": (
                    "Returns all unresolved incidents including type, location, severity, "
                    "required capabilities, uncovered capabilities, and deadline."
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
                    "Dispatch a vehicle to handle an incident. "
                    "For multi-capability incidents, multiple vehicles may be dispatched. "
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
                "name": "report_status",
                "description": (
                    "Returns high-level summary of resolved/unresolved incidents, "
                    "vehicle availability, and current simulation time."
                ),
            },
        ]
    }
]


def _run_react_gemini(
    scenario_dict: dict,
    api_key: str,
    model: str,
    use_validator: bool,
    max_steps: int,
    max_llm_calls: int,
) -> dict:
    """Gemini-backed ReAct loop. Same logic as the Anthropic version; different API surface."""
    import google.generativeai as genai

    world = WorldState(scenario_dict)
    world_tool = WorldTool(world)
    validator = ValidatorTool(world)

    genai.configure(api_key=api_key)
    gemini_model = genai.GenerativeModel(
        model_name=model,
        tools=GEMINI_TOOLS,
        system_instruction=SYSTEM_PROMPT,
    )
    chat = gemini_model.start_chat()

    step_count = 0
    llm_calls = 0

    def dispatch_tool(name: str, inputs: dict) -> Any:
        if name == "get_map_state":
            return world_tool.get_map_state()
        if name == "get_vehicles":
            return world_tool.get_vehicles()
        if name == "get_incidents":
            return world_tool.get_incidents()
        if name == "get_shortest_path":
            return world_tool.get_shortest_path(**inputs)
        if name == "dispatch_vehicle":
            if use_validator:
                valid, err_msg = validator.validate_dispatch(
                    vehicle_id=inputs.get("vehicle_id", ""),
                    incident_id=inputs.get("incident_id", ""),
                    hospital_node=inputs.get("hospital_node"),
                )
                if not valid:
                    return {"success": False, "validator_error": err_msg}
            return world_tool.dispatch_vehicle(**inputs)
        if name == "report_status":
            return world_tool.report_status()
        return {"error": f"Unknown tool: {name}"}

    current_msg: Any = (
        f"SCENARIO: {world.name}\n"
        f"Description: {world.scenario_id}\n\n"
        "Begin emergency response. Use your tools to assess the situation "
        "and dispatch all resources."
    )

    while step_count < max_steps and llm_calls < max_llm_calls:
        step_count += 1
        try:
            response = chat.send_message(current_msg)
            llm_calls += 1
        except Exception as exc:
            print(f"  [ReAct/Gemini] API error at step {step_count}: {exc}")
            break

        fn_calls = [p.function_call for p in response.parts if p.function_call and p.function_call.name]

        if not fn_calls:
            print(f"  [ReAct/Gemini] Agent finished after {step_count} steps.")
            break

        tool_responses = []
        for fc in fn_calls:
            args = {k: v for k, v in fc.args.items()} if fc.args else {}
            result = dispatch_tool(fc.name, args)
            print(f"  [ReAct/Gemini] {fc.name} → {str(result)[:80]}")
            tool_responses.append({"function_response": {"name": fc.name, "response": result}})

        current_msg = tool_responses

    mode_str = "react" if use_validator else "ablated"
    return compute_metrics(world, validator, step_count, mode_str)


def run_react(
    scenario_dict: dict,
    api_key: str,
    model: str = "claude-sonnet-4-5",
    use_validator: bool = True,
    max_steps: int = 40,
    max_llm_calls: int = 40,
    provider: str = "anthropic",
) -> dict:
    """
    Run the full ReAct agent loop on a scenario.

    Parameters
    ----------
    use_validator : bool
        If True, runs the ValidatorTool before each dispatch (Full ReAct).
        If False, dispatches are executed directly (Ablated ReAct).
    provider : str
        "anthropic" or "gemini"
    """
    if provider == "gemini":
        return _run_react_gemini(scenario_dict, api_key, model, use_validator, max_steps, max_llm_calls)

    import anthropic  # Import here so deterministic mode works without the package

    world = WorldState(scenario_dict)
    world_tool = WorldTool(world)
    validator = ValidatorTool(world)
    client = anthropic.Anthropic(api_key=api_key)

    step_count = 0
    llm_calls = 0
    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                f"SCENARIO: {world.name}\n"
                f"Description: {world.scenario_id}\n\n"
                "Begin emergency response. Use your tools to assess the situation "
                "and dispatch all resources."
            ),
        }
    ]

    def dispatch_tool(name: str, inputs: dict) -> Any:
        if name == "get_map_state":
            return world_tool.get_map_state()
        if name == "get_vehicles":
            return world_tool.get_vehicles()
        if name == "get_incidents":
            return world_tool.get_incidents()
        if name == "get_shortest_path":
            return world_tool.get_shortest_path(**inputs)
        if name == "dispatch_vehicle":
            if use_validator:
                valid, err_msg = validator.validate_dispatch(
                    vehicle_id=inputs["vehicle_id"],
                    incident_id=inputs["incident_id"],
                    hospital_node=inputs.get("hospital_node"),
                )
                if not valid:
                    return {"success": False, "validator_error": err_msg}
            return world_tool.dispatch_vehicle(**inputs)
        if name == "report_status":
            return world_tool.report_status()
        return {"error": f"Unknown tool: {name}"}

    while step_count < max_steps and llm_calls < max_llm_calls:
        step_count += 1
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )
            llm_calls += 1
        except Exception as exc:
            print(f"  [ReAct] API error at step {step_count}: {exc}")
            break

        messages.append({"role": "assistant", "content": response.content})

        tool_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_blocks or response.stop_reason == "end_turn":
            print(f"  [ReAct] Agent finished after {step_count} steps.")
            break

        tool_results: list[dict] = []
        for block in tool_blocks:
            result = dispatch_tool(block.name, block.input or {})
            result_str = json.dumps(result, indent=2)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_str,
            })

        messages.append({"role": "user", "content": tool_results})

    return compute_metrics(world, validator, step_count, "react" if use_validator else "ablated")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9: ZERO-SHOT BASELINE
# Send a single LLM prompt with scenario description.
# Parse the JSON dispatch list from the response.
# Execute WITHOUT validation.
# ─────────────────────────────────────────────────────────────────────────────

def _build_zero_shot_prompt(scenario_dict: dict) -> str:
    """Build a single-shot prompt describing the scenario for the zero-shot baseline."""
    world = WorldState(scenario_dict)

    inc_lines = []
    for iid, inc in world.incidents.items():
        inc_lines.append(
            f"  - {iid}: type={inc['type']}, location={inc['location']}, "
            f"severity={inc['severity']}, deadline={inc['deadline_minutes']}min, "
            f"required_capabilities={inc['required_capabilities']}, patients={inc['patients']}"
        )

    veh_lines = []
    for vid, v in world.vehicles.items():
        veh_lines.append(
            f"  - {vid}: type={v['type']}, location={v['location']}, "
            f"capabilities={v['capabilities']}, capacity={v['capacity']}, fuel={v.get('fuel', 100)}"
        )

    node_lines = []
    for nid, nd in world.nodes.items():
        if nd.get("hospital"):
            node_lines.append(f"  - {nid}: HOSPITAL (capacity={nd['hospital_capacity']})")
        elif nd.get("type", "") == "depot":
            node_lines.append(f"  - {nid}: depot")

    edge_lines = []
    for e in world.edges_raw:
        if e.get("allowed_vehicle_types") and len(e["allowed_vehicle_types"]) < 4:
            edge_lines.append(
                f"  - {e['id']}: {e['source_node']} <-> {e['target_node']}, "
                f"time={e['base_travel_time']}min, restricted to {e['allowed_vehicle_types']}"
            )

    prompt = (
        f"You are an emergency response coordinator for scenario: {world.name}\n\n"
        f"INCIDENTS:\n" + "\n".join(inc_lines) + "\n\n"
        f"VEHICLES:\n" + "\n".join(veh_lines) + "\n\n"
        f"KEY NODES:\n" + "\n".join(node_lines) + "\n\n"
    )
    if edge_lines:
        prompt += f"RESTRICTED EDGES (not all vehicle types allowed):\n" + "\n".join(edge_lines) + "\n\n"

    prompt += (
        "Task: Output a JSON array of dispatch decisions. Each decision is:\n"
        '  {"vehicle_id": "...", "incident_id": "...", "hospital_node": "..." (or null)}\n\n'
        "Rules:\n"
        "1. Each vehicle can only be dispatched once.\n"
        "2. For multi-capability incidents, send multiple vehicles (one per capability).\n"
        "3. For ambulances carrying patients, include the hospital_node (nearest hospital).\n"
        "4. Respect vehicle type restrictions on edges.\n"
        "5. Prioritize higher-severity incidents.\n\n"
        "Output ONLY the JSON array, no other text."
    )
    return prompt


def run_zero_shot(
    scenario_dict: dict,
    api_key: str,
    model: str = "claude-sonnet-4-5",
    provider: str = "anthropic",
) -> dict:
    """
    Zero-shot baseline: single LLM call, parse dispatch list, execute without validation.
    violations are still counted by comparing against what the validator would say.
    """
    world = WorldState(scenario_dict)
    world_tool = WorldTool(world)
    # Validator is used only to COUNT violations, not to block execution
    validator = ValidatorTool(world)

    prompt = _build_zero_shot_prompt(scenario_dict)

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

    # Parse JSON from the response
    decisions: list[dict] = []
    json_match = re.search(r"\[.*\]", raw_text, re.DOTALL)
    if json_match:
        try:
            decisions = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            print(f"  [ZeroShot] Could not parse JSON from response.")

    step_count = 1  # The single LLM call is one "step"
    zero_shot_violations = 0

    for decision in decisions:
        vid = decision.get("vehicle_id", "")
        iid = decision.get("incident_id", "")
        hosp = decision.get("hospital_node")

        # Count violations honestly without mutating validator state
        v = world.vehicles.get(vid)
        inc = world.incidents.get(iid)
        if v and inc:
            required = set(inc.get("required_capabilities", []))
            covered = set(inc.get("covered_capabilities", []))
            still_needed = required - covered
            contributes = set(v.get("capabilities", [])) & still_needed
            if not contributes:
                zero_shot_violations += 1
                print(f"  [ZeroShot] Violation: {vid} contributes nothing to {iid}.")

        # Execute regardless (zero-shot ignores validator)
        if v and inc and not inc["resolved"]:
            world_tool.dispatch_vehicle(
                vehicle_id=vid,
                incident_id=iid,
                hospital_node=hosp if hosp else None,
            )
            step_count += 1

    # Inject clean violation count into metrics
    result = compute_metrics(world, validator, step_count, "zero_shot")
    result["violation_count"] = zero_shot_violations
    return result


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9B: AGENTKIT AGENT
# Architecturally distinct from ReAct: code handles all routing, capacity,
# capability matching. LLM is consulted ONLY for ethical tie-breaking (Tier 3).
# ─────────────────────────────────────────────────────────────────────────────

class RescueAgent:
    """
    AgentKit-style agent with deterministic planning and optional LLM ethics.

    Architecture:
      - All routing, capacity, and capability matching done by code (never LLM).
      - LLM called ONLY when _is_ethical_tie() detects identical severity+deadline.
      - Maintains plan_queue, memory log of failed dispatches, and observation log.
      - Dynamic replanning via Tier 4 trigger detection in observe().
    """

    def __init__(
        self,
        world: WorldState,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-5",
        use_llm_for_ethics: bool = True,
        provider: str = "anthropic",
    ):
        self.world = world
        self.tool = WorldTool(world)
        self.validator = ValidatorTool(world)
        self.api_key = api_key
        self.model = model
        self.use_llm_for_ethics = use_llm_for_ethics
        self.provider = provider
        self.plan_queue: list[tuple[str, dict]] = []
        self.memory: list[dict] = []
        self.step_count: int = 0

    def observe(self) -> tuple[dict, dict, dict, list[str]]:
        """
        Poll simulation state. Advances clock to fire any pending dynamic triggers —
        critical for Tier 4 correctness even when no dispatch is happening.
        Returns (incidents, vehicles, map_state, alerts).
        """
        alerts = self.world.advance_clock(self.world.current_time)
        incidents = self.tool.get_incidents()
        vehicles = self.tool.get_vehicles()
        map_state = self.tool.get_map_state()
        return incidents, vehicles, map_state, alerts

    def plan(self, incidents: dict, vehicles: dict) -> None:
        """
        Pure code: rank open incidents by (severity DESC, deadline ASC).
        If use_llm_for_ethics=True and an ethical tie is detected, calls
        _llm_ethical_sort() to break the tie. Populates self.plan_queue.
        """
        ranked = sorted(
            incidents.items(),
            key=lambda kv: (-kv[1]["severity"], kv[1]["deadline_minutes"]),
        )
        if self.use_llm_for_ethics and self._is_ethical_tie(ranked):
            ranked = self._llm_ethical_sort(ranked)
        self.plan_queue = list(ranked)

    def act(self) -> bool:
        """
        Scan the plan_queue in priority order; dispatch the first incident
        for which a valid vehicle exists.

        1. Refresh incident state from world for each candidate.
        2. Call _match_vehicle() (pure code) to find best vehicle.
        3. Call validator.validate_dispatch() before any dispatch.
        4. On validation failure, log to self.memory and try next vehicle.
        5. On success, call world_tool.dispatch_vehicle().
        6. If incident fully resolved, pop it from self.plan_queue.
        Returns False only when no incident in the queue can be dispatched.
        """
        if not self.plan_queue:
            return False

        for idx in range(len(self.plan_queue)):
            incident_id, _ = self.plan_queue[idx]

            world_inc = self.world.incidents.get(incident_id)
            if world_inc is None or world_inc["resolved"]:
                self.plan_queue.pop(idx)
                return True  # list changed; caller will re-enter

            excluded: set[str] = set()
            dispatched = False
            while True:
                vehicle_id, hospital_node = self._match_vehicle(
                    incident_id, world_inc, exclude=excluded
                )
                if vehicle_id is None:
                    # No vehicle for this incident; try next in queue
                    self.memory.append({
                        "incident_id": incident_id,
                        "reason": "No suitable vehicle available",
                        "time": self.world.current_time,
                    })
                    break

                valid, err_msg = self.validator.validate_dispatch(
                    vehicle_id, incident_id, hospital_node
                )
                if not valid:
                    self.memory.append({
                        "vehicle_id": vehicle_id,
                        "incident_id": incident_id,
                        "reason": err_msg,
                        "time": self.world.current_time,
                    })
                    print(f"  [AgentKit] Validator rejected {vehicle_id}→{incident_id}: {err_msg}")
                    excluded.add(vehicle_id)
                    continue

                result = self.tool.dispatch_vehicle(
                    vehicle_id=vehicle_id,
                    incident_id=incident_id,
                    hospital_node=hospital_node,
                )
                self.step_count += 1
                resolved_flag = result.get("incident_resolved", False)
                print(
                    f"  [AgentKit] {vehicle_id} → {incident_id} | "
                    f"t={result.get('travel_time_minutes', 0):.1f}min | resolved={resolved_flag}"
                )
                if resolved_flag:
                    self.plan_queue.pop(idx)
                dispatched = True
                break

            if dispatched:
                return bool(self.plan_queue) or bool(self.world.open_incidents())

        # No incident in the queue had an available vehicle
        return False

    def replan(self, alerts: list[str]) -> None:
        """
        Triggered when observe() returns non-empty alerts (Tier 4).
        Flushes self.plan_queue entirely, re-observes, and rebuilds plan.
        """
        print(f"  [AgentKit] REPLAN triggered by {len(alerts)} alert(s): {alerts}")
        self.plan_queue = []
        incidents, vehicles, _, _ = self.observe()
        self.plan(incidents, vehicles)

    def _match_vehicle(
        self,
        incident_id: str,
        inc: dict,
        exclude: set[str] | None = None,
    ) -> tuple[str | None, str | None]:
        """
        Pure code. Find nearest idle vehicle contributing at least one uncovered
        required capability. Respects vehicle-type edge restrictions via dijkstra.
        For patient_transport vehicles, also resolves nearest_hospital via
        the module-level _nearest_hospital() helper.
        Returns (vehicle_id, hospital_node) or (None, None).
        """
        world_inc = self.world.incidents.get(incident_id)
        if not world_inc:
            return None, None

        already_covered = set(world_inc.get("covered_capabilities", []))
        still_needed = set(world_inc["required_capabilities"]) - already_covered
        if not still_needed:
            return None, None

        best_vid: str | None = None
        best_cost: float = math.inf
        best_hospital: str | None = None

        for vid, v in self.world.vehicles.items():
            if not v["available"]:
                continue
            if exclude and vid in exclude:
                continue
            vtype = v.get("type")
            vehicle_caps = set(v["capabilities"])
            if not (vehicle_caps & still_needed):
                continue
            if world_inc.get("patients", 0) > 0 and "patient_transport" in vehicle_caps:
                if world_inc["patients"] > v["capacity"] - v["current_load"]:
                    continue
            cost, _ = self.world.dijkstra(v["location"], world_inc["location"], vtype)
            if math.isinf(cost):
                continue
            if cost < best_cost:
                best_cost = cost
                best_vid = vid
                best_hospital = None
                if "patient_transport" in vehicle_caps and world_inc.get("patients", 0) > 0:
                    best_hospital = _nearest_hospital(
                        self.world, world_inc["location"], vtype
                    )

        return best_vid, best_hospital

    def _is_ethical_tie(self, ranked: list) -> bool:
        """Detect Tier 3 scenario: top two incidents share identical severity and deadline."""
        if len(ranked) < 2:
            return False
        _, inc0 = ranked[0]
        _, inc1 = ranked[1]
        return (
            inc0["severity"] == inc1["severity"]
            and inc0["deadline_minutes"] == inc1["deadline_minutes"]
        )

    def _llm_ethical_sort(self, ranked: list) -> list:
        """
        Called ONLY when _is_ethical_tie() returns True.
        Sends a minimal structured prompt to Claude describing the tied incidents.
        Parses the JSON array response and reorders ranked accordingly.
        Never used for routing, capacity, or any math decision.
        """
        try:
            tied = []
            for iid, inc in ranked[:2]:
                tied.append({
                    "incident_id": iid,
                    "type": inc.get("type", "unknown"),
                    "location": inc.get("location", "unknown"),
                    "severity": inc.get("severity"),
                    "deadline_minutes": inc.get("deadline_minutes"),
                    "required_capabilities": inc.get("required_capabilities", []),
                    "patients": inc.get("patients", 0),
                })

            prompt = (
                "Two emergency incidents have identical severity and deadline. "
                "As an emergency coordinator, determine which to prioritize first "
                "based on humanitarian considerations (threat to life, patient count, "
                "vulnerability of affected population).\n\n"
                f"Incident A: {json.dumps(tied[0], indent=2)}\n\n"
                f"Incident B: {json.dumps(tied[1], indent=2)}\n\n"
                "Return a JSON array of incident IDs in priority order (highest first). "
                "Example: [\"INC_001\", \"INC_002\"]\n"
                "Output ONLY the JSON array, no other text."
            )

            if self.provider == "gemini":
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                gmodel = genai.GenerativeModel(self.model)
                gresponse = gmodel.generate_content(prompt)
                raw = gresponse.text if gresponse.text else "[]"
            else:
                import anthropic
                client = anthropic.Anthropic(api_key=self.api_key)
                response = client.messages.create(
                    model=self.model,
                    max_tokens=256,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text if response.content else "[]"
            json_match = re.search(r"\[.*?\]", raw, re.DOTALL)
            if json_match:
                order = json.loads(json_match.group(0))
                ranked_dict = dict(ranked)
                reordered: list = []
                seen: set = set()
                for iid in order:
                    if iid in ranked_dict and iid not in seen:
                        reordered.append((iid, ranked_dict[iid]))
                        seen.add(iid)
                for iid, inc in ranked:
                    if iid not in seen:
                        reordered.append((iid, inc))
                return reordered
        except Exception as exc:
            print(f"  [AgentKit] LLM ethical sort failed (using original order): {exc}")
        return ranked

    def run(self) -> int:
        """
        Main loop: observe → plan → act → replan.
        Breaks when all incidents resolved, no dispatch possible, or step_count >= 100.
        Returns total step_count.
        """
        incidents, vehicles, _, alerts = self.observe()
        if alerts:
            self.replan(alerts)
            incidents, vehicles, _, _ = self.observe()
        self.plan(incidents, vehicles)

        while self.step_count < 100:
            incidents, vehicles, _, alerts = self.observe()
            if alerts:
                self.replan(alerts)
                incidents, vehicles, _, _ = self.observe()

            if not incidents:
                break

            if not self.plan_queue:
                self.plan(incidents, vehicles)

            if not self.plan_queue:
                break

            prev_steps = self.step_count
            can_continue = self.act()

            if self.step_count == prev_steps:
                # act() scanned every queued incident and found nothing to dispatch
                break

            if not can_continue and not self.world.open_incidents():
                break

        return self.step_count


def run_agentkit(
    scenario_dict: dict,
    api_key: str | None = None,
    model: str = "claude-sonnet-4-5",
    use_llm_for_ethics: bool = True,
    provider: str = "anthropic",
) -> dict:
    """
    Instantiate RescueAgent, call agent.run(), return compute_metrics().
    mode string = "agentkit"
    """
    world = WorldState(scenario_dict)
    agent = RescueAgent(
        world,
        api_key=api_key,
        model=model,
        use_llm_for_ethics=use_llm_for_ethics,
        provider=provider,
    )
    step_count = agent.run()
    return compute_metrics(world, agent.validator, step_count, "agentkit")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 10: BENCHMARK RUNNER
# Orchestrates all scenarios, modes, and runs; aggregates results.
# ─────────────────────────────────────────────────────────────────────────────

def run_scenario(
    scenario_path: str,
    mode: str,
    api_key: str | None,
    model: str = "claude-sonnet-4-5",
    provider: str = "anthropic",
) -> dict:
    """Load and run a single scenario in the specified mode."""
    scenario_dict = load_scenario(scenario_path)
    scenario_name = scenario_dict["scenario_id"]
    print(f"\n  Running: {scenario_name} | mode={mode} | provider={provider}")

    if mode == "deterministic":
        return run_deterministic(scenario_dict)
    elif mode == "react":
        if not api_key:
            raise ValueError("API key required for react mode.")
        return run_react(scenario_dict, api_key=api_key, model=model, use_validator=True, provider=provider)
    elif mode == "ablated":
        if not api_key:
            raise ValueError("API key required for ablated mode.")
        return run_react(scenario_dict, api_key=api_key, model=model, use_validator=False, provider=provider)
    elif mode == "zero_shot":
        if not api_key:
            raise ValueError("API key required for zero_shot mode.")
        return run_zero_shot(scenario_dict, api_key=api_key, model=model, provider=provider)
    elif mode == "agentkit":
        return run_agentkit(
            scenario_dict,
            api_key=api_key,
            model=model,
            use_llm_for_ethics=True,
            provider=provider,
        )
    else:
        raise ValueError(f"Unknown mode: {mode}")


def aggregate_tier_results(results: list[dict]) -> dict:
    """Compute mean metrics across a list of per-scenario results."""
    if not results:
        return {}
    keys = ["pwrs", "cap_pwrs", "resolution_rate", "deadline_adherence",
            "violation_count"]
    agg: dict = {}
    for k in keys:
        vals = [r[k] for r in results if k in r and r[k] is not None]
        agg[k] = round(sum(vals) / len(vals), 4) if vals else None
    eff_vals = [r["step_efficiency"] for r in results
                if r.get("step_efficiency") is not None]
    agg["step_efficiency"] = round(sum(eff_vals) / len(eff_vals), 4) if eff_vals else None
    return agg


def print_results_table(all_results: dict[str, dict[int, dict]]) -> None:
    """
    Print a formatted results table.

    all_results: {mode -> {tier -> aggregated_metrics}}
    """
    print("\n" + "=" * 100)
    print("  RESCUEBENCH BENCHMARK RESULTS")
    print("=" * 100)
    header = (
        f"{'Method':<20} {'Tier':<6} {'PWRS':<8} {'Cap-PWRS':<10} "
        f"{'Res.Rate':<10} {'DL Adh.':<10} {'Violations':<12} {'Step Eff.':<10}"
    )
    print(header)
    print("-" * 100)

    mode_labels = {
        "deterministic": "Deterministic",
        "zero_shot": "Zero-Shot LLM",
        "ablated": "ReAct (Ablated)",
        "react": "ReAct (Full)",
        "agentkit": "AgentKit (Ours)",
    }
    mode_order = ["deterministic", "zero_shot", "ablated", "react", "agentkit"]

    for mode in mode_order:
        if mode not in all_results:
            continue
        for tier in sorted(all_results[mode].keys()):
            agg = all_results[mode][tier]
            eff = f"{agg['step_efficiency']:.3f}" if agg.get("step_efficiency") is not None else "N/A"
            print(
                f"{mode_labels.get(mode, mode):<20} {tier:<6} "
                f"{agg.get('pwrs', 0):<8.3f} {agg.get('cap_pwrs', 0):<10.3f} "
                f"{agg.get('resolution_rate', 0):<10.3f} "
                f"{agg.get('deadline_adherence', 0):<10.3f} "
                f"{agg.get('violation_count', 0):<12.1f} "
                f"{eff:<10}"
            )

    print("=" * 100)

    # Print ablation summary (means across all tiers)
    print("\nABLATION SUMMARY (averaged across all tiers):")
    print("-" * 70)
    print(f"{'Method':<20} {'Mean PWRS':<12} {'Mean Cap-PWRS':<15} {'Mean Viol.':<12} {'Mean Step Eff.':<14}")
    print("-" * 70)
    for mode in mode_order:
        if mode not in all_results:
            continue
        tier_aggs = list(all_results[mode].values())
        mean_pwrs = round(sum(a.get("pwrs", 0) for a in tier_aggs) / len(tier_aggs), 3)
        mean_cap_pwrs = round(sum(a.get("cap_pwrs", 0) for a in tier_aggs) / len(tier_aggs), 3)
        mean_viol = round(sum(a.get("violation_count", 0) for a in tier_aggs) / len(tier_aggs), 1)
        eff_vals = [a["step_efficiency"] for a in tier_aggs if a.get("step_efficiency") is not None]
        mean_eff = f"{sum(eff_vals)/len(eff_vals):.3f}" if eff_vals else "N/A"
        print(
            f"{mode_labels.get(mode, mode):<20} {mean_pwrs:<12} {mean_cap_pwrs:<15} "
            f"{mean_viol:<12} {mean_eff:<14}"
        )
    print("=" * 70)


def run_benchmark(
    modes: list[str],
    tiers: list[int],
    num_runs: int,
    api_key: str | None,
    model: str = "claude-sonnet-4-5",
    provider: str = "anthropic",
) -> dict[str, dict[int, dict]]:
    """
    Run the full benchmark.

    Returns: {mode -> {tier -> aggregated_metrics_across_scenarios_and_runs}}
    """
    all_results: dict[str, dict[int, dict]] = {}

    for mode in modes:
        print(f"\n{'#'*60}")
        print(f"  MODE: {mode.upper()}")
        print(f"{'#'*60}")

        if mode not in all_results:
            all_results[mode] = {}

        for tier in tiers:
            scenario_files = get_scenario_files(tier)
            if not scenario_files:
                print(f"  WARNING: No scenario files found for tier {tier}")
                continue

            print(f"\n--- Tier {tier} ({len(scenario_files)} scenarios × {num_runs} runs) ---")
            tier_run_results: list[dict] = []

            for scenario_path in scenario_files:
                for run_idx in range(num_runs):
                    print(f"\n  [Scenario: {os.path.basename(scenario_path)}, Run {run_idx+1}/{num_runs}]")
                    try:
                        result = run_scenario(scenario_path, mode, api_key, model, provider)
                        tier_run_results.append(result)
                        print(
                            f"    PWRS={result['pwrs']:.3f} | Cap-PWRS={result['cap_pwrs']:.3f} | "
                            f"Violations={result['violation_count']} | "
                            f"StepEff={result.get('step_efficiency')}"
                        )
                    except Exception as exc:
                        print(f"  ERROR running {scenario_path} in mode {mode}: {exc}")
                        # Record a zero-score result on error
                        tier_run_results.append({
                            "pwrs": 0.0, "cap_pwrs": 0.0, "resolution_rate": 0.0,
                            "deadline_adherence": 0.0, "violation_count": 0,
                            "step_efficiency": None,
                        })

            all_results[mode][tier] = aggregate_tier_results(tier_run_results)
            agg = all_results[mode][tier]
            print(
                f"\n  Tier {tier} aggregate: "
                f"PWRS={agg.get('pwrs'):.3f}, Cap-PWRS={agg.get('cap_pwrs'):.3f}, "
                f"Violations={agg.get('violation_count'):.1f}"
            )

    return all_results


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 11: CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RescueBench Comprehensive Benchmark Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run deterministic planner on all tiers (no API key needed)
  python run_benchmark.py --mode deterministic --tier all

  # Run full ReAct agent on Tier 1 only, 1 run per scenario
  python run_benchmark.py --mode react --tier 1 --runs 1 --api-key sk-ant-...

  # Run all modes on Tier 2, 3 runs each
  python run_benchmark.py --mode all --tier 2 --runs 3 --api-key sk-ant-...

  # Use env var for API key
  export ANTHROPIC_API_KEY=sk-ant-...
  python run_benchmark.py --mode all --tier all --runs 3
        """,
    )
    parser.add_argument(
        "--mode",
        default="deterministic",
        choices=["deterministic", "react", "zero_shot", "ablated", "agentkit", "all"],
        help="Evaluation mode (default: deterministic)",
    )
    parser.add_argument(
        "--tier",
        default="all",
        help="Tier to run: 1, 2, 3, 4, or 'all' (default: all)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of runs per scenario (default: 3)",
    )
    parser.add_argument(
        "--provider",
        default="gemini",
        choices=["anthropic", "gemini"],
        help="LLM provider (default: gemini)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key — Gemini key or Anthropic key depending on --provider "
             "(overrides GEMINI_API_KEY / ANTHROPIC_API_KEY env vars)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name (default: gemini-2.0-flash for Gemini, claude-sonnet-4-5 for Anthropic)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Resolve modes
    if args.mode == "all":
        modes = ["deterministic", "zero_shot", "ablated", "react", "agentkit"]
    else:
        modes = [args.mode]

    # Resolve tiers
    if args.tier == "all":
        tiers = [1, 2, 3, 4]
    else:
        tiers = [int(args.tier)]

    # Resolve provider and API key
    provider = args.provider
    if provider == "gemini":
        api_key = args.api_key or os.getenv("GEMINI_API_KEY")
        default_model = "gemini-2.5-flash"
    else:
        api_key = args.api_key or os.getenv("ANTHROPIC_API_KEY")
        default_model = "claude-sonnet-4-5"
    model = args.model or default_model

    llm_modes = {"react", "zero_shot", "ablated", "agentkit"}
    needs_api = bool(set(modes) & llm_modes)
    if needs_api and not api_key:
        env_var = "GEMINI_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"
        print(
            f"WARNING: No API key provided for provider '{provider}'. "
            f"LLM modes will fail.\nSet {env_var} or use --api-key."
        )

    print(f"\nRescueBench Benchmark Runner")
    print(f"  Provider: {provider}")
    print(f"  Modes : {modes}")
    print(f"  Tiers : {tiers}")
    print(f"  Runs  : {args.runs} per scenario")
    print(f"  Model : {model}")

    start = time.time()
    all_results = run_benchmark(
        modes=modes,
        tiers=tiers,
        num_runs=args.runs,
        api_key=api_key,
        model=model,
        provider=provider,
    )
    elapsed = time.time() - start

    print_results_table(all_results)
    print(f"\nTotal runtime: {elapsed:.1f}s")

    # Optionally save results to JSON
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "benchmark_results.json")
    with open(output_path, "w") as fh:
        json.dump(all_results, fh, indent=2)
    print(f"Results saved to: {output_path}")


if __name__ == "__main__":
    main()
