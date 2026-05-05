from __future__ import annotations

import copy
import heapq
import math


QUANTITY_CAPABILITY_PRIORITY = ("patient_transport", "bulk_supply", "medical_triage")


class WorldState:
    """
    Mutable live simulation state.

    This version models dispatches as concurrent missions over time rather than
    immediately advancing the global clock per action.
    """

    def __init__(self, scenario: dict):
        self.scenario_id: str = scenario["scenario_id"]
        self.name: str = scenario["name"]
        self.current_time: float = scenario["current_time"]

        self.edges_raw: list[dict] = copy.deepcopy(scenario["edges_raw"])
        self._edge_by_id: dict[str, dict] = {edge["id"]: edge for edge in self.edges_raw}

        self.nodes: dict = copy.deepcopy(scenario["nodes"])
        self.vehicles: dict = copy.deepcopy(scenario["vehicles"])
        self.incidents: dict = copy.deepcopy(scenario["incidents"])
        self.dynamic_triggers: list[dict] = copy.deepcopy(scenario["dynamic_triggers"])
        self.event_log: list[str] = []

        for node in self.nodes.values():
            node.setdefault("hospital", False)
            node.setdefault("hospital_capacity", node.get("current_capacity", 0) if node.get("hospital") else 0)
            node.setdefault("hospital_current", 0)
            node.setdefault("hospital_reserved", 0)

        for vehicle in self.vehicles.values():
            vehicle.setdefault("available", True)
            vehicle.setdefault("busy_until", 0.0)
            vehicle.setdefault("next_event_time", None)
            vehicle.setdefault("status", "idle" if vehicle["available"] else "busy")
            vehicle.setdefault("next_location", vehicle.get("location"))
            vehicle.setdefault("assigned_incident", None)
            vehicle.setdefault("assigned_hospital", None)
            vehicle.setdefault("mission", None)

        for incident in self.incidents.values():
            required_capabilities = list(incident.get("required_capabilities", []))
            required_quantity = int(incident.get("required_quantity", incident.get("patients", 0)))
            quantity_capability = incident.get("quantity_capability")
            if quantity_capability is None:
                quantity_capability = self._infer_quantity_capability(required_capabilities, required_quantity)

            incident.setdefault("covered_capabilities", [])
            incident.setdefault("committed_capabilities", [])
            incident["required_quantity"] = required_quantity
            incident["quantity_capability"] = quantity_capability
            incident.setdefault("fulfilled_quantity", 0)
            incident.setdefault("committed_quantity", 0)
            incident["patients"] = required_quantity if quantity_capability == "patient_transport" else 0
            incident["remaining_patients"] = (
                max(0, required_quantity - incident["fulfilled_quantity"])
                if quantity_capability == "patient_transport"
                else 0
            )
            incident["patients_transported"] = (
                incident["fulfilled_quantity"] if quantity_capability == "patient_transport" else 0
            )

    def clone(self) -> "WorldState":
        """Return a deep-copied snapshot for local what-if simulation."""
        return copy.deepcopy(self)

    def _infer_quantity_capability(self, capabilities: list[str], required_quantity: int) -> str | None:
        if required_quantity <= 0:
            return None
        for capability in QUANTITY_CAPABILITY_PRIORITY:
            if capability in capabilities:
                return capability
        return capabilities[0] if capabilities else None

    def vehicle_speed_multiplier(self, vehicle: dict) -> float:
        speed_multiplier = float(vehicle.get("speed_multiplier", 1.0))
        return speed_multiplier if speed_multiplier > 0 else 1.0

    def speed_multiplier_for_vehicle_type(self, vehicle_type: str | None) -> float:
        if vehicle_type is None:
            return 1.0
        for vehicle in self.vehicles.values():
            if vehicle.get("type") == vehicle_type:
                return self.vehicle_speed_multiplier(vehicle)
        return 1.0

    def quantity_capability(self, incident: dict) -> str | None:
        return incident.get("quantity_capability")

    def required_quantity(self, incident: dict) -> int:
        return int(incident.get("required_quantity", 0))

    def fulfilled_quantity(self, incident: dict) -> int:
        return int(incident.get("fulfilled_quantity", 0))

    def committed_quantity(self, incident: dict) -> int:
        return int(incident.get("committed_quantity", 0))

    def remaining_quantity(self, incident: dict) -> int:
        return max(0, self.required_quantity(incident) - self.fulfilled_quantity(incident))

    def remaining_uncommitted_quantity(self, incident: dict) -> int:
        return max(0, self.required_quantity(incident) - self.fulfilled_quantity(incident) - self.committed_quantity(incident))

    def incident_quantity_ratio(self, incident: dict) -> float:
        required_quantity = self.required_quantity(incident)
        if required_quantity <= 0:
            return 1.0
        return max(0.0, min(1.0, self.fulfilled_quantity(incident) / required_quantity))

    def incident_transport_ratio(self, incident: dict) -> float:
        return self.incident_quantity_ratio(incident)

    def incident_coverage_fraction(self, incident: dict) -> float:
        required = list(incident.get("required_capabilities", []))
        if not required:
            return 1.0

        quantity_capability = self.quantity_capability(incident)
        covered = set(incident.get("covered_capabilities", []))
        covered_units = 0.0
        for capability in required:
            if capability == quantity_capability and self.required_quantity(incident) > 0:
                covered_units += self.incident_quantity_ratio(incident)
            elif capability in covered:
                covered_units += 1.0
        return covered_units / len(required)

    def incident_effective_uncovered_capabilities(self, incident: dict) -> list[str]:
        required = list(incident.get("required_capabilities", []))
        covered = set(incident.get("covered_capabilities", []))
        committed = set(incident.get("committed_capabilities", []))
        quantity_capability = self.quantity_capability(incident)

        uncovered: list[str] = []
        for capability in required:
            if capability == quantity_capability and self.required_quantity(incident) > 0:
                if self.remaining_uncommitted_quantity(incident) > 0:
                    uncovered.append(capability)
                continue
            if capability not in covered and capability not in committed:
                uncovered.append(capability)
        return uncovered

    def build_graph_with_edges(
        self,
        vehicle_type: str | None = None,
        speed_multiplier: float = 1.0,
        edge_penalties: dict[str, float] | None = None,
    ) -> dict[str, list[tuple[str, float, str]]]:
        """
        Build an undirected adjacency list filtered by passable edges and, if
        provided, vehicle-type restrictions.
        """
        speed = speed_multiplier if speed_multiplier > 0 else 1.0
        graph: dict[str, list[tuple[str, float, str]]] = {node_id: [] for node_id in self.nodes}
        for edge in self.edges_raw:
            if edge.get("status", "clear") != "clear":
                continue
            if vehicle_type and vehicle_type not in edge.get("allowed_vehicle_types", []):
                continue
            source = edge["source_node"]
            target = edge["target_node"]
            travel_time = edge["base_travel_time"] / speed
            if edge_penalties:
                travel_time += float(edge_penalties.get(edge["id"], 0.0))
            if source in graph:
                graph[source].append((target, travel_time, edge["id"]))
            if target in graph:
                graph[target].append((source, travel_time, edge["id"]))
        return graph

    def build_graph(self, vehicle_type: str | None = None) -> dict[str, list[tuple[str, float]]]:
        graph_with_edges = self.build_graph_with_edges(vehicle_type)
        return {
            node_id: [(neighbor, travel_time) for neighbor, travel_time, _ in neighbors]
            for node_id, neighbors in graph_with_edges.items()
        }

    def edge_penalties_for_strategy(
        self,
        route_strategy: str = "fastest",
        horizon_minutes: float | None = None,
    ) -> dict[str, float]:
        if route_strategy == "fastest":
            return {}

        penalties: dict[str, float] = {}
        base_penalty = 25.0 if route_strategy == "robust" else 10.0
        for trigger in self.dynamic_triggers:
            if trigger.get("fired"):
                continue
            edge_id = trigger.get("target_edge")
            if not edge_id:
                continue
            trigger_time = float(trigger.get("trigger_time", self.current_time))
            gap = max(0.0, trigger_time - self.current_time)
            if horizon_minutes is not None and gap <= horizon_minutes:
                penalties[edge_id] = penalties.get(edge_id, 0.0) + base_penalty + (horizon_minutes - gap)
            else:
                penalties[edge_id] = penalties.get(edge_id, 0.0) + (base_penalty / max(1.0, gap))
        return penalties

    def shortest_path_details(
        self,
        source: str,
        target: str,
        vehicle_type: str | None = None,
        speed_multiplier: float = 1.0,
        route_strategy: str = "fastest",
        horizon_minutes: float | None = None,
    ) -> tuple[float, list[str], list[float], list[str]]:
        """Shortest path plus leg-level timing details."""
        if source == target:
            return 0.0, [source], [], []

        graph = self.build_graph_with_edges(
            vehicle_type,
            speed_multiplier,
            self.edge_penalties_for_strategy(route_strategy, horizon_minutes),
        )
        dist = {node: math.inf for node in graph}
        prev_node: dict[str, str | None] = {node: None for node in graph}
        prev_edge: dict[str, str | None] = {node: None for node in graph}
        prev_leg_time: dict[str, float] = {node: 0.0 for node in graph}
        if source not in dist or target not in dist:
            return math.inf, [], [], []

        dist[source] = 0.0
        queue: list[tuple[float, str]] = [(0.0, source)]
        while queue:
            cur_dist, node = heapq.heappop(queue)
            if cur_dist > dist[node]:
                continue
            if node == target:
                break
            for neighbor, weight, edge_id in graph.get(node, []):
                next_dist = dist[node] + weight
                if next_dist < dist[neighbor]:
                    dist[neighbor] = next_dist
                    prev_node[neighbor] = node
                    prev_edge[neighbor] = edge_id
                    prev_leg_time[neighbor] = weight
                    heapq.heappush(queue, (next_dist, neighbor))

        if math.isinf(dist.get(target, math.inf)):
            return math.inf, [], [], []

        path: list[str] = []
        leg_times_reversed: list[float] = []
        edge_ids_reversed: list[str] = []
        cur: str | None = target
        while cur is not None:
            path.append(cur)
            edge_id = prev_edge[cur]
            if edge_id is not None:
                edge_ids_reversed.append(edge_id)
                leg_times_reversed.append(prev_leg_time[cur])
            cur = prev_node[cur]

        path.reverse()
        leg_times_reversed.reverse()
        edge_ids_reversed.reverse()
        return dist[target], path, leg_times_reversed, edge_ids_reversed

    def dijkstra(
        self,
        source: str,
        target: str,
        vehicle_type: str | None = None,
        speed_multiplier: float = 1.0,
        route_strategy: str = "fastest",
        horizon_minutes: float | None = None,
    ) -> tuple[float, list[str]]:
        cost, path, _, _ = self.shortest_path_details(
            source,
            target,
            vehicle_type,
            speed_multiplier,
            route_strategy,
            horizon_minutes,
        )
        return cost, path

    def hospital_available_capacity(self, hospital_node: str, reserved_offset: int = 0) -> int:
        hospital = self.nodes.get(hospital_node)
        if not hospital or not hospital.get("hospital"):
            return 0
        capacity = int(hospital.get("hospital_capacity", 0))
        if capacity <= 0:
            return 10**9
        reserved = max(0, int(hospital.get("hospital_reserved", 0)) - reserved_offset)
        return max(0, capacity - int(hospital.get("hospital_current", 0)) - reserved)

    def reserve_hospital_capacity(self, hospital_node: str, quantity: int) -> None:
        if quantity <= 0:
            return
        hospital = self.nodes.get(hospital_node)
        if hospital and hospital.get("hospital"):
            hospital["hospital_reserved"] = int(hospital.get("hospital_reserved", 0)) + quantity

    def release_hospital_capacity(self, hospital_node: str | None, quantity: int) -> None:
        if quantity <= 0 or not hospital_node:
            return
        hospital = self.nodes.get(hospital_node)
        if hospital and hospital.get("hospital"):
            hospital["hospital_reserved"] = max(0, int(hospital.get("hospital_reserved", 0)) - quantity)

    def admit_hospital_patients(self, hospital_node: str | None, quantity: int) -> None:
        if quantity <= 0 or not hospital_node:
            return
        hospital = self.nodes.get(hospital_node)
        if not hospital or not hospital.get("hospital"):
            return
        self.release_hospital_capacity(hospital_node, quantity)
        hospital["hospital_current"] = int(hospital.get("hospital_current", 0)) + quantity

    def choose_hospital(
        self,
        from_node: str,
        vehicle: dict,
        preferred_node: str | None = None,
        required_load: int = 0,
        route_strategy: str = "fastest",
        limit: int = 1,
    ) -> str | None:
        options = self.choose_hospital_options(
            from_node,
            vehicle,
            preferred_node=preferred_node,
            required_load=required_load,
            route_strategy=route_strategy,
            limit=limit,
        )
        return options[0][0] if options else None

    def choose_hospital_options(
        self,
        from_node: str,
        vehicle: dict,
        preferred_node: str | None = None,
        required_load: int = 0,
        route_strategy: str = "fastest",
        limit: int = 3,
    ) -> list[tuple[str, float]]:
        vehicle_type = vehicle.get("type")
        speed_multiplier = self.vehicle_speed_multiplier(vehicle)

        def reachable_hospital(node_id: str) -> bool:
            hospital = self.nodes.get(node_id)
            if not hospital or not hospital.get("hospital"):
                return False
            if required_load > 0 and self.hospital_available_capacity(node_id) < required_load:
                return False
            cost, _, _, _ = self.shortest_path_details(
                from_node,
                node_id,
                vehicle_type,
                speed_multiplier,
                route_strategy,
            )
            return not math.isinf(cost)

        candidates: list[tuple[str, float, float]] = []
        preferred_bonus = -0.25
        for node_id, node_data in self.nodes.items():
            if not node_data.get("hospital"):
                continue
            if required_load > 0 and self.hospital_available_capacity(node_id) < required_load:
                continue
            cost, _, _, _ = self.shortest_path_details(
                from_node,
                node_id,
                vehicle_type,
                speed_multiplier,
                route_strategy,
            )
            if math.isinf(cost):
                continue
            score = cost + (preferred_bonus if preferred_node and node_id == preferred_node else 0.0)
            candidates.append((node_id, cost, score))

        candidates.sort(key=lambda item: item[2])
        if preferred_node and reachable_hospital(preferred_node):
            preferred_real_cost, _, _, _ = self.shortest_path_details(
                from_node,
                preferred_node,
                vehicle_type,
                speed_multiplier,
                route_strategy,
            )
            if all(node_id != preferred_node for node_id, _, _ in candidates):
                candidates.insert(0, (preferred_node, preferred_real_cost, preferred_real_cost + preferred_bonus))
        trimmed = candidates[:limit]
        return [(node_id, cost) for node_id, cost, _ in trimmed]

    def vehicle_quantity_capacity(
        self,
        vehicle: dict,
        incident: dict,
        hospital_node: str | None = None,
    ) -> int:
        quantity_capability = self.quantity_capability(incident)
        if not quantity_capability:
            return 0
        if quantity_capability not in set(vehicle.get("capabilities", [])):
            return 0

        remaining = self.remaining_uncommitted_quantity(incident)
        if remaining <= 0:
            return 0

        if quantity_capability == "patient_transport":
            available = max(0, int(vehicle.get("capacity", 0)) - int(vehicle.get("current_load", 0)))
            quantity = min(remaining, available)
            if hospital_node is not None:
                quantity = min(quantity, self.hospital_available_capacity(hospital_node))
            return max(0, quantity)

        if quantity_capability == "bulk_supply":
            available = max(0, int(vehicle.get("current_load", 0)))
            return max(0, min(remaining, available))

        available = int(vehicle.get("capacity", 0))
        if available <= 0:
            available = 1
        return max(0, min(remaining, available))

    def mission_contribution(
        self,
        vehicle: dict,
        incident: dict,
        hospital_node: str | None = None,
    ) -> tuple[list[str], int]:
        quantity_capability = self.quantity_capability(incident)
        uncovered = set(self.incident_effective_uncovered_capabilities(incident))
        vehicle_caps = set(vehicle.get("capabilities", []))

        contribution = sorted((vehicle_caps & uncovered) - ({quantity_capability} if quantity_capability else set()))
        quantity_reserved = self.vehicle_quantity_capacity(vehicle, incident, hospital_node)
        if quantity_reserved > 0 and quantity_capability:
            contribution = sorted(set(contribution) | {quantity_capability})
        return contribution, quantity_reserved

    def reserve_incident_commitment(
        self,
        incident_id: str,
        capabilities: list[str],
        quantity_reserved: int = 0,
    ) -> None:
        incident = self.incidents.get(incident_id)
        if not incident or incident.get("resolved"):
            return

        required = set(incident.get("required_capabilities", []))
        quantity_capability = self.quantity_capability(incident)
        committed = set(incident.get("committed_capabilities", []))
        committed |= ((set(capabilities) & required) - ({quantity_capability} if quantity_capability else set()))
        incident["committed_capabilities"] = sorted(committed)
        if quantity_reserved > 0 and quantity_capability:
            incident["committed_quantity"] = self.committed_quantity(incident) + quantity_reserved

    def release_incident_commitment(
        self,
        incident_id: str,
        capabilities: list[str],
        quantity_reserved: int = 0,
    ) -> None:
        incident = self.incidents.get(incident_id)
        if not incident:
            return

        quantity_capability = self.quantity_capability(incident)
        committed = set(incident.get("committed_capabilities", []))
        committed -= (set(capabilities) - ({quantity_capability} if quantity_capability else set()))
        incident["committed_capabilities"] = sorted(committed)
        if quantity_reserved > 0 and quantity_capability:
            incident["committed_quantity"] = max(0, self.committed_quantity(incident) - quantity_reserved)

    def apply_incident_contribution(
        self,
        incident_id: str,
        capabilities: list[str],
        quantity_delivered: int = 0,
    ) -> bool:
        incident = self.incidents.get(incident_id)
        if not incident or incident["resolved"]:
            return False

        required = set(incident.get("required_capabilities", []))
        quantity_capability = self.quantity_capability(incident)
        covered = set(incident.get("covered_capabilities", []))
        covered |= ((set(capabilities) & required) - ({quantity_capability} if quantity_capability else set()))

        if quantity_delivered > 0 and quantity_capability:
            incident["fulfilled_quantity"] = min(
                self.required_quantity(incident),
                self.fulfilled_quantity(incident) + quantity_delivered,
            )
            if quantity_capability == "patient_transport":
                incident["patients_transported"] = incident["fulfilled_quantity"]
                incident["remaining_patients"] = self.remaining_quantity(incident)
            if self.remaining_quantity(incident) <= 0:
                covered.add(quantity_capability)

        incident["covered_capabilities"] = sorted(covered)
        return self.incident_fully_resolved(incident)

    def incident_fully_resolved(self, incident: dict) -> bool:
        required = set(incident.get("required_capabilities", []))
        covered = set(incident.get("covered_capabilities", []))
        quantity_capability = self.quantity_capability(incident)

        if quantity_capability and self.required_quantity(incident) > 0 and self.remaining_quantity(incident) > 0:
            return False
        if quantity_capability and self.required_quantity(incident) > 0:
            covered.add(quantity_capability)
        return required <= covered

    def mission_fuel_cost(
        self,
        vehicle: dict,
        incident: dict,
        hospital_node: str | None = None,
        route_strategy: str = "fastest",
    ) -> float:
        vehicle_type = vehicle.get("type")
        speed_multiplier = self.vehicle_speed_multiplier(vehicle)
        total_cost, _ = self.dijkstra(
            vehicle["location"],
            incident["location"],
            vehicle_type,
            speed_multiplier,
            route_strategy,
        )
        if math.isinf(total_cost):
            return math.inf
        quantity_capability = self.quantity_capability(incident)
        if quantity_capability == "patient_transport" and hospital_node:
            load = self.vehicle_quantity_capacity(vehicle, incident, hospital_node)
            if load > 0:
                hospital_cost, _ = self.dijkstra(
                    incident["location"],
                    hospital_node,
                    vehicle_type,
                    speed_multiplier,
                    route_strategy,
                )
                if math.isinf(hospital_cost):
                    return math.inf
                total_cost += hospital_cost
        return total_cost

    def mission_time_estimate(
        self,
        vehicle: dict,
        incident: dict,
        hospital_node: str | None = None,
        route_strategy: str = "fastest",
    ) -> tuple[float, float]:
        """Estimate arrival time and full mission completion time for one dispatch."""
        vehicle_type = vehicle.get("type")
        speed_multiplier = self.vehicle_speed_multiplier(vehicle)
        arrival_cost, _ = self.dijkstra(
            vehicle["location"],
            incident["location"],
            vehicle_type,
            speed_multiplier,
            route_strategy,
        )
        if math.isinf(arrival_cost):
            return math.inf, math.inf

        total_cost = arrival_cost
        quantity_capability = self.quantity_capability(incident)
        if quantity_capability == "patient_transport" and hospital_node:
            load = self.vehicle_quantity_capacity(vehicle, incident, hospital_node)
            if load > 0:
                hospital_cost, _ = self.dijkstra(
                    incident["location"],
                    hospital_node,
                    vehicle_type,
                    speed_multiplier,
                    route_strategy,
                )
                if math.isinf(hospital_cost):
                    return math.inf, math.inf
                total_cost += hospital_cost
        return arrival_cost, total_cost

    def schedule_vehicle_mission(
        self,
        vehicle_id: str,
        incident_id: str,
        hospital_node: str | None,
        reserved_capabilities: list[str],
        reserved_quantity: int,
        route_strategy: str = "fastest",
    ) -> tuple[float, list[str], float | None]:
        vehicle = self.vehicles[vehicle_id]
        incident = self.incidents[incident_id]
        speed_multiplier = self.vehicle_speed_multiplier(vehicle)

        cost, path, leg_times, edge_ids = self.shortest_path_details(
            vehicle["location"],
            incident["location"],
            vehicle.get("type"),
            speed_multiplier,
            route_strategy,
        )
        if math.isinf(cost):
            return math.inf, [], None

        self.reserve_incident_commitment(incident_id, reserved_capabilities, reserved_quantity)
        if reserved_quantity > 0 and self.quantity_capability(incident) == "patient_transport" and hospital_node:
            self.reserve_hospital_capacity(hospital_node, reserved_quantity)

        vehicle["available"] = False
        vehicle["status"] = "enroute_to_incident"
        vehicle["assigned_incident"] = incident_id
        vehicle["assigned_hospital"] = hospital_node
        vehicle["next_location"] = incident["location"]
        vehicle["mission"] = {
            "phase": "to_incident",
            "target_node": incident["location"],
            "path": path,
            "leg_times": leg_times,
            "edge_ids": edge_ids,
            "next_leg_index": 0,
            "reserved_capabilities": list(reserved_capabilities),
            "reserved_quantity": reserved_quantity,
            "planned_hospital": hospital_node,
            "route_strategy": route_strategy,
        }
        self._refresh_vehicle_schedule(vehicle)

        estimated_completion = vehicle["busy_until"] if not vehicle["available"] else self.current_time
        expected_hospital_travel = None
        if reserved_quantity > 0 and self.quantity_capability(incident) == "patient_transport" and hospital_node:
            hospital_cost, _, _, _ = self.shortest_path_details(
                incident["location"],
                hospital_node,
                vehicle.get("type"),
                speed_multiplier,
                route_strategy,
            )
            expected_hospital_travel = None if math.isinf(hospital_cost) else hospital_cost
        return cost, path, expected_hospital_travel

    def _refresh_vehicle_schedule(self, vehicle: dict) -> None:
        mission = vehicle.get("mission")
        if not mission:
            vehicle["next_event_time"] = None
            vehicle["busy_until"] = self.current_time
            return

        path = mission.get("path", [])
        leg_times = mission.get("leg_times", [])
        next_leg_index = mission.get("next_leg_index", 0)
        if len(path) <= 1 or next_leg_index >= len(leg_times):
            vehicle["next_event_time"] = self.current_time
            vehicle["busy_until"] = self.current_time
            return

        vehicle["next_event_time"] = self.current_time + leg_times[next_leg_index]
        remaining = sum(leg_times[next_leg_index:])
        vehicle["busy_until"] = self.current_time + remaining

    def advance_clock(self, new_time: float) -> list[str]:
        """Advance the world to `new_time`, processing due mission and trigger events."""
        alerts: list[str] = []
        if new_time < self.current_time:
            new_time = self.current_time

        while True:
            next_due = self._next_due_time(new_time)
            if next_due is None:
                break
            self.current_time = next_due
            alerts.extend(self._fire_due_triggers())
            self._process_due_vehicle_events()

        self.current_time = new_time
        alerts.extend(self._fire_due_triggers())
        self._process_due_vehicle_events()
        return alerts

    def _fire_trigger(self, trigger: dict) -> None:
        edge_id = trigger.get("target_edge", "")
        if edge_id and edge_id in self._edge_by_id:
            self._edge_by_id[edge_id]["status"] = trigger.get("new_status", "blocked")

    def _fire_due_triggers(self) -> list[str]:
        alerts: list[str] = []
        fired_any = False
        for trigger in self.dynamic_triggers:
            if trigger["fired"]:
                continue
            if trigger["trigger_time"] <= self.current_time:
                self._fire_trigger(trigger)
                trigger["fired"] = True
                fired_any = True
                if trigger["message"]:
                    alerts.append(trigger["message"])
                    self.event_log.append(trigger["message"])
        if fired_any:
            self._reroute_active_vehicles()
        return alerts

    def _reroute_active_vehicles(self) -> None:
        for vehicle in self.vehicles.values():
            if vehicle.get("available", True):
                continue
            mission = vehicle.get("mission")
            if not mission:
                continue

            target_node = mission.get("target_node")
            route_strategy = mission.get("route_strategy", "fastest")
            if mission.get("phase") == "to_hospital":
                quantity = int(mission.get("reserved_quantity", 0))
                preferred = mission.get("planned_hospital")
                if quantity > 0:
                    self.release_hospital_capacity(preferred, quantity)
                new_hospital = self.choose_hospital(
                    vehicle["location"],
                    vehicle,
                    preferred,
                    quantity,
                    route_strategy=route_strategy,
                )
                if quantity > 0 and new_hospital:
                    self.reserve_hospital_capacity(new_hospital, quantity)
                vehicle["assigned_hospital"] = new_hospital
                mission["planned_hospital"] = new_hospital
                target_node = new_hospital

            if not target_node or vehicle["location"] == target_node:
                vehicle["next_event_time"] = self.current_time
                vehicle["busy_until"] = self.current_time
                continue

            cost, path, leg_times, edge_ids = self.shortest_path_details(
                vehicle["location"],
                target_node,
                vehicle.get("type"),
                self.vehicle_speed_multiplier(vehicle),
                route_strategy,
            )
            if math.isinf(cost):
                vehicle["next_event_time"] = None
                vehicle["busy_until"] = math.inf
                continue

            mission["target_node"] = target_node
            mission["path"] = path
            mission["leg_times"] = leg_times
            mission["edge_ids"] = edge_ids
            mission["next_leg_index"] = 0
            vehicle["next_location"] = target_node
            self._refresh_vehicle_schedule(vehicle)

    def _process_due_vehicle_events(self) -> list[str]:
        completed: list[str] = []
        for vehicle_id, vehicle in self.vehicles.items():
            if vehicle.get("available", True):
                continue
            next_event_time = vehicle.get("next_event_time")
            if next_event_time is None or next_event_time > self.current_time:
                continue

            mission = vehicle.get("mission")
            if not mission:
                continue

            path = mission.get("path", [])
            leg_times = mission.get("leg_times", [])
            next_leg_index = mission.get("next_leg_index", 0)
            if len(path) <= 1:
                self._complete_vehicle_phase(vehicle_id)
                completed.append(vehicle_id)
                continue

            if next_leg_index < len(path) - 1:
                vehicle["location"] = path[next_leg_index + 1]
                mission["next_leg_index"] = next_leg_index + 1
                leg_time = leg_times[next_leg_index] if next_leg_index < len(leg_times) else 0.0
                vehicle["fuel"] = max(0.0, float(vehicle.get("fuel", 0.0)) - leg_time)

            if mission["next_leg_index"] >= len(leg_times):
                self._complete_vehicle_phase(vehicle_id)
                completed.append(vehicle_id)
            else:
                self._refresh_vehicle_schedule(vehicle)

        return completed

    def _complete_vehicle_phase(self, vehicle_id: str) -> None:
        vehicle = self.vehicles[vehicle_id]
        mission = vehicle.get("mission")
        if not mission:
            return

        phase = mission.get("phase")
        incident_id = vehicle.get("assigned_incident")
        incident = self.incidents.get(incident_id) if incident_id else None
        reserved_capabilities = list(mission.get("reserved_capabilities", []))
        reserved_quantity = int(mission.get("reserved_quantity", 0))

        if phase == "to_incident" and incident:
            quantity_capability = self.quantity_capability(incident)
            keep_quantity_committed = quantity_capability == "patient_transport" and reserved_quantity > 0
            self.release_incident_commitment(
                incident_id,
                reserved_capabilities,
                0 if keep_quantity_committed else reserved_quantity,
            )

            quantity_delivered = reserved_quantity if quantity_capability and quantity_capability != "patient_transport" else 0
            now_resolved = self.apply_incident_contribution(incident_id, reserved_capabilities, quantity_delivered)

            if quantity_capability == "bulk_supply" and quantity_delivered > 0:
                vehicle["current_load"] = max(0, int(vehicle.get("current_load", 0)) - quantity_delivered)

            if quantity_capability == "patient_transport" and reserved_quantity > 0:
                hospital_node = vehicle.get("assigned_hospital")
                self.release_hospital_capacity(hospital_node, reserved_quantity)
                route_strategy = mission.get("route_strategy", "fastest")
                hospital_node = self.choose_hospital(
                    vehicle["location"],
                    vehicle,
                    hospital_node,
                    reserved_quantity,
                    route_strategy=route_strategy,
                )
                if hospital_node:
                    self.reserve_hospital_capacity(hospital_node, reserved_quantity)
                    cost, path, leg_times, edge_ids = self.shortest_path_details(
                        vehicle["location"],
                        hospital_node,
                        vehicle.get("type"),
                        self.vehicle_speed_multiplier(vehicle),
                        route_strategy,
                    )
                    if not math.isinf(cost):
                        vehicle["available"] = False
                        vehicle["status"] = "transporting_to_hospital"
                        vehicle["current_load"] = reserved_quantity
                        vehicle["assigned_hospital"] = hospital_node
                        vehicle["next_location"] = hospital_node
                        vehicle["mission"] = {
                            "phase": "to_hospital",
                            "target_node": hospital_node,
                            "path": path,
                            "leg_times": leg_times,
                            "edge_ids": edge_ids,
                            "next_leg_index": 0,
                            "reserved_capabilities": reserved_capabilities,
                            "reserved_quantity": reserved_quantity,
                            "planned_hospital": hospital_node,
                            "route_strategy": route_strategy,
                        }
                        if now_resolved and incident:
                            incident["resolved"] = True
                            incident["resolved_at"] = self.current_time
                        self._refresh_vehicle_schedule(vehicle)
                        return
                reserved_quantity = 0

            if now_resolved and incident:
                incident["resolved"] = True
                incident["resolved_at"] = self.current_time

            self._release_vehicle(vehicle)
            return

        if phase == "to_hospital" and incident:
            self.admit_hospital_patients(vehicle.get("assigned_hospital"), reserved_quantity)
            now_resolved = self.apply_incident_contribution(incident_id, [], reserved_quantity)
            self.release_incident_commitment(incident_id, [], reserved_quantity)
            if now_resolved:
                incident["resolved"] = True
                incident["resolved_at"] = self.current_time
            self._release_vehicle(vehicle)
            return

        self._release_vehicle(vehicle)

    def _release_vehicle(self, vehicle: dict) -> None:
        vehicle["available"] = True
        vehicle["status"] = "idle"
        vehicle["next_location"] = vehicle.get("location")
        vehicle["busy_until"] = self.current_time
        vehicle["next_event_time"] = None
        vehicle["current_load"] = 0 if "patient_transport" in set(vehicle.get("capabilities", [])) else vehicle.get("current_load", 0)
        vehicle["assigned_incident"] = None
        vehicle["assigned_hospital"] = None
        vehicle["mission"] = None

    def _next_due_time(self, limit_time: float) -> float | None:
        due_times: list[float] = []
        for trigger in self.dynamic_triggers:
            if not trigger["fired"] and self.current_time < trigger["trigger_time"] <= limit_time:
                due_times.append(trigger["trigger_time"])
        for vehicle in self.vehicles.values():
            next_event_time = vehicle.get("next_event_time")
            if next_event_time is not None and self.current_time < next_event_time <= limit_time:
                due_times.append(next_event_time)
        return min(due_times) if due_times else None

    def next_event_time(self) -> float | None:
        future_times: list[float] = []
        for trigger in self.dynamic_triggers:
            if not trigger["fired"] and trigger["trigger_time"] > self.current_time:
                future_times.append(trigger["trigger_time"])
        for vehicle in self.vehicles.values():
            next_event_time = vehicle.get("next_event_time")
            if next_event_time is not None and next_event_time > self.current_time:
                future_times.append(next_event_time)
        return min(future_times) if future_times else None

    def has_pending_events(self) -> bool:
        return self.next_event_time() is not None

    def open_incidents(self) -> dict:
        return {incident_id: inc for incident_id, inc in self.incidents.items() if not inc["resolved"]}

    def available_vehicles(self) -> dict:
        return {vehicle_id: vehicle for vehicle_id, vehicle in self.vehicles.items() if vehicle["available"]}
