from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DispatchCandidate:
    """Structured description of a pre-validated next dispatch option."""

    candidate_id: str
    incident_id: str
    vehicle_id: str
    hospital_node: str | None
    travel_time: float
    arrival_time: float
    completion_time: float
    expected_total_trip_time: float
    severity: float
    deadline_minutes: float
    deadline_slack: float
    completion_slack: float
    contribution: list[str]
    uncovered_before: list[str]
    reserved_quantity: int = 0
    quantity_capability: str | None = None
    quantity_remaining_before: int = 0
    provider_count: int = 0
    scarcity_bonus: float = 0.0
    future_option_cost: float = 0.0
    immediate_resolved: bool = False
    projected_pwrs: float = 0.0
    projected_cap_pwrs: float = 0.0
    projected_resolution_rate: float = 0.0
    projected_deadline_adherence: float = 0.0
    heuristic_score: float = 0.0
    dynamic_alerts: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)

    def brief(self) -> str:
        hospital_text = self.hospital_node if self.hospital_node else "none"
        resolved_text = "yes" if self.immediate_resolved else "no"
        alerts_text = ", ".join(self.dynamic_alerts) if self.dynamic_alerts else "none"
        rationale_text = "; ".join(self.rationale[:3]) if self.rationale else "none"
        quantity_text = (
            f", quantity={self.reserved_quantity}/{self.quantity_remaining_before} for {self.quantity_capability}"
            if self.quantity_capability and self.quantity_remaining_before > 0
            else ""
        )
        return (
            f"{self.candidate_id}: dispatch {self.vehicle_id} -> {self.incident_id}, "
            f"hospital={hospital_text}, eta={self.travel_time:.1f}, total_trip={self.expected_total_trip_time:.1f}, "
            f"arrival_slack={self.deadline_slack:.1f}, completion_slack={self.completion_slack:.1f}, "
            f"contribution={self.contribution}{quantity_text}, immediate_resolved={resolved_text}, "
            f"projected_pwrs={self.projected_pwrs:.3f}, projected_cap_pwrs={self.projected_cap_pwrs:.3f}, "
            f"projected_resolution_rate={self.projected_resolution_rate:.3f}, "
            f"providers={self.provider_count}, option_cost={self.future_option_cost:.2f}, "
            f"alerts={alerts_text}, rationale={rationale_text}"
        )
