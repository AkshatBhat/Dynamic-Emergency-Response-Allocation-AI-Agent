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
    route_strategy: str = "fastest"
    reserved_quantity: int = 0
    quantity_capability: str | None = None
    quantity_remaining_before: int = 0
    provider_count: int = 0
    scarcity_bonus: float = 0.0
    future_option_cost: float = 0.0
    disruption_risk: float = 0.0
    lookahead_gain: float = 0.0
    contingency_penalty: float = 0.0
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
            f"hospital={hospital_text}, route={self.route_strategy}, "
            f"eta={self.travel_time:.1f}, total_trip={self.expected_total_trip_time:.1f}, "
            f"arrival_slack={self.deadline_slack:.1f}, completion_slack={self.completion_slack:.1f}, "
            f"contribution={self.contribution}{quantity_text}, immediate_resolved={resolved_text}, "
            f"projected_pwrs={self.projected_pwrs:.3f}, projected_cap_pwrs={self.projected_cap_pwrs:.3f}, "
            f"projected_resolution_rate={self.projected_resolution_rate:.3f}, "
            f"providers={self.provider_count}, option_cost={self.future_option_cost:.2f}, "
            f"disruption_risk={self.disruption_risk:.2f}, "
            f"lookahead_gain={self.lookahead_gain:.2f}, contingency_penalty={self.contingency_penalty:.2f}, "
            f"alerts={alerts_text}, rationale={rationale_text}"
        )


@dataclass
class DispatchBundle:
    """Structured description of a same-time multi-dispatch plan."""

    bundle_id: str
    actions: list[DispatchCandidate]
    projected_pwrs: float = 0.0
    projected_cap_pwrs: float = 0.0
    projected_resolution_rate: float = 0.0
    projected_deadline_adherence: float = 0.0
    heuristic_score: float = 0.0
    dynamic_alerts: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    immediate_resolved_count: int = 0
    scarce_vehicle_count: int = 0
    future_option_cost: float = 0.0
    concentration_penalty: float = 0.0
    total_completion_slack: float = 0.0
    on_time_severity_sum: float = 0.0
    unresolved_risk: float = 0.0
    disruption_risk: float = 0.0
    incident_spread: int = 0
    lookahead_gain: float = 0.0
    contingency_penalty: float = 0.0

    def brief(self) -> str:
        actions_text = "; ".join(
            f"{action.vehicle_id}->{action.incident_id}"
            + (f" via {action.hospital_node}" if action.hospital_node else "")
            + f" [{action.route_strategy}]"
            for action in self.actions
        )
        rationale_text = "; ".join(self.rationale[:3]) if self.rationale else "none"
        alerts_text = ", ".join(self.dynamic_alerts) if self.dynamic_alerts else "none"
        return (
            f"{self.bundle_id}: actions=[{actions_text}], projected_pwrs={self.projected_pwrs:.3f}, "
            f"projected_cap_pwrs={self.projected_cap_pwrs:.3f}, "
            f"projected_resolution_rate={self.projected_resolution_rate:.3f}, "
            f"projected_deadline_adherence={self.projected_deadline_adherence:.3f}, "
            f"on_time_severity={self.on_time_severity_sum:.1f}, "
            f"scarce_vehicles={self.scarce_vehicle_count}, option_cost={self.future_option_cost:.2f}, "
            f"unresolved_risk={self.unresolved_risk:.2f}, disruption_risk={self.disruption_risk:.2f}, "
            f"lookahead_gain={self.lookahead_gain:.2f}, contingency_penalty={self.contingency_penalty:.2f}, "
            f"spread={self.incident_spread}, concentration_penalty={self.concentration_penalty:.2f}, alerts={alerts_text}, "
            f"rationale={rationale_text}"
        )
