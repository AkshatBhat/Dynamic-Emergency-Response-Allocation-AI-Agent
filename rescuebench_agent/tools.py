from __future__ import annotations

import copy
import math

from .world import WorldState


class WorldTool:
    """Agent-facing interface for querying and mutating the simulation."""

    def __init__(self, world: WorldState):
        self.world = world

    def get_map_state(self) -> dict:
        graph = self.world.build_graph()
        return {
            "nodes": {
                node_id: {**node_data, "connections": [neighbor for neighbor, _ in graph.get(node_id, [])]}
                for node_id, node_data in self.world.nodes.items()
            },
            "blocked_edges": [
                edge["id"] for edge in self.world.edges_raw if edge.get("status", "clear") != "clear"
            ],
            "active_alerts": list(self.world.event_log),
            "next_event_time": self.world.next_event_time(),
        }

    def get_vehicles(self) -> dict:
        vehicles = copy.deepcopy(self.world.vehicles)
        for vehicle in vehicles.values():
            mission = vehicle.get("mission")
            if mission:
                vehicle["mission_phase"] = mission.get("phase")
                vehicle["mission_target"] = mission.get("target_node")
                vehicle["reserved_quantity"] = mission.get("reserved_quantity", 0)
            vehicle["next_available_location"] = vehicle.get("next_location", vehicle.get("location"))
        return vehicles

    def get_incidents(self) -> dict:
        return {
            incident_id: {
                **incident,
                "uncovered_capabilities": self.world.incident_effective_uncovered_capabilities(incident),
                "coverage_fraction": round(self.world.incident_coverage_fraction(incident), 4),
                "required_quantity": incident.get("required_quantity", 0),
                "remaining_quantity": self.world.remaining_quantity(incident),
                "committed_quantity": incident.get("committed_quantity", 0),
                "quantity_capability": incident.get("quantity_capability"),
                "remaining_patients": incident.get("remaining_patients", 0),
                "patients_transported": incident.get("patients_transported", 0),
            }
            for incident_id, incident in self.world.incidents.items()
            if not incident["resolved"]
        }

    def get_shortest_path(self, from_node: str, to_node: str, vehicle_type: str | None = None) -> dict:
        cost, path = self.world.dijkstra(
            from_node,
            to_node,
            vehicle_type,
            self.world.speed_multiplier_for_vehicle_type(vehicle_type),
        )
        if math.isinf(cost):
            return {"reachable": False, "path": [], "travel_time_minutes": None}
        return {"reachable": True, "path": path, "travel_time_minutes": cost}

    def dispatch_vehicle(
        self,
        vehicle_id: str,
        incident_id: str,
        hospital_node: str | None = None,
        route_strategy: str = "fastest",
    ) -> dict:
        """
        Dispatch a vehicle by scheduling a concurrent mission.

        Dispatching no longer advances the simulation clock. Missions execute as
        the world is advanced through `advance_to_next_event`.
        """
        alerts = self.world.advance_clock(self.world.current_time)
        vehicle = self.world.vehicles.get(vehicle_id)
        incident = self.world.incidents.get(incident_id)
        if not vehicle or not incident:
            return {
                "success": False,
                "error": f"Unknown vehicle '{vehicle_id}' or incident '{incident_id}'.",
            }

        if incident["resolved"]:
            return {
                "success": False,
                "error": f"Incident '{incident_id}' is already resolved.",
            }

        quantity_capability = self.world.quantity_capability(incident)
        if quantity_capability == "patient_transport" and hospital_node is None:
            hospital_node = self.world.choose_hospital(
                incident["location"],
                vehicle,
                vehicle.get("home_depot"),
                self.world.vehicle_quantity_capacity(vehicle, incident),
                route_strategy=route_strategy,
            )

        reserved_capabilities, reserved_quantity = self.world.mission_contribution(vehicle, incident, hospital_node)
        if not reserved_capabilities and reserved_quantity <= 0:
            return {
                "success": False,
                "error": f"Vehicle '{vehicle_id}' contributes nothing new to incident '{incident_id}'.",
            }

        travel_time, path, expected_hospital_travel = self.world.schedule_vehicle_mission(
            vehicle_id=vehicle_id,
            incident_id=incident_id,
            hospital_node=hospital_node,
            reserved_capabilities=reserved_capabilities,
            reserved_quantity=reserved_quantity,
            route_strategy=route_strategy,
        )
        if math.isinf(travel_time):
            return {
                "success": False,
                "error": (
                    f"No passable route from {vehicle['location']} to {incident['location']} "
                    f"for vehicle type '{vehicle.get('type')}'."
                ),
            }

        updated_vehicle = self.world.vehicles[vehicle_id]
        result: dict = {
            "success": True,
            "vehicle_id": vehicle_id,
            "incident_id": incident_id,
            "route": path,
            "travel_time_minutes": travel_time,
            "arrival_time": self.world.current_time + travel_time,
            "incident_resolved": False,
            "scheduled_capabilities": reserved_capabilities,
            "scheduled_quantity": reserved_quantity,
            "quantity_capability": quantity_capability,
            "hospital_node": hospital_node,
            "route_strategy": route_strategy,
            "vehicle_reavailable_at": updated_vehicle.get("busy_until"),
        }
        if alerts:
            result["dynamic_alerts"] = alerts
        if expected_hospital_travel is not None:
            result["expected_hospital_travel_time_minutes"] = expected_hospital_travel
            result["expected_total_trip_time"] = travel_time + expected_hospital_travel
        return result

    def advance_to_next_event(self) -> dict:
        next_time = self.world.next_event_time()
        if next_time is None:
            return {
                "advanced": False,
                "current_time": self.world.current_time,
                "reason": "No pending vehicle arrivals or dynamic triggers.",
            }

        before_available = {
            vehicle_id: vehicle["available"] for vehicle_id, vehicle in self.world.vehicles.items()
        }
        before_locations = {
            vehicle_id: vehicle["location"] for vehicle_id, vehicle in self.world.vehicles.items()
        }
        alerts = self.world.advance_clock(next_time)
        released = sorted(
            vehicle_id
            for vehicle_id, was_available in before_available.items()
            if not was_available and self.world.vehicles.get(vehicle_id, {}).get("available")
        )
        moved = sorted(
            vehicle_id
            for vehicle_id, location in before_locations.items()
            if self.world.vehicles.get(vehicle_id, {}).get("location") != location
        )
        return {
            "advanced": True,
            "current_time": self.world.current_time,
            "dynamic_alerts": alerts,
            "released_vehicles": released,
            "moved_vehicles": moved,
            "pending_events_remaining": self.world.has_pending_events(),
        }

    def report_status(self) -> dict:
        resolved = [incident_id for incident_id, incident in self.world.incidents.items() if incident["resolved"]]
        unresolved = [
            incident_id for incident_id, incident in self.world.incidents.items() if not incident["resolved"]
        ]
        available = [vehicle_id for vehicle_id, vehicle in self.world.vehicles.items() if vehicle["available"]]
        busy = {
            vehicle_id: {
                "status": vehicle["status"],
                "busy_until": vehicle["busy_until"],
                "next_event_time": vehicle.get("next_event_time"),
                "location": vehicle["location"],
                "next_location": vehicle.get("next_location", vehicle["location"]),
                "assigned_hospital": vehicle.get("assigned_hospital"),
                "mission": copy.deepcopy(vehicle.get("mission")),
            }
            for vehicle_id, vehicle in self.world.vehicles.items()
            if not vehicle["available"]
        }
        return {
            "resolved_incidents": resolved,
            "unresolved_incidents": unresolved,
            "available_vehicles": available,
            "busy_vehicles": busy,
            "current_time": self.world.current_time,
            "active_alerts": list(self.world.event_log),
            "next_event_time": self.world.next_event_time(),
        }


