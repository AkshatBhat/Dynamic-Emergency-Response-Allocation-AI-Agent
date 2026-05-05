from __future__ import annotations

import json
import math
import re

from .planning import DispatchCandidate
from ..metrics import compute_metrics
from ..tools import ValidatorTool, WorldTool
from ..world import WorldState


class RescueAgent:
    """
    Hybrid agent that combines deterministic feasibility checks with candidate
    rollout scoring and optional LLM-guided action selection.
    """

    def __init__(
        self,
        world: WorldState,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-5",
        use_llm_for_ethics: bool = True,
        provider: str = "anthropic",
        use_llm_for_planning: bool = True,
    ):
        self.world = world
        self.tool = WorldTool(world)
        self.validator = ValidatorTool(world)
        self.api_key = api_key
        self.model = model
        self.use_llm_for_ethics = use_llm_for_ethics
        self.provider = provider
        self.use_llm_for_planning = use_llm_for_planning
        self.plan_queue: list[tuple[str, dict]] = []
        self.memory: list[dict] = []
        self.step_count: int = 0
        self.selection_history: list[dict] = []
        self.max_candidate_pool: int = 12
        self.max_prompt_candidates: int = 5
        self.rollout_depth: int = 5

    def observe(self) -> tuple[dict, dict, dict, list[str]]:
        """Poll simulation state and proactively fire pending dynamic triggers."""
        alerts = self.world.advance_clock(self.world.current_time)
        incidents = self.tool.get_incidents()
        vehicles = self.tool.get_vehicles()
        map_state = self.tool.get_map_state()
        return incidents, vehicles, map_state, alerts

    def plan(self, incidents: dict, vehicles: dict) -> None:
        del vehicles
        ranked = sorted(
            incidents.items(),
            key=lambda item: (-item[1]["severity"], item[1]["deadline_minutes"]),
        )
        if self.use_llm_for_ethics and self._is_ethical_tie(ranked):
            ranked = self._llm_ethical_sort(ranked)
        self.plan_queue = list(ranked)

    def act(self) -> bool:
        """
        Generate candidate dispatches, project their downstream effect, and
        execute the best available choice.
        """
        candidates = self._generate_dispatch_candidates()
        if not candidates:
            self._remember(
                "blocked",
                "No feasible dispatch candidates remain under current world constraints.",
            )
            return False

        selected = self._select_candidate(candidates)
        valid, err_msg = self.validator.validate_dispatch(
            selected.vehicle_id,
            selected.incident_id,
            selected.hospital_node,
        )
        if not valid:
            self._remember("validation_failure", err_msg)
            print(
                f"  [AgentKit] Post-selection validator rejection "
                f"{selected.vehicle_id}→{selected.incident_id}: {err_msg}"
            )
            remaining = [candidate for candidate in candidates if candidate.candidate_id != selected.candidate_id]
            if not remaining:
                return False
            selected = remaining[0]

        result = self.tool.dispatch_vehicle(
            vehicle_id=selected.vehicle_id,
            incident_id=selected.incident_id,
            hospital_node=selected.hospital_node,
        )
        self.step_count += 1
        resolved_flag = result.get("incident_resolved", False)
        print(
            f"  [AgentKit] {selected.vehicle_id} → {selected.incident_id} | "
            f"t={result.get('travel_time_minutes', 0):.1f}min | resolved={resolved_flag}"
        )
        self._record_execution(selected, result, candidates)
        self._prune_plan_queue()
        return bool(self.plan_queue) or bool(self.world.open_incidents())

    def _wait_for_next_event(self) -> bool:
        advanced = self.tool.advance_to_next_event()
        if not advanced.get("advanced"):
            return False
        summary = (
            f"Advanced to t={advanced['current_time']:.1f}; "
            f"released={advanced.get('released_vehicles', [])}; "
            f"alerts={advanced.get('dynamic_alerts', [])}"
        )
        self._remember("wait", summary)
        print(f"  [AgentKit] WAIT | {summary}")
        return True

    def replan(self, alerts: list[str]) -> None:
        """Flush and rebuild the plan after dynamic alerts."""
        print(f"  [AgentKit] REPLAN triggered by {len(alerts)} alert(s): {alerts}")
        self.plan_queue = []
        incidents, vehicles, _, _ = self.observe()
        self.plan(incidents, vehicles)

    def _is_ethical_tie(self, ranked: list) -> bool:
        if len(ranked) < 2:
            return False
        _, incident0 = ranked[0]
        _, incident1 = ranked[1]
        return (
            incident0["severity"] == incident1["severity"]
            and incident0["deadline_minutes"] == incident1["deadline_minutes"]
        )

    def _llm_ethical_sort(self, ranked: list) -> list:
        """Use the LLM only to break true ethical ties."""
        try:
            tied = []
            for incident_id, incident in ranked[:2]:
                tied.append(
                    {
                        "incident_id": incident_id,
                        "type": incident.get("type", "unknown"),
                        "location": incident.get("location", "unknown"),
                        "severity": incident.get("severity"),
                        "deadline_minutes": incident.get("deadline_minutes"),
                        "required_capabilities": incident.get("required_capabilities", []),
                        "patients": incident.get("patients", 0),
                    }
                )

            prompt = (
                "Two emergency incidents have identical severity and deadline. "
                "As an emergency coordinator, determine which to prioritize first "
                "based on humanitarian considerations (threat to life, patient count, "
                "vulnerability of affected population).\n\n"
                f"Incident A: {json.dumps(tied[0], indent=2)}\n\n"
                f"Incident B: {json.dumps(tied[1], indent=2)}\n\n"
                "Return a JSON array of incident IDs in priority order (highest first). "
                'Example: ["INC_001", "INC_002"]\n'
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
                for incident_id in order:
                    if incident_id in ranked_dict and incident_id not in seen:
                        reordered.append((incident_id, ranked_dict[incident_id]))
                        seen.add(incident_id)
                for incident_id, incident in ranked:
                    if incident_id not in seen:
                        reordered.append((incident_id, incident))
                return reordered
        except Exception as exc:
            print(f"  [AgentKit] LLM ethical sort failed (using original order): {exc}")
        return ranked

    def _estimate_mission_times(
        self,
        vehicle: dict,
        incident: dict,
        hospital_node: str | None,
    ) -> tuple[float, float, float, float]:
        arrival_trip, total_trip = self.world.mission_time_estimate(vehicle, incident, hospital_node)
        arrival_time = self.world.current_time + arrival_trip
        completion_time = self.world.current_time + total_trip
        return arrival_trip, total_trip, arrival_time, completion_time

    def _incident_urgency_value(
        self,
        incident: dict,
        completion_slack: float | None = None,
    ) -> float:
        required = max(1, len(incident.get("required_capabilities", [])))
        uncovered = len(self.world.incident_effective_uncovered_capabilities(incident))
        remaining_work = uncovered / required

        required_quantity = self.world.required_quantity(incident)
        if required_quantity > 0:
            remaining_ratio = self.world.remaining_quantity(incident) / max(1, required_quantity)
            remaining_work = max(remaining_work, remaining_ratio)

        slack = (
            completion_slack
            if completion_slack is not None
            else incident["deadline_minutes"] - self.world.current_time
        )
        if slack <= 0:
            deadline_pressure = 3.0 + min(abs(slack), 30.0) / 10.0
        else:
            deadline_pressure = 1.0 + (1.0 / max(1.0, slack))
        return incident["severity"] * deadline_pressure * max(0.25, remaining_work)

    def _candidate_hospital(
        self,
        vehicle: dict,
        incident: dict,
    ) -> str | None:
        quantity_capability = self.world.quantity_capability(incident)
        if quantity_capability != "patient_transport":
            return None
        if "patient_transport" not in set(vehicle.get("capabilities", [])):
            return None
        return self.world.choose_hospital(
            incident["location"],
            vehicle,
            vehicle.get("home_depot"),
            self.world.vehicle_quantity_capacity(vehicle, incident),
        )

    def _vehicle_can_help_incident(
        self,
        vehicle_id: str,
        incident_id: str,
    ) -> bool:
        vehicle = self.world.vehicles.get(vehicle_id)
        incident = self.world.incidents.get(incident_id)
        if not vehicle or not incident or not vehicle.get("available") or incident.get("resolved"):
            return False

        hospital_node = self._candidate_hospital(vehicle, incident)
        contribution, reserved_quantity = self.world.mission_contribution(vehicle, incident, hospital_node)
        if not contribution and reserved_quantity <= 0:
            return False
        valid, _ = self.validator.validate_dispatch(
            vehicle_id,
            incident_id,
            hospital_node,
            count_violation=False,
        )
        return valid

    def _provider_count_for_incident(self, incident_id: str) -> int:
        count = 0
        for vehicle_id, vehicle in self.world.vehicles.items():
            if not vehicle.get("available"):
                continue
            if self._vehicle_can_help_incident(vehicle_id, incident_id):
                count += 1
        return count

    def _vehicle_future_option_cost(
        self,
        vehicle_id: str,
        selected_incident_id: str,
    ) -> float:
        vehicle = self.world.vehicles[vehicle_id]
        cost = 0.0

        for incident_id, incident in self.world.open_incidents().items():
            if incident_id == selected_incident_id:
                continue

            hospital_node = self._candidate_hospital(vehicle, incident)
            contribution, reserved_quantity = self.world.mission_contribution(vehicle, incident, hospital_node)
            if not contribution and reserved_quantity <= 0:
                continue

            valid, _ = self.validator.validate_dispatch(
                vehicle_id,
                incident_id,
                hospital_node,
                count_violation=False,
            )
            if not valid:
                continue

            alternatives = 0
            for other_vehicle_id, other_vehicle in self.world.vehicles.items():
                if other_vehicle_id == vehicle_id or not other_vehicle.get("available"):
                    continue
                other_hospital = self._candidate_hospital(other_vehicle, incident)
                other_contribution, other_reserved = self.world.mission_contribution(
                    other_vehicle,
                    incident,
                    other_hospital,
                )
                if not other_contribution and other_reserved <= 0:
                    continue
                other_valid, _ = self.validator.validate_dispatch(
                    other_vehicle_id,
                    incident_id,
                    other_hospital,
                    count_violation=False,
                )
                if other_valid:
                    alternatives += 1

            urgency = self._incident_urgency_value(incident)
            if alternatives == 0:
                cost += urgency
            elif alternatives == 1:
                cost += urgency * 0.35
        return cost

    def _generate_dispatch_candidates(self) -> list[DispatchCandidate]:
        self._prune_plan_queue()
        if not self.plan_queue:
            return []

        raw_candidates: list[
            tuple[
                float,
                str,
                str,
                str | None,
                list[str],
                list[str],
                int,
                str | None,
                int,
                int,
                float,
                float,
                float,
                float,
                float,
                float,
                float,
            ]
        ] = []
        for incident_id, _ in self.plan_queue:
            incident = self.world.incidents.get(incident_id)
            if not incident or incident["resolved"]:
                continue
            uncovered = self.world.incident_effective_uncovered_capabilities(incident)
            if not uncovered:
                continue

            for vehicle_id, vehicle in self.world.vehicles.items():
                if not vehicle["available"]:
                    continue
                quantity_capability = self.world.quantity_capability(incident)
                quantity_remaining = self.world.remaining_uncommitted_quantity(incident)
                hospital_node = self._candidate_hospital(vehicle, incident)
                contribution, reserved_quantity = self.world.mission_contribution(vehicle, incident, hospital_node)
                if not contribution:
                    continue

                valid, _ = self.validator.validate_dispatch(
                    vehicle_id,
                    incident_id,
                    hospital_node,
                    count_violation=False,
                )
                if not valid:
                    continue

                travel_time, total_trip_time, arrival_time, completion_time = self._estimate_mission_times(
                    vehicle,
                    incident,
                    hospital_node,
                )
                if math.isinf(travel_time) or math.isinf(total_trip_time):
                    continue
                deadline_slack = incident["deadline_minutes"] - arrival_time
                completion_slack = incident["deadline_minutes"] - completion_time
                provider_count = self._provider_count_for_incident(incident_id)
                scarcity_bonus = 1.0 / max(1, provider_count)
                future_option_cost = self._vehicle_future_option_cost(vehicle_id, incident_id)
                pre_score = self._candidate_pre_score(
                    incident,
                    uncovered,
                    contribution,
                    reserved_quantity,
                    quantity_remaining,
                    completion_slack,
                    scarcity_bonus,
                    future_option_cost,
                )
                raw_candidates.append(
                    (
                        pre_score,
                        incident_id,
                        vehicle_id,
                        hospital_node,
                        contribution,
                        uncovered,
                        reserved_quantity,
                        quantity_capability,
                        quantity_remaining,
                        provider_count,
                        travel_time,
                        total_trip_time,
                        arrival_time,
                        completion_time,
                        deadline_slack,
                        completion_slack,
                        future_option_cost,
                    )
                )

        if not raw_candidates:
            return []

        raw_candidates.sort(key=lambda item: item[0], reverse=True)
        shortlisted = raw_candidates[: self.max_candidate_pool]
        candidates: list[DispatchCandidate] = []
        for idx, (
            _,
            incident_id,
            vehicle_id,
            hospital_node,
            contribution,
            uncovered,
            reserved_quantity,
            quantity_capability,
            quantity_remaining,
            provider_count,
            travel_time,
            total_trip_time,
            arrival_time,
            completion_time,
            deadline_slack,
            completion_slack,
            future_option_cost,
        ) in enumerate(shortlisted, start=1):
            incident = self.world.incidents[incident_id]
            candidate = DispatchCandidate(
                candidate_id=f"C{idx}",
                incident_id=incident_id,
                vehicle_id=vehicle_id,
                hospital_node=hospital_node,
                travel_time=travel_time,
                arrival_time=arrival_time,
                completion_time=completion_time,
                expected_total_trip_time=total_trip_time,
                severity=incident["severity"],
                deadline_minutes=incident["deadline_minutes"],
                deadline_slack=deadline_slack,
                completion_slack=completion_slack,
                contribution=contribution,
                uncovered_before=uncovered,
                reserved_quantity=reserved_quantity,
                quantity_capability=quantity_capability,
                quantity_remaining_before=quantity_remaining,
                provider_count=provider_count,
                scarcity_bonus=1.0 / max(1, provider_count),
                future_option_cost=future_option_cost,
            )
            self._project_candidate(candidate)
            candidates.append(candidate)

        candidates.sort(key=lambda candidate: candidate.heuristic_score, reverse=True)
        for idx, candidate in enumerate(candidates, start=1):
            candidate.candidate_id = f"C{idx}"
        return candidates[: self.max_prompt_candidates]

    def _candidate_pre_score(
        self,
        incident: dict,
        uncovered: list[str],
        contribution: list[str],
        reserved_quantity: int,
        quantity_remaining: int,
        completion_slack: float,
        scarcity_bonus: float,
        future_option_cost: float,
    ) -> float:
        quantity_capability = self.world.quantity_capability(incident)
        boolean_needed = [capability for capability in uncovered if capability != quantity_capability]
        boolean_contrib = [capability for capability in contribution if capability != quantity_capability]
        quantity_ratio = 0.0
        if quantity_capability and quantity_capability in uncovered and quantity_remaining > 0:
            quantity_ratio = reserved_quantity / quantity_remaining
        delivered_units = len(boolean_contrib) + min(quantity_ratio, 1.0)
        total_units = len(boolean_needed) + (1 if quantity_capability and quantity_capability in uncovered else 0)
        contribution_ratio = delivered_units / total_units if total_units else 1.0
        resolves = len(boolean_contrib) == len(boolean_needed) and (
            not quantity_capability or quantity_capability not in uncovered or reserved_quantity >= quantity_remaining
        )
        urgency = self._incident_urgency_value(incident, completion_slack)
        on_time_resolution = incident["severity"] if resolves and completion_slack >= 0 else 0.0
        partial_value = urgency * contribution_ratio
        slack_bonus = max(min(completion_slack, 25.0), -25.0)
        resolve_bonus = 14.0 if resolves else 0.0
        scarcity_value = urgency * scarcity_bonus * 2.5
        preservation_penalty = future_option_cost * 2.0
        return (
            on_time_resolution * 100.0
            + partial_value * 22.0
            + resolve_bonus
            + slack_bonus
            + scarcity_value
            - preservation_penalty
        )

    def _project_candidate(self, candidate: DispatchCandidate) -> None:
        sim_world = self.world.clone()
        sim_tool = WorldTool(sim_world)
        sim_validator = ValidatorTool(sim_world)

        valid, err_msg = sim_validator.validate_dispatch(
            candidate.vehicle_id,
            candidate.incident_id,
            candidate.hospital_node,
            count_violation=False,
        )
        if not valid:
            candidate.heuristic_score = float("-inf")
            candidate.rationale.append(err_msg)
            return

        result = sim_tool.dispatch_vehicle(
            vehicle_id=candidate.vehicle_id,
            incident_id=candidate.incident_id,
            hospital_node=candidate.hospital_node,
        )
        candidate.immediate_resolved = result.get("incident_resolved", False)
        candidate.dynamic_alerts = list(result.get("dynamic_alerts", []))

        self._rollout_projection(sim_world, max_steps=max(0, self.rollout_depth - 1))
        projected = self._state_objectives(sim_world)
        candidate.projected_pwrs = projected["pwrs"]
        candidate.projected_cap_pwrs = projected["cap_pwrs"]
        candidate.projected_resolution_rate = projected["resolution_rate"]
        candidate.projected_deadline_adherence = projected["deadline_adherence"]
        candidate.heuristic_score = self._combine_candidate_score(candidate)
        candidate.rationale = self._candidate_rationale(candidate)

    def _rollout_projection(self, sim_world: WorldState, max_steps: int) -> None:
        sim_tool = WorldTool(sim_world)
        sim_validator = ValidatorTool(sim_world)
        dispatches_taken = 0
        idle_iterations = 0

        while dispatches_taken < max_steps and idle_iterations < max_steps * 2:
            best_action = self._best_rollout_action(sim_world, sim_validator)
            if best_action is None:
                advanced = sim_tool.advance_to_next_event()
                if not advanced.get("advanced"):
                    break
                idle_iterations += 1
                continue
            vehicle_id, incident_id, hospital_node = best_action
            valid, _ = sim_validator.validate_dispatch(
                vehicle_id,
                incident_id,
                hospital_node,
                count_violation=False,
            )
            if not valid:
                break
            sim_tool.dispatch_vehicle(vehicle_id=vehicle_id, incident_id=incident_id, hospital_node=hospital_node)
            dispatches_taken += 1

    def _best_rollout_action(
        self,
        sim_world: WorldState,
        sim_validator: ValidatorTool,
    ) -> tuple[str, str, str | None] | None:
        best_action: tuple[str, str, str | None] | None = None
        best_score = float("-inf")

        ranked_incidents = sorted(
            sim_world.open_incidents().items(),
            key=lambda item: (-item[1]["severity"], item[1]["deadline_minutes"]),
        )
        for incident_id, incident in ranked_incidents:
            uncovered = sim_world.incident_effective_uncovered_capabilities(incident)
            if not uncovered:
                continue
            for vehicle_id, vehicle in sim_world.vehicles.items():
                if not vehicle["available"]:
                    continue
                quantity_capability = sim_world.quantity_capability(incident)
                quantity_remaining = sim_world.remaining_uncommitted_quantity(incident)
                hospital_node = None
                if quantity_capability == "patient_transport" and "patient_transport" in set(vehicle["capabilities"]):
                    hospital_node = sim_world.choose_hospital(
                        incident["location"],
                        vehicle,
                        vehicle.get("home_depot"),
                        sim_world.vehicle_quantity_capacity(vehicle, incident),
                    )
                contribution, reserved_quantity = sim_world.mission_contribution(vehicle, incident, hospital_node)
                if not contribution:
                    continue
                valid, _ = sim_validator.validate_dispatch(
                    vehicle_id,
                    incident_id,
                    hospital_node,
                    count_violation=False,
                )
                if not valid:
                    continue
                _, total_trip_time = sim_world.mission_time_estimate(vehicle, incident, hospital_node)
                if math.isinf(total_trip_time):
                    continue
                completion_time = sim_world.current_time + total_trip_time
                completion_slack = incident["deadline_minutes"] - completion_time
                provider_count = 0
                for other_vehicle_id, other_vehicle in sim_world.vehicles.items():
                    if not other_vehicle.get("available"):
                        continue
                    other_hospital = None
                    if quantity_capability == "patient_transport" and "patient_transport" in set(
                        other_vehicle["capabilities"]
                    ):
                        other_hospital = sim_world.choose_hospital(
                            incident["location"],
                            other_vehicle,
                            other_vehicle.get("home_depot"),
                            sim_world.vehicle_quantity_capacity(other_vehicle, incident),
                        )
                    other_contribution, other_reserved = sim_world.mission_contribution(
                        other_vehicle,
                        incident,
                        other_hospital,
                    )
                    if not other_contribution and other_reserved <= 0:
                        continue
                    other_valid, _ = sim_validator.validate_dispatch(
                        other_vehicle_id,
                        incident_id,
                        other_hospital,
                        count_violation=False,
                    )
                    if other_valid:
                        provider_count += 1
                score = self._candidate_pre_score(
                    incident,
                    uncovered,
                    contribution,
                    reserved_quantity,
                    quantity_remaining,
                    completion_slack,
                    1.0 / max(1, provider_count),
                    0.0,
                )
                if score > best_score:
                    best_score = score
                    best_action = (vehicle_id, incident_id, hospital_node)

        return best_action

    def _state_objectives(self, world: WorldState) -> dict[str, float]:
        incidents = world.incidents
        total_weight = sum(incident["severity"] for incident in incidents.values())
        if total_weight <= 0:
            return {
                "pwrs": 0.0,
                "cap_pwrs": 0.0,
                "resolution_rate": 0.0,
                "deadline_adherence": 0.0,
            }

        on_time_weight = 0.0
        cap_weight = 0.0
        resolved_count = 0
        deadline_met_count = 0
        total_incidents = len(incidents)

        for incident in incidents.values():
            coverage = world.incident_coverage_fraction(incident)

            if incident["resolved"]:
                resolved_count += 1
                resolved_at = incident.get("resolved_at")
                if resolved_at is not None and resolved_at <= incident["deadline_minutes"]:
                    deadline_met_count += 1
                    on_time_weight += incident["severity"]
                if resolved_at is not None and resolved_at > incident["deadline_minutes"]:
                    lateness = resolved_at - incident["deadline_minutes"]
                    grace_window = max(1.0, float(incident["deadline_minutes"]))
                    coverage *= max(0.0, 1.0 - (lateness / grace_window))

            cap_weight += incident["severity"] * coverage

        return {
            "pwrs": on_time_weight / total_weight,
            "cap_pwrs": cap_weight / total_weight,
            "resolution_rate": resolved_count / total_incidents if total_incidents else 0.0,
            "deadline_adherence": deadline_met_count / total_incidents if total_incidents else 0.0,
        }

    def _combine_candidate_score(self, candidate: DispatchCandidate) -> float:
        score = 0.0
        score += candidate.projected_pwrs * 1000.0
        score += candidate.projected_cap_pwrs * 250.0
        score += candidate.projected_resolution_rate * 60.0
        score += candidate.projected_deadline_adherence * 60.0
        score += max(min(candidate.completion_slack, 20.0), -20.0) * 1.2
        score += candidate.scarcity_bonus * 12.0
        score -= candidate.future_option_cost * 2.0
        if candidate.immediate_resolved and candidate.completion_slack >= 0:
            score += 15.0
        if candidate.dynamic_alerts:
            score -= 8.0 * len(candidate.dynamic_alerts)
        return score

    def _candidate_rationale(self, candidate: DispatchCandidate) -> list[str]:
        reasons = [
            f"projects PWRS {candidate.projected_pwrs:.3f}",
            f"projects Cap-PWRS {candidate.projected_cap_pwrs:.3f}",
            f"completion slack {candidate.completion_slack:.1f} min",
        ]
        if candidate.immediate_resolved:
            reasons.append("immediately resolves the incident")
        else:
            reasons.append(f"adds partial coverage {candidate.contribution}")
        if candidate.quantity_capability and candidate.quantity_remaining_before > 0:
            reasons.append(
                f"commits {candidate.reserved_quantity}/{candidate.quantity_remaining_before} "
                f"units of {candidate.quantity_capability}"
            )
        if candidate.provider_count > 0:
            reasons.append(f"{candidate.provider_count} feasible provider(s) exist for this incident")
        if candidate.future_option_cost > 0:
            reasons.append(f"using this vehicle consumes future option value {candidate.future_option_cost:.2f}")
        if candidate.dynamic_alerts:
            reasons.append("may trigger dynamic alert handling")
        return reasons

    def _select_candidate(self, candidates: list[DispatchCandidate]) -> DispatchCandidate:
        if not self._can_use_llm_for_planning():
            return candidates[0]
        if len(candidates) == 1:
            return candidates[0]
        if not self._should_consult_llm(candidates):
            return candidates[0]

        selected = self._llm_select_candidate(candidates)
        return selected or candidates[0]

    def _can_use_llm_for_planning(self) -> bool:
        return bool(self.use_llm_for_planning and self.api_key)

    def _should_consult_llm(self, candidates: list[DispatchCandidate]) -> bool:
        if len(candidates) < 2:
            return False
        top = candidates[0]
        runner_up = candidates[1]
        score_gap = top.heuristic_score - runner_up.heuristic_score
        relative_gap = score_gap / max(1.0, abs(top.heuristic_score))

        close_projected_pwrs = abs(top.projected_pwrs - runner_up.projected_pwrs) <= 0.05
        close_projected_cap = abs(top.projected_cap_pwrs - runner_up.projected_cap_pwrs) <= 0.08
        dynamic_context = bool(self.world.event_log)

        if dynamic_context:
            return True
        if relative_gap <= 0.08:
            return True
        if close_projected_pwrs and close_projected_cap:
            return True
        return False

    def _llm_select_candidate(self, candidates: list[DispatchCandidate]) -> DispatchCandidate | None:
        prompt = self._build_candidate_prompt(candidates)
        try:
            if self.provider == "gemini":
                import google.generativeai as genai

                genai.configure(api_key=self.api_key)
                gmodel = genai.GenerativeModel(self.model)
                gresponse = gmodel.generate_content(prompt)
                raw = gresponse.text if gresponse.text else "{}"
            else:
                import anthropic

                client = anthropic.Anthropic(api_key=self.api_key)
                response = client.messages.create(
                    model=self.model,
                    max_tokens=256,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text if response.content else "{}"

            chosen_id, reason = self._parse_candidate_choice(raw)
            if chosen_id is None:
                self._remember("selection_parse_failure", raw[:300])
                return None

            for candidate in candidates:
                if candidate.candidate_id == chosen_id:
                    print(
                        f"  [AgentKit] LLM selected {chosen_id}: "
                        f"{candidate.vehicle_id} -> {candidate.incident_id}"
                    )
                    self.selection_history.append(
                        {
                            "time": self.world.current_time,
                            "candidate_id": chosen_id,
                            "reason": reason,
                            "heuristic_score": candidate.heuristic_score,
                        }
                    )
                    if reason:
                        self._remember("llm_selection", reason)
                    return candidate
        except Exception as exc:
            self._remember("llm_selection_error", str(exc))
            print(f"  [AgentKit] LLM candidate selection failed; using heuristic fallback: {exc}")
        return None

    def _build_candidate_prompt(self, candidates: list[DispatchCandidate]) -> str:
        open_incidents = []
        for incident_id, incident in self.world.open_incidents().items():
            uncovered = self.world.incident_effective_uncovered_capabilities(incident)
            open_incidents.append(
                {
                    "incident_id": incident_id,
                    "severity": incident["severity"],
                    "deadline_minutes": incident["deadline_minutes"],
                    "uncovered_capabilities": uncovered,
                    "required_quantity": incident.get("required_quantity", 0),
                    "remaining_quantity": self.world.remaining_quantity(incident),
                    "committed_quantity": incident.get("committed_quantity", 0),
                    "quantity_capability": incident.get("quantity_capability"),
                }
            )
        open_incidents.sort(key=lambda item: (-item["severity"], item["deadline_minutes"]))

        recent_lessons = [
            entry["summary"]
            for entry in self.memory
            if entry.get("kind") in {"llm_selection", "reflection", "blocked", "validation_failure"}
        ][-3:]

        prompt = (
            "You are choosing the next emergency dispatch from a pre-validated shortlist. "
            "Do not invent a new action. Choose exactly one candidate ID.\n\n"
            f"Current simulation time: {self.world.current_time:.1f}\n"
            f"Active alerts: {self.world.event_log[-2:] if self.world.event_log else []}\n"
            f"Open incidents: {json.dumps(open_incidents[:5], indent=2)}\n"
            f"Recent lessons: {json.dumps(recent_lessons, indent=2)}\n\n"
            "Candidate options:\n"
        )
        for candidate in candidates:
            prompt += f"- {candidate.brief()}\n"
        prompt += (
            "\nSelection criteria:\n"
            "1. Maximize projected on-time severity-weighted resolution.\n"
            "2. Preserve unique or scarce vehicles for incidents that few other vehicles can satisfy.\n"
            "3. Prefer candidates with stronger projected PWRS, then Cap-PWRS.\n"
            "4. Use completion slack, partial-coverage value, and alert risk only as tie-breakers.\n\n"
            'Return ONLY a JSON object like {"candidate_id": "C2", "reason": "..."}.'
        )
        return prompt

    def _parse_candidate_choice(self, raw: str) -> tuple[str | None, str]:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            candidate_id_match = re.search(r"C\d+", raw)
            return (candidate_id_match.group(0), "") if candidate_id_match else (None, "")

        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            candidate_id_match = re.search(r"C\d+", raw)
            return (candidate_id_match.group(0), "") if candidate_id_match else (None, "")

        candidate_id = payload.get("candidate_id")
        reason = payload.get("reason", "")
        return candidate_id, reason

    def _record_execution(
        self,
        selected: DispatchCandidate,
        result: dict,
        candidates: list[DispatchCandidate],
    ) -> None:
        top = candidates[0]
        summary = (
            f"Selected {selected.candidate_id} ({selected.vehicle_id}->{selected.incident_id}) "
            f"with projected PWRS {selected.projected_pwrs:.3f}; "
            f"actual resolved={result.get('incident_resolved', False)}."
        )
        self._remember("execution", summary)
        if selected.candidate_id != top.candidate_id:
            self._remember(
                "reflection",
                f"LLM overrode heuristic {top.candidate_id} in favor of {selected.candidate_id}.",
            )
        if result.get("dynamic_alerts"):
            self._remember(
                "reflection",
                f"Dynamic alert triggered after dispatch: {result['dynamic_alerts']}",
            )

    def _remember(self, kind: str, summary: str) -> None:
        self.memory.append(
            {
                "kind": kind,
                "summary": summary,
                "time": self.world.current_time,
            }
        )

    def _prune_plan_queue(self) -> None:
        self.plan_queue = [
            (incident_id, incident)
            for incident_id, incident in self.plan_queue
            if incident_id in self.world.incidents and not self.world.incidents[incident_id]["resolved"]
        ]

    def run(self) -> int:
        """Main observe → plan → act → replan loop."""
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
                if self._wait_for_next_event():
                    continue
                break

            prev_steps = self.step_count
            can_continue = self.act()
            if self.step_count == prev_steps:
                if self._wait_for_next_event():
                    continue
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
    use_llm_for_planning: bool = True,
) -> dict:
    """Instantiate RescueAgent, run it, and compute metrics."""
    world = WorldState(scenario_dict)
    agent = RescueAgent(
        world,
        api_key=api_key,
        model=model,
        use_llm_for_ethics=use_llm_for_ethics,
        provider=provider,
        use_llm_for_planning=use_llm_for_planning,
    )
    step_count = agent.run()
    return compute_metrics(world, agent.validator, step_count, "agentkit")
