from __future__ import annotations

import math

from ..metrics import compute_metrics
from ..tools import ValidatorTool, WorldTool
from ..world import WorldState


def run_deterministic(scenario_dict: dict) -> dict:
    """
    Greedy rule-based dispatcher.

    Rank incidents by severity descending and deadline ascending, then dispatch
    the nearest feasible vehicle that contributes at least one uncovered capability.
    """
    world = WorldState(scenario_dict)
    world_tool = WorldTool(world)
    validator = ValidatorTool(world)
    step_count = 0
    max_steps = 100

    while step_count < max_steps:
        open_incidents = world.open_incidents()
        if not open_incidents:
            break

        ranked = sorted(
            open_incidents.items(),
            key=lambda item: (-item[1]["severity"], item[1]["deadline_minutes"]),
        )

        dispatched = False
        for incident_id, incident in ranked:
            still_needed = set(world.incident_effective_uncovered_capabilities(incident))
            if not still_needed:
                continue

            best_vehicle_id: str | None = None
            best_cost: float = math.inf
            best_hospital: str | None = None

            for vehicle_id, vehicle in world.vehicles.items():
                if not vehicle["available"]:
                    continue

                vehicle_type = vehicle.get("type")
                vehicle_caps = set(vehicle["capabilities"])
                contribution, quantity_reserved = world.mission_contribution(vehicle, incident)
                contribution = set(contribution)
                if quantity_reserved > 0 and world.quantity_capability(incident):
                    contribution.add(world.quantity_capability(incident))
                if not contribution:
                    continue

                hospital_node = None
                if world.quantity_capability(incident) == "patient_transport" and "patient_transport" in vehicle_caps:
                    hospital_node = world.choose_hospital(
                        incident["location"],
                        vehicle,
                        vehicle.get("home_depot"),
                        world.vehicle_quantity_capacity(vehicle, incident),
                    )
                valid, _ = validator.validate_dispatch(
                    vehicle_id=vehicle_id,
                    incident_id=incident_id,
                    hospital_node=hospital_node,
                    count_violation=False,
                )
                if not valid:
                    continue

                cost, _ = world.dijkstra(
                    vehicle["location"],
                    incident["location"],
                    vehicle_type,
                    world.vehicle_speed_multiplier(vehicle),
                )
                if math.isinf(cost):
                    continue

                if cost < best_cost:
                    best_cost = cost
                    best_vehicle_id = vehicle_id
                    best_hospital = hospital_node

            if best_vehicle_id is None:
                continue

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
            break

        if not dispatched:
            advanced = world_tool.advance_to_next_event()
            if advanced.get("advanced"):
                print(
                    f"  [Deterministic] Waiting to t={advanced['current_time']:.1f} "
                    f"| released={advanced.get('released_vehicles', [])} "
                    f"| alerts={advanced.get('dynamic_alerts', [])}"
                )
                continue
            print("  [Deterministic] No valid dispatches possible; stopping.")
            break

    return compute_metrics(world, validator, step_count, "deterministic")