class ValidatorTool:
    """Deterministic safety layer that checks dispatches before state mutation."""

    def __init__(self, world: WorldState):
        self.world = world
        self.violation_count: int = 0

    def validate_dispatch(
        self,
        vehicle_id: str,
        incident_id: str,
        hospital_node: str | None = None,
        route_strategy: str = "fastest",
        count_violation: bool = True,
    ) -> tuple[bool, str]:
        self.world.advance_clock(self.world.current_time)

        vehicle = self.world.vehicles.get(vehicle_id)
        incident = self.world.incidents.get(incident_id)

        if not vehicle:
            return self._fail(f"Vehicle '{vehicle_id}' does not exist.", count_violation)
        if not incident:
            return self._fail(f"Incident '{incident_id}' does not exist.", count_violation)
        if not vehicle["available"]:
            return self._fail(
                f"Vehicle '{vehicle_id}' is {vehicle.get('status', 'busy')} until t={vehicle['busy_until']:.1f}.",
                count_violation,
            )
        if incident["resolved"]:
            return self._fail(f"Incident '{incident_id}' is already fully resolved.", count_violation)

        quantity_capability = self.world.quantity_capability(incident)
        if quantity_capability == "patient_transport" and hospital_node is None:
            hospital_node = self.world.choose_hospital(
                incident["location"],
                vehicle,
                vehicle.get("home_depot"),
                self.world.vehicle_quantity_capacity(vehicle, incident),
                route_strategy=route_strategy,
            )

        contribution, quantity_reserved = self.world.mission_contribution(vehicle, incident, hospital_node)
        if not contribution and quantity_reserved <= 0:
            still_needed = self.world.incident_effective_uncovered_capabilities(incident)
            return self._fail(
                f"Vehicle '{vehicle_id}' (caps: {sorted(vehicle.get('capabilities', []))}) contributes "
                f"nothing new to incident '{incident_id}'. Still needed: {still_needed}.",
                count_violation,
            )

        speed_multiplier = self.world.vehicle_speed_multiplier(vehicle)
        vehicle_type = vehicle.get("type")
        incident_cost, _ = self.world.dijkstra(
            vehicle["location"],
            incident["location"],
            vehicle_type,
            speed_multiplier,
            route_strategy,
        )
        if math.isinf(incident_cost):
            return self._fail(
                f"No passable route from {vehicle['location']} to {incident['location']} "
                f"for vehicle type '{vehicle_type}'.",
                count_violation,
            )

        if quantity_capability == "patient_transport" and quantity_reserved > 0:
            if hospital_node is None:
                return self._fail(
                    f"Vehicle '{vehicle_id}' must include hospital_node to transport patients from '{incident_id}'.",
                    count_violation,
                )
            hospital = self.world.nodes.get(hospital_node)
            if not hospital:
                return self._fail(f"Hospital node '{hospital_node}' does not exist.", count_violation)
            if not hospital.get("hospital"):
                return self._fail(f"Node '{hospital_node}' is not a hospital.", count_violation)
            if quantity_reserved <= 0:
                return self._fail(
                    f"Vehicle '{vehicle_id}' cannot transport any remaining patients from '{incident_id}' "
                    f"under the current vehicle and hospital capacity limits.",
                    count_violation,
                )
            hospital_cost, _ = self.world.dijkstra(
                incident["location"],
                hospital_node,
                vehicle_type,
                speed_multiplier,
                route_strategy,
            )
            if math.isinf(hospital_cost):
                return self._fail(
                    f"No route from {incident['location']} to hospital '{hospital_node}' "
                    f"for vehicle type '{vehicle_type}'.",
                    count_violation,
                )

        if quantity_capability == "bulk_supply" and quantity_reserved <= 0 and "bulk_supply" in contribution:
            return self._fail(
                f"Vehicle '{vehicle_id}' has no remaining bulk supply load for '{incident_id}'.",
                count_violation,
            )

        required_fuel = self.world.mission_fuel_cost(vehicle, incident, hospital_node, route_strategy)
        if math.isinf(required_fuel):
            return self._fail(
                f"Vehicle '{vehicle_id}' cannot complete the planned route for '{incident_id}'.",
                count_violation,
            )
        if float(vehicle.get("fuel", 0.0)) < required_fuel:
            return self._fail(
                f"Vehicle '{vehicle_id}' has insufficient fuel ({vehicle.get('fuel', 0.0):.1f}) "
                f"for the planned mission cost {required_fuel:.1f}.",
                count_violation,
            )

        return True, "OK"

    def _fail(self, msg: str, count_violation: bool = True) -> tuple[bool, str]:
        if count_violation:
            self.violation_count += 1
        return False, f"VALIDATOR ERROR: {msg}"
