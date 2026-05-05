from __future__ import annotations

from .tools import ValidatorTool
from .world import WorldState


def compute_metrics(
    world: WorldState,
    validator: ValidatorTool,
    step_count: int,
    mode: str,
) -> dict:
    """Compute benchmark metrics for a completed run."""
    incidents = world.incidents
    total_weight = sum(incident["severity"] for incident in incidents.values())

    resolved_weight = sum(
        incident["severity"]
        for incident in incidents.values()
        if incident["resolved"]
        and incident.get("resolved_at") is not None
        and incident["resolved_at"] <= incident["deadline_minutes"]
    )
    pwrs = resolved_weight / total_weight if total_weight > 0 else 0.0

    cap_pwrs_numerator = 0.0
    for incident in incidents.values():
        cap_coverage = world.incident_coverage_fraction(incident)
        if incident["resolved"] and incident.get("resolved_at") is not None:
            if incident["resolved_at"] > incident["deadline_minutes"]:
                lateness = incident["resolved_at"] - incident["deadline_minutes"]
                grace_window = incident["deadline_minutes"]
                time_penalty = max(0.0, 1.0 - (lateness / grace_window))
                cap_coverage *= time_penalty
        cap_pwrs_numerator += incident["severity"] * cap_coverage
    cap_pwrs = cap_pwrs_numerator / total_weight if total_weight > 0 else 0.0

    total_incidents = len(incidents)
    resolved_count = sum(1 for incident in incidents.values() if incident["resolved"])
    resolution_rate = resolved_count / total_incidents if total_incidents > 0 else 0.0

    met_count = 0
    deadline_details: dict = {}
    for incident_id, incident in incidents.items():
        if incident["resolved"] and incident.get("resolved_at") is not None:
            met = incident["resolved_at"] <= incident["deadline_minutes"]
            if met:
                met_count += 1
            deadline_details[incident_id] = {
                "resolved": True,
                "resolved_at": incident["resolved_at"],
                "deadline": incident["deadline_minutes"],
                "met_deadline": met,
            }
        else:
            deadline_details[incident_id] = {"resolved": False, "met_deadline": False}

    deadline_adherence = met_count / total_incidents if total_incidents > 0 else 0.0
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
        "incidents_resolved": {incident_id: incident["resolved"] for incident_id, incident in incidents.items()},
    }
