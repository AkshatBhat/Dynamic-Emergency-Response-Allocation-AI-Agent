from __future__ import annotations

import json
import math
import re
from collections import Counter

from .planning import DispatchBundle, DispatchCandidate
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
        self.max_prompt_candidates: int = 6
        self.rollout_depth: int = 5
        self.max_bundle_size: int = 2
        self.max_bundle_pool: int = 10
        self.lookahead_event_budget: int = 2
        self.lookahead_beam_width: int = 3
        self.lookahead_discount: float = 0.92
        self.planner_mode: str = "static"
        self.score_weights: dict[str, float] = {}
        self._set_score_weights()

    def _set_score_weights(self) -> None:
        weights_by_mode = {
            "static": {
                "candidate_pwrs": 1000.0,
                "candidate_cap": 250.0,
                "candidate_resolution": 60.0,
                "candidate_deadline": 60.0,
                "candidate_slack": 1.2,
                "candidate_scarcity": 12.0,
                "candidate_future_cost": 2.0,
                "candidate_disruption": 6.0,
                "candidate_lookahead": 0.35,
                "candidate_contingency": 0.35,
                "bundle_pwrs": 1100.0,
                "bundle_cap": 260.0,
                "bundle_resolution": 80.0,
                "bundle_deadline": 80.0,
                "bundle_severity": 12.0,
                "bundle_resolve": 16.0,
                "bundle_scarce": 6.0,
                "bundle_spread": 4.0,
                "bundle_slack": 0.8,
                "bundle_future_cost": 2.0,
                "bundle_unresolved": 4.0,
                "bundle_disruption": 5.0,
                "bundle_lookahead": 0.35,
                "bundle_contingency": 0.35,
                "bundle_dynamic_alert": 6.0,
            },
            "quantity": {
                "candidate_pwrs": 980.0,
                "candidate_cap": 265.0,
                "candidate_resolution": 70.0,
                "candidate_deadline": 65.0,
                "candidate_slack": 1.1,
                "candidate_scarcity": 14.0,
                "candidate_future_cost": 2.2,
                "candidate_disruption": 6.0,
                "candidate_lookahead": 0.35,
                "candidate_contingency": 0.35,
                "bundle_pwrs": 1060.0,
                "bundle_cap": 290.0,
                "bundle_resolution": 85.0,
                "bundle_deadline": 90.0,
                "bundle_severity": 10.0,
                "bundle_resolve": 16.0,
                "bundle_scarce": 6.0,
                "bundle_spread": 3.0,
                "bundle_slack": 0.7,
                "bundle_future_cost": 2.0,
                "bundle_unresolved": 4.5,
                "bundle_disruption": 5.0,
                "bundle_lookahead": 0.40,
                "bundle_contingency": 0.40,
                "bundle_dynamic_alert": 6.0,
            },
            "dynamic": {
                "candidate_pwrs": 980.0,
                "candidate_cap": 250.0,
                "candidate_resolution": 60.0,
                "candidate_deadline": 65.0,
                "candidate_slack": 1.1,
                "candidate_scarcity": 12.0,
                "candidate_future_cost": 2.0,
                "candidate_disruption": 7.5,
                "candidate_lookahead": 0.45,
                "candidate_contingency": 0.50,
                "bundle_pwrs": 1080.0,
                "bundle_cap": 260.0,
                "bundle_resolution": 80.0,
                "bundle_deadline": 85.0,
                "bundle_severity": 11.0,
                "bundle_resolve": 16.0,
                "bundle_scarce": 6.0,
                "bundle_spread": 5.0,
                "bundle_slack": 0.8,
                "bundle_future_cost": 2.0,
                "bundle_unresolved": 4.5,
                "bundle_disruption": 6.5,
                "bundle_lookahead": 0.55,
                "bundle_contingency": 0.65,
                "bundle_dynamic_alert": 7.0,
            },
            "contention": {
                "candidate_pwrs": 1000.0,
                "candidate_cap": 255.0,
                "candidate_resolution": 65.0,
                "candidate_deadline": 70.0,
                "candidate_slack": 1.2,
                "candidate_scarcity": 16.0,
                "candidate_future_cost": 2.6,
                "candidate_disruption": 6.0,
                "candidate_lookahead": 0.40,
                "candidate_contingency": 0.35,
                "bundle_pwrs": 1110.0,
                "bundle_cap": 270.0,
                "bundle_resolution": 82.0,
                "bundle_deadline": 88.0,
                "bundle_severity": 12.0,
                "bundle_resolve": 16.0,
                "bundle_scarce": 8.0,
                "bundle_spread": 5.5,
                "bundle_slack": 0.9,
                "bundle_future_cost": 2.4,
                "bundle_unresolved": 5.0,
                "bundle_disruption": 5.0,
                "bundle_lookahead": 0.45,
                "bundle_contingency": 0.40,
                "bundle_dynamic_alert": 6.0,
            },
        }
        self.score_weights = weights_by_mode[self.planner_mode]

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
        Generate same-time dispatch bundles, project their downstream effect,
        and execute the best available plan.
        """
        self._refresh_search_profile()
        atomic_candidates = self._generate_dispatch_candidates()
        if not atomic_candidates:
            self._remember(
                "blocked",
                "No feasible dispatch candidates remain under current world constraints.",
            )
            return False

        bundles = self._generate_dispatch_bundles(atomic_candidates)
        if not bundles:
            self._remember(
                "blocked",
                "No feasible dispatch bundles remain under current world constraints.",
            )
            return False

        selected_bundle = self._select_bundle(bundles)
        executed_results = self._execute_bundle(selected_bundle, bundles)
        if not executed_results:
            return False

        self._record_bundle_execution(selected_bundle, executed_results, bundles)
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
        route_strategy: str = "fastest",
    ) -> tuple[float, float, float, float]:
        arrival_trip, total_trip = self.world.mission_time_estimate(
            vehicle,
            incident,
            hospital_node,
            route_strategy,
        )
        arrival_time = self.world.current_time + arrival_trip
        completion_time = self.world.current_time + total_trip
        return arrival_trip, total_trip, arrival_time, completion_time

    def _refresh_search_profile(self) -> None:
        open_incident_items = list(self.world.open_incidents().items())
        open_incidents = [incident for _, incident in open_incident_items]
        available_vehicles = list(self.world.available_vehicles().values())
        pending_triggers = sum(1 for trigger in self.world.dynamic_triggers if not trigger.get("fired"))
        quantity_incidents = sum(1 for incident in open_incidents if self.world.required_quantity(incident) > 0)
        high_contention = sum(
            1 for incident_id, _ in open_incident_items if self._provider_count_for_incident(incident_id) <= 1
        )

        if pending_triggers:
            self.planner_mode = "dynamic"
        elif quantity_incidents:
            self.planner_mode = "quantity"
        elif len(open_incidents) >= 3 or high_contention >= 1:
            self.planner_mode = "contention"
        else:
            self.planner_mode = "static"
        self._set_score_weights()

        self.max_candidate_pool = 16 if len(open_incidents) >= 3 else 12
        self.max_prompt_candidates = 6 if pending_triggers or len(open_incidents) >= 3 else 5
        self.rollout_depth = 7 if pending_triggers else 6 if len(open_incidents) >= 3 else 5
        self.max_bundle_size = 3 if len(available_vehicles) >= 3 and (len(open_incidents) >= 2 or quantity_incidents) else 2
        self.max_bundle_pool = 14 if self.max_bundle_size >= 3 else 10
        self.lookahead_event_budget = 3 if pending_triggers else 2
        self.lookahead_beam_width = 4 if pending_triggers or len(open_incidents) >= 3 else 3

    def _incident_urgency_value(
        self,
        incident: dict,
        completion_slack: float | None = None,
    ) -> float:
        return self._incident_urgency_value_for_world(self.world, incident, completion_slack)

    def _incident_urgency_value_for_world(
        self,
        world: WorldState,
        incident: dict,
        completion_slack: float | None = None,
    ) -> float:
        required = max(1, len(incident.get("required_capabilities", [])))
        uncovered = len(world.incident_effective_uncovered_capabilities(incident))
        remaining_work = uncovered / required

        required_quantity = world.required_quantity(incident)
        if required_quantity > 0:
            remaining_ratio = world.remaining_quantity(incident) / max(1, required_quantity)
            remaining_work = max(remaining_work, remaining_ratio)

        slack = (
            completion_slack
            if completion_slack is not None
            else incident["deadline_minutes"] - world.current_time
        )
        if slack <= 0:
            deadline_pressure = 3.0 + min(abs(slack), 30.0) / 10.0
        else:
            deadline_pressure = 1.0 + (1.0 / max(1.0, slack))
        return incident["severity"] * deadline_pressure * max(0.25, remaining_work)

    def _candidate_route_strategies(self, incident: dict) -> list[str]:
        strategies = ["fastest"]
        pending_triggers = any(not trigger.get("fired") for trigger in self.world.dynamic_triggers)
        if pending_triggers or self.planner_mode == "dynamic":
            strategies.append("robust")
        return strategies

    def _candidate_hospital_options(
        self,
        vehicle: dict,
        incident: dict,
        route_strategy: str,
    ) -> list[str | None]:
        quantity_capability = self.world.quantity_capability(incident)
        if quantity_capability != "patient_transport":
            return [None]
        if "patient_transport" not in set(vehicle.get("capabilities", [])):
            return [None]
        options = self.world.choose_hospital_options(
            incident["location"],
            vehicle,
            preferred_node=vehicle.get("home_depot"),
            required_load=self.world.vehicle_quantity_capacity(vehicle, incident),
            route_strategy=route_strategy,
            limit=2,
        )
        return [node_id for node_id, _ in options] or [None]

    def _vehicle_can_help_incident(
        self,
        vehicle_id: str,
        incident_id: str,
    ) -> bool:
        vehicle = self.world.vehicles.get(vehicle_id)
        incident = self.world.incidents.get(incident_id)
        if not vehicle or not incident or not vehicle.get("available") or incident.get("resolved"):
            return False

        for route_strategy in self._candidate_route_strategies(incident):
            for hospital_node in self._candidate_hospital_options(vehicle, incident, route_strategy):
                contribution, reserved_quantity = self.world.mission_contribution(vehicle, incident, hospital_node)
                if not contribution and reserved_quantity <= 0:
                    continue
                valid, _ = self.validator.validate_dispatch(
                    vehicle_id,
                    incident_id,
                    hospital_node,
                    route_strategy=route_strategy,
                    count_violation=False,
                )
                if valid:
                    return True
        return False

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

            valid_here = False
            for route_strategy in self._candidate_route_strategies(incident):
                for hospital_node in self._candidate_hospital_options(vehicle, incident, route_strategy):
                    contribution, reserved_quantity = self.world.mission_contribution(vehicle, incident, hospital_node)
                    if not contribution and reserved_quantity <= 0:
                        continue
                    valid, _ = self.validator.validate_dispatch(
                        vehicle_id,
                        incident_id,
                        hospital_node,
                        route_strategy=route_strategy,
                        count_violation=False,
                    )
                    if valid:
                        valid_here = True
                        break
                if valid_here:
                    break
            if not valid_here:
                continue

            alternatives = 0
            for other_vehicle_id, other_vehicle in self.world.vehicles.items():
                if other_vehicle_id == vehicle_id or not other_vehicle.get("available"):
                    continue
                for other_route_strategy in self._candidate_route_strategies(incident):
                    found_other = False
                    for other_hospital in self._candidate_hospital_options(other_vehicle, incident, other_route_strategy):
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
                            route_strategy=other_route_strategy,
                            count_violation=False,
                        )
                        if other_valid:
                            alternatives += 1
                            found_other = True
                            break
                    if found_other:
                        break

            urgency = self._incident_urgency_value(incident)
            if alternatives == 0:
                cost += urgency
            elif alternatives == 1:
                cost += urgency * 0.35
        return cost

    def _candidate_disruption_risk(
        self,
        vehicle: dict,
        incident: dict,
        hospital_node: str | None,
        completion_time: float,
        route_strategy: str = "fastest",
    ) -> float:
        return self._candidate_disruption_risk_for_world(
            self.world,
            vehicle,
            incident,
            hospital_node,
            completion_time,
            route_strategy,
        )

    def _candidate_disruption_risk_for_world(
        self,
        world: WorldState,
        vehicle: dict,
        incident: dict,
        hospital_node: str | None,
        completion_time: float,
        route_strategy: str = "fastest",
    ) -> float:
        pending_triggers = [trigger for trigger in world.dynamic_triggers if not trigger.get("fired")]
        if not pending_triggers:
            return 0.0

        vehicle_type = vehicle.get("type")
        speed_multiplier = world.vehicle_speed_multiplier(vehicle)
        _, _, _, edge_ids = world.shortest_path_details(
            vehicle["location"],
            incident["location"],
            vehicle_type,
            speed_multiplier,
            route_strategy,
        )
        if hospital_node:
            _, _, _, hospital_edge_ids = world.shortest_path_details(
                incident["location"],
                hospital_node,
                vehicle_type,
                speed_multiplier,
                route_strategy,
            )
            edge_ids = edge_ids + hospital_edge_ids

        if not edge_ids:
            return 0.0

        risk = 0.0
        edge_set = set(edge_ids)
        for trigger in pending_triggers:
            target_edge = trigger.get("target_edge")
            if not target_edge or target_edge not in edge_set:
                continue
            trigger_time = float(trigger.get("trigger_time", world.current_time))
            if trigger_time <= completion_time:
                risk += 2.5
            else:
                time_gap = trigger_time - world.current_time
                risk += 1.0 / max(1.0, time_gap)
        return risk

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
                float,
                str,
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
                provider_count = self._provider_count_for_incident(incident_id)
                scarcity_bonus = 1.0 / max(1, provider_count)
                future_option_cost = self._vehicle_future_option_cost(vehicle_id, incident_id)
                for route_strategy in self._candidate_route_strategies(incident):
                    for hospital_node in self._candidate_hospital_options(vehicle, incident, route_strategy):
                        contribution, reserved_quantity = self.world.mission_contribution(
                            vehicle,
                            incident,
                            hospital_node,
                        )
                        if not contribution:
                            continue

                        valid, _ = self.validator.validate_dispatch(
                            vehicle_id,
                            incident_id,
                            hospital_node,
                            route_strategy=route_strategy,
                            count_violation=False,
                        )
                        if not valid:
                            continue

                        travel_time, total_trip_time, arrival_time, completion_time = self._estimate_mission_times(
                            vehicle,
                            incident,
                            hospital_node,
                            route_strategy,
                        )
                        if math.isinf(travel_time) or math.isinf(total_trip_time):
                            continue
                        deadline_slack = incident["deadline_minutes"] - arrival_time
                        completion_slack = incident["deadline_minutes"] - completion_time
                        disruption_risk = self._candidate_disruption_risk(
                            vehicle,
                            incident,
                            hospital_node,
                            completion_time,
                            route_strategy,
                        )
                        pre_score = self._candidate_pre_score(
                            incident,
                            uncovered,
                            contribution,
                            reserved_quantity,
                            quantity_remaining,
                            completion_slack,
                            scarcity_bonus,
                            future_option_cost,
                            disruption_risk,
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
                                disruption_risk,
                                route_strategy,
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
            disruption_risk,
            route_strategy,
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
                route_strategy=route_strategy,
                reserved_quantity=reserved_quantity,
                quantity_capability=quantity_capability,
                quantity_remaining_before=quantity_remaining,
                provider_count=provider_count,
                scarcity_bonus=1.0 / max(1, provider_count),
                future_option_cost=future_option_cost,
                disruption_risk=disruption_risk,
            )
            self._project_candidate(candidate)
            candidates.append(candidate)

        candidates.sort(key=lambda candidate: candidate.heuristic_score, reverse=True)
        for idx, candidate in enumerate(candidates, start=1):
            candidate.candidate_id = f"C{idx}"
        return candidates[: self.max_prompt_candidates]

    def _generate_dispatch_bundles(self, candidates: list[DispatchCandidate]) -> list[DispatchBundle]:
        if not candidates:
            return []

        bundles: list[DispatchBundle] = []
        seen_keys: set[tuple[tuple[str, str, str | None], ...]] = set()

        def add_bundle(actions: list[DispatchCandidate]) -> None:
            ordered = sorted(actions, key=self._bundle_priority_key)
            key = tuple(
                sorted(
                    (action.vehicle_id, action.incident_id, action.hospital_node, action.route_strategy)
                    for action in ordered
                )
            )
            if key in seen_keys:
                return
            seen_keys.add(key)
            bundles.append(DispatchBundle(bundle_id=f"B{len(bundles) + 1}", actions=ordered))

        for candidate in candidates:
            add_bundle([candidate])

        pair_candidates = candidates[: min(len(candidates), self.max_candidate_pool)]
        for idx, first in enumerate(pair_candidates):
            for second in pair_candidates[idx + 1 :]:
                if first.vehicle_id == second.vehicle_id:
                    continue
                add_bundle([first, second])

        if self.max_bundle_size >= 3:
            triple_candidates = pair_candidates[: min(len(pair_candidates), 8)]
            for idx, first in enumerate(triple_candidates):
                for jdx, second in enumerate(triple_candidates[idx + 1 :], start=idx + 1):
                    if first.vehicle_id == second.vehicle_id:
                        continue
                    for third in triple_candidates[jdx + 1 :]:
                        if len({first.vehicle_id, second.vehicle_id, third.vehicle_id}) < 3:
                            continue
                        add_bundle([first, second, third])

        for bundle in bundles:
            self._project_bundle(bundle)

        bundles = [bundle for bundle in bundles if math.isfinite(bundle.heuristic_score)]
        bundles.sort(key=lambda bundle: bundle.heuristic_score, reverse=True)
        shortlisted = bundles[: self.max_bundle_pool]
        for idx, bundle in enumerate(shortlisted, start=1):
            bundle.bundle_id = f"B{idx}"
        return shortlisted

    def _bundle_priority_key(self, candidate: DispatchCandidate) -> tuple[float, float, float]:
        return (candidate.completion_slack, -candidate.severity, -candidate.heuristic_score)

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
        disruption_risk: float,
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
        disruption_penalty = disruption_risk * max(2.0, urgency * 0.25)
        return (
            on_time_resolution * 100.0
            + partial_value * 22.0
            + resolve_bonus
            + slack_bonus
            + scarcity_value
            - preservation_penalty
            - disruption_penalty
        )

    def _project_candidate(self, candidate: DispatchCandidate) -> None:
        sim_world = self.world.clone()
        sim_tool = WorldTool(sim_world)
        sim_validator = ValidatorTool(sim_world)

        valid, err_msg = sim_validator.validate_dispatch(
            candidate.vehicle_id,
            candidate.incident_id,
            candidate.hospital_node,
            route_strategy=candidate.route_strategy,
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
            route_strategy=candidate.route_strategy,
        )
        candidate.immediate_resolved = result.get("incident_resolved", False)
        candidate.dynamic_alerts = list(result.get("dynamic_alerts", []))

        lookahead_world = sim_world.clone()
        immediate_value = self._state_value(lookahead_world)
        lookahead_value = self._multi_event_lookahead_value(
            lookahead_world,
            decision_budget=max(0, self.rollout_depth - 1),
            event_budget=self.lookahead_event_budget,
            beam_width=self.lookahead_beam_width,
        )
        candidate.lookahead_gain = max(0.0, lookahead_value - immediate_value)
        candidate.contingency_penalty = self._contingency_penalty(lookahead_world)

        self._rollout_projection(sim_world, max_steps=max(0, self.rollout_depth - 1))
        projected = self._state_objectives(sim_world)
        candidate.projected_pwrs = projected["pwrs"]
        candidate.projected_cap_pwrs = projected["cap_pwrs"]
        candidate.projected_resolution_rate = projected["resolution_rate"]
        candidate.projected_deadline_adherence = projected["deadline_adherence"]
        candidate.heuristic_score = self._combine_candidate_score(candidate)
        candidate.rationale = self._candidate_rationale(candidate)

    def _project_bundle(self, bundle: DispatchBundle) -> None:
        sim_world = self.world.clone()
        sim_tool = WorldTool(sim_world)
        sim_validator = ValidatorTool(sim_world)
        results: list[dict] = []

        for action in bundle.actions:
            valid, err_msg = sim_validator.validate_dispatch(
                action.vehicle_id,
                action.incident_id,
                action.hospital_node,
                route_strategy=action.route_strategy,
                count_violation=False,
            )
            if not valid:
                bundle.heuristic_score = float("-inf")
                bundle.rationale = [err_msg]
                return
            result = sim_tool.dispatch_vehicle(
                vehicle_id=action.vehicle_id,
                incident_id=action.incident_id,
                hospital_node=action.hospital_node,
                route_strategy=action.route_strategy,
            )
            if not result.get("success", False):
                bundle.heuristic_score = float("-inf")
                bundle.rationale = [result.get("error", "Bundle dispatch failed.")]
                return
            results.append(result)

        lookahead_world = sim_world.clone()
        immediate_value = self._state_value(lookahead_world)
        lookahead_value = self._multi_event_lookahead_value(
            lookahead_world,
            decision_budget=max(0, self.rollout_depth - len(bundle.actions)),
            event_budget=self.lookahead_event_budget,
            beam_width=self.lookahead_beam_width,
        )
        bundle.lookahead_gain = max(0.0, lookahead_value - immediate_value)
        bundle.contingency_penalty = self._contingency_penalty(lookahead_world)

        self._rollout_projection(sim_world, max_steps=max(0, self.rollout_depth - len(bundle.actions)))
        projected = self._state_objectives(sim_world)
        bundle.projected_pwrs = projected["pwrs"]
        bundle.projected_cap_pwrs = projected["cap_pwrs"]
        bundle.projected_resolution_rate = projected["resolution_rate"]
        bundle.projected_deadline_adherence = projected["deadline_adherence"]
        bundle.dynamic_alerts = [
            alert for result in results for alert in result.get("dynamic_alerts", [])
        ]
        bundle.immediate_resolved_count = sum(
            1 for result in results if result.get("incident_resolved", False)
        )
        bundle.scarce_vehicle_count = sum(
            1 for action in bundle.actions if action.provider_count <= 1
        )
        bundle.future_option_cost = sum(action.future_option_cost for action in bundle.actions)
        bundle.disruption_risk = sum(action.disruption_risk for action in bundle.actions)
        bundle.total_completion_slack = sum(action.completion_slack for action in bundle.actions)
        incident_counts = Counter(action.incident_id for action in bundle.actions)
        bundle.concentration_penalty = sum(max(0, count - 1) for count in incident_counts.values()) * 4.0
        bundle.incident_spread = len(incident_counts)
        bundle.on_time_severity_sum = sum(
            action.severity for action in bundle.actions if action.completion_slack >= 0
        )
        bundle.unresolved_risk = self._unresolved_incident_risk(sim_world)
        bundle.heuristic_score = self._combine_bundle_score(bundle)
        bundle.rationale = self._bundle_rationale(bundle)

    def _unresolved_incident_risk(self, world: WorldState) -> float:
        return self._unresolved_incident_risk_for_world(world)

    def _unresolved_incident_risk_for_world(self, world: WorldState) -> float:
        risk = 0.0
        for incident in world.open_incidents().values():
            provider_count = 0
            for vehicle in world.available_vehicles().values():
                quantity_capability = world.quantity_capability(incident)
                hospital_node = None
                if quantity_capability == "patient_transport" and "patient_transport" in set(vehicle["capabilities"]):
                    hospital_node = world.choose_hospital(
                        incident["location"],
                        vehicle,
                        vehicle.get("home_depot"),
                        world.vehicle_quantity_capacity(vehicle, incident),
                    )
                contribution, reserved_quantity = world.mission_contribution(vehicle, incident, hospital_node)
                if contribution or reserved_quantity > 0:
                    provider_count += 1
            scarcity = 1.0 / max(1, provider_count)
            urgency = self._incident_urgency_value_for_world(world, incident)
            risk += urgency * scarcity
        return risk

    def _state_value(self, world: WorldState) -> float:
        objectives = self._state_objectives(world)
        unresolved_risk = self._unresolved_incident_risk_for_world(world)
        return (
            objectives["pwrs"] * 1100.0
            + objectives["cap_pwrs"] * 260.0
            + objectives["resolution_rate"] * 80.0
            + objectives["deadline_adherence"] * 80.0
            - unresolved_risk * 5.0
        )

    def _contingency_penalty(self, world: WorldState) -> float:
        event_world = world.clone()
        advanced = WorldTool(event_world).advance_to_next_event()
        if not advanced.get("advanced"):
            return 0.0
        current_value = self._state_value(world)
        event_value = self._state_value(event_world)
        alert_penalty = 2.0 * len(advanced.get("dynamic_alerts", []))
        return max(0.0, current_value - event_value) + alert_penalty

    def _enumerate_rollout_actions(
        self,
        sim_world: WorldState,
        sim_validator: ValidatorTool,
        limit: int,
    ) -> list[tuple[float, str, str, str | None]]:
        ranked_actions: list[tuple[float, str, str, str | None]] = []
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
                disruption_risk = self._candidate_disruption_risk_for_world(
                    sim_world,
                    vehicle,
                    incident,
                    hospital_node,
                    completion_time,
                )
                score = self._candidate_pre_score(
                    incident,
                    uncovered,
                    contribution,
                    reserved_quantity,
                    quantity_remaining,
                    completion_slack,
                    1.0 / max(1, provider_count),
                    0.0,
                    disruption_risk,
                )
                ranked_actions.append((score, vehicle_id, incident_id, hospital_node))
        ranked_actions.sort(key=lambda item: item[0], reverse=True)
        return ranked_actions[:limit]

    def _enumerate_rollout_bundles(
        self,
        sim_world: WorldState,
        sim_validator: ValidatorTool,
        beam_width: int,
    ) -> list[list[tuple[str, str, str | None]]]:
        actions = self._enumerate_rollout_actions(
            sim_world,
            sim_validator,
            limit=max(beam_width + 2, self.max_bundle_size + 1),
        )
        bundles: list[list[tuple[str, str, str | None]]] = []
        seen: set[tuple[tuple[str, str, str | None], ...]] = set()

        def add_bundle(bundle_actions: list[tuple[str, str, str | None]]) -> None:
            key = tuple(sorted(bundle_actions))
            if key in seen:
                return
            seen.add(key)
            bundles.append(bundle_actions)

        action_tuples = [(vehicle_id, incident_id, hospital_node) for _, vehicle_id, incident_id, hospital_node in actions]
        for action in action_tuples:
            add_bundle([action])
        for idx, first in enumerate(action_tuples):
            for second in action_tuples[idx + 1 :]:
                if first[0] == second[0]:
                    continue
                add_bundle([first, second])
        if self.max_bundle_size >= 3:
            limited = action_tuples[: min(len(action_tuples), beam_width + 1)]
            for idx, first in enumerate(limited):
                for jdx, second in enumerate(limited[idx + 1 :], start=idx + 1):
                    if first[0] == second[0]:
                        continue
                    for third in limited[jdx + 1 :]:
                        if len({first[0], second[0], third[0]}) < 3:
                            continue
                        add_bundle([first, second, third])
        return bundles[:beam_width]

    def _apply_rollout_bundle(
        self,
        sim_world: WorldState,
        bundle_actions: list[tuple[str, str, str | None]],
    ) -> bool:
        sim_tool = WorldTool(sim_world)
        sim_validator = ValidatorTool(sim_world)
        for vehicle_id, incident_id, hospital_node in bundle_actions:
            valid, _ = sim_validator.validate_dispatch(
                vehicle_id,
                incident_id,
                hospital_node,
                count_violation=False,
            )
            if not valid:
                return False
            result = sim_tool.dispatch_vehicle(
                vehicle_id=vehicle_id,
                incident_id=incident_id,
                hospital_node=hospital_node,
            )
            if not result.get("success", False):
                return False
        return True

    def _multi_event_lookahead_value(
        self,
        sim_world: WorldState,
        decision_budget: int,
        event_budget: int,
        beam_width: int,
    ) -> float:
        base_value = self._state_value(sim_world)
        if decision_budget <= 0 and event_budget <= 0:
            return base_value

        best_value = base_value
        sim_validator = ValidatorTool(sim_world)

        if decision_budget > 0:
            bundles = self._enumerate_rollout_bundles(sim_world, sim_validator, beam_width)
            for bundle_actions in bundles:
                branch_world = sim_world.clone()
                if not self._apply_rollout_bundle(branch_world, bundle_actions):
                    continue
                branch_value = self._multi_event_lookahead_value(
                    branch_world,
                    decision_budget=decision_budget - 1,
                    event_budget=event_budget,
                    beam_width=max(1, beam_width - 1),
                )
                best_value = max(best_value, base_value * 0.2 + self.lookahead_discount * branch_value)

        if event_budget > 0:
            event_world = sim_world.clone()
            advanced = WorldTool(event_world).advance_to_next_event()
            if advanced.get("advanced"):
                event_penalty = 2.0 * len(advanced.get("dynamic_alerts", []))
                branch_value = self._multi_event_lookahead_value(
                    event_world,
                    decision_budget=decision_budget,
                    event_budget=event_budget - 1,
                    beam_width=beam_width,
                )
                best_value = max(
                    best_value,
                    base_value * 0.2 + self.lookahead_discount * branch_value - event_penalty,
                )

        return best_value

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
        actions = self._enumerate_rollout_actions(sim_world, sim_validator, limit=1)
        if not actions:
            return None
        _, vehicle_id, incident_id, hospital_node = actions[0]
        return (vehicle_id, incident_id, hospital_node)

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
        w = self.score_weights
        score = 0.0
        score += candidate.projected_pwrs * w["candidate_pwrs"]
        score += candidate.projected_cap_pwrs * w["candidate_cap"]
        score += candidate.projected_resolution_rate * w["candidate_resolution"]
        score += candidate.projected_deadline_adherence * w["candidate_deadline"]
        score += max(min(candidate.completion_slack, 20.0), -20.0) * w["candidate_slack"]
        score += candidate.scarcity_bonus * w["candidate_scarcity"]
        score -= candidate.future_option_cost * w["candidate_future_cost"]
        score -= candidate.disruption_risk * w["candidate_disruption"]
        score += candidate.lookahead_gain * w["candidate_lookahead"]
        score -= candidate.contingency_penalty * w["candidate_contingency"]
        if candidate.immediate_resolved and candidate.completion_slack >= 0:
            score += 15.0
        if candidate.dynamic_alerts:
            score -= 8.0 * len(candidate.dynamic_alerts)
        return score

    def _combine_bundle_score(self, bundle: DispatchBundle) -> float:
        w = self.score_weights
        score = 0.0
        score += bundle.projected_pwrs * w["bundle_pwrs"]
        score += bundle.projected_cap_pwrs * w["bundle_cap"]
        score += bundle.projected_resolution_rate * w["bundle_resolution"]
        score += bundle.projected_deadline_adherence * w["bundle_deadline"]
        score += bundle.on_time_severity_sum * w["bundle_severity"]
        score += bundle.immediate_resolved_count * w["bundle_resolve"]
        score += bundle.scarce_vehicle_count * w["bundle_scarce"]
        score += bundle.incident_spread * w["bundle_spread"]
        score += max(min(bundle.total_completion_slack, 30.0), -30.0) * w["bundle_slack"]
        score -= bundle.future_option_cost * w["bundle_future_cost"]
        score -= bundle.unresolved_risk * w["bundle_unresolved"]
        score -= bundle.disruption_risk * w["bundle_disruption"]
        score += bundle.lookahead_gain * w["bundle_lookahead"]
        score -= bundle.contingency_penalty * w["bundle_contingency"]
        score -= bundle.concentration_penalty
        if bundle.dynamic_alerts:
            score -= w["bundle_dynamic_alert"] * len(bundle.dynamic_alerts)
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
        if candidate.disruption_risk > 0:
            reasons.append(f"route disruption risk {candidate.disruption_risk:.2f}")
        if candidate.lookahead_gain > 0:
            reasons.append(f"future lookahead gain {candidate.lookahead_gain:.2f}")
        if candidate.contingency_penalty > 0:
            reasons.append(f"next-event fragility {candidate.contingency_penalty:.2f}")
        if candidate.dynamic_alerts:
            reasons.append("may trigger dynamic alert handling")
        return reasons

    def _bundle_rationale(self, bundle: DispatchBundle) -> list[str]:
        reasons = [
            f"projects PWRS {bundle.projected_pwrs:.3f}",
            f"projects Cap-PWRS {bundle.projected_cap_pwrs:.3f}",
            f"on-time severity covered now {bundle.on_time_severity_sum:.1f}",
        ]
        if bundle.immediate_resolved_count:
            reasons.append(f"immediately resolves {bundle.immediate_resolved_count} incident(s)")
        if bundle.scarce_vehicle_count:
            reasons.append(f"uses {bundle.scarce_vehicle_count} scarce vehicle(s)")
        if bundle.future_option_cost > 0:
            reasons.append(f"consumes future option value {bundle.future_option_cost:.2f}")
        if bundle.unresolved_risk > 0:
            reasons.append(f"leaves unresolved urgency risk {bundle.unresolved_risk:.2f}")
        if bundle.disruption_risk > 0:
            reasons.append(f"bundle disruption risk {bundle.disruption_risk:.2f}")
        if bundle.lookahead_gain > 0:
            reasons.append(f"future lookahead gain {bundle.lookahead_gain:.2f}")
        if bundle.contingency_penalty > 0:
            reasons.append(f"next-event fragility {bundle.contingency_penalty:.2f}")
        if bundle.incident_spread > 1:
            reasons.append(f"covers {bundle.incident_spread} incidents in parallel")
        if bundle.concentration_penalty > 0:
            reasons.append("concentrates multiple units on one incident")
        if bundle.dynamic_alerts:
            reasons.append("may trigger dynamic alert handling")
        return reasons

    def _select_bundle(self, bundles: list[DispatchBundle]) -> DispatchBundle:
        if not self._can_use_llm_for_planning() or len(bundles) == 1:
            return bundles[0]
        if not self._should_consult_llm_for_bundles(bundles):
            return bundles[0]
        selected = self._llm_critique_bundle_choice(bundles)
        if selected is None:
            return bundles[0]
        if not self._llm_bundle_selection_is_safe(selected, bundles[0]):
            self._remember(
                "llm_selection_rejected",
                f"Rejected LLM bundle {selected.bundle_id} in favor of heuristic {bundles[0].bundle_id}.",
            )
            return bundles[0]
        return selected

    def _can_use_llm_for_planning(self) -> bool:
        return bool(self.use_llm_for_planning and self.api_key)

    def _should_consult_llm_for_bundles(self, bundles: list[DispatchBundle]) -> bool:
        if len(bundles) < 2:
            return False
        top = bundles[0]
        runner_up = bundles[1]
        score_gap = top.heuristic_score - runner_up.heuristic_score
        relative_gap = score_gap / max(1.0, abs(top.heuristic_score))
        close_projected_pwrs = abs(top.projected_pwrs - runner_up.projected_pwrs) <= 0.03
        close_projected_cap = abs(top.projected_cap_pwrs - runner_up.projected_cap_pwrs) <= 0.05
        close_deadline = abs(top.projected_deadline_adherence - runner_up.projected_deadline_adherence) <= 0.05
        dynamic_context = bool(self.world.event_log)

        if relative_gap <= 0.04:
            return True
        if close_projected_pwrs and close_projected_cap and close_deadline:
            return True
        if dynamic_context and relative_gap <= 0.08:
            return True
        return False

    def _llm_bundle_selection_is_safe(
        self,
        selected: DispatchBundle,
        heuristic_top: DispatchBundle,
    ) -> bool:
        if selected.bundle_id == heuristic_top.bundle_id:
            return True
        if selected.projected_pwrs + 0.05 < heuristic_top.projected_pwrs:
            return False
        if selected.projected_cap_pwrs + 0.05 < heuristic_top.projected_cap_pwrs:
            return False
        if selected.projected_deadline_adherence + 0.05 < heuristic_top.projected_deadline_adherence:
            return False
        if selected.on_time_severity_sum + 2.0 < heuristic_top.on_time_severity_sum:
            return False
        return True

    def _llm_critique_bundle_choice(self, bundles: list[DispatchBundle]) -> DispatchBundle | None:
        prompt = self._build_bundle_critic_prompt(bundles)
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

            chosen_id, risk_tag, reason = self._parse_bundle_critic_choice(raw)
            if chosen_id is None:
                self._remember("selection_parse_failure", raw[:300])
                return None

            for bundle in bundles:
                if bundle.bundle_id == chosen_id:
                    print(
                        f"  [AgentKit] LLM critique preferred {chosen_id}: "
                        f"{', '.join(f'{action.vehicle_id}->{action.incident_id}' for action in bundle.actions)}"
                    )
                    self.selection_history.append(
                        {
                            "time": self.world.current_time,
                            "bundle_id": chosen_id,
                            "risk_tag": risk_tag,
                            "reason": reason,
                            "heuristic_score": bundle.heuristic_score,
                        }
                    )
                    if reason:
                        self._remember("llm_selection", reason)
                    return bundle
        except Exception as exc:
            self._remember("llm_selection_error", str(exc))
            print(f"  [AgentKit] LLM bundle critique failed; using heuristic fallback: {exc}")
        return None

    def _build_bundle_critic_prompt(self, bundles: list[DispatchBundle]) -> str:
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
            "You are critiquing the heuristic top emergency dispatch bundle against the runner-up. "
            "Do not invent a new action. Choose either the top bundle or the runner-up bundle.\n\n"
            f"Current simulation time: {self.world.current_time:.1f}\n"
            f"Planner mode: {self.planner_mode}\n"
            f"Active alerts: {self.world.event_log[-2:] if self.world.event_log else []}\n"
            f"Open incidents: {json.dumps(open_incidents[:5], indent=2)}\n"
            f"Recent lessons: {json.dumps(recent_lessons, indent=2)}\n\n"
            f"Top bundle: {bundles[0].brief()}\n"
            f"Runner-up bundle: {bundles[1].brief() if len(bundles) > 1 else bundles[0].brief()}\n\n"
            "You may only choose between these two bundle IDs.\n"
        )
        prompt += (
            "\nRisk tags:\n"
            '- "none": the heuristic top bundle should stand.\n'
            '- "fragility": the top bundle is too vulnerable to disruption or next-event degradation.\n'
            '- "option_loss": the top bundle wastes scarce future flexibility.\n'
            '- "concentration": the top bundle over-commits to one incident while another urgent one is left exposed.\n'
            '- "deadline": the runner-up is materially safer on deadlines or on-time severity.\n\n'
            "Prefer the runner-up only if the top bundle has a concrete risk of one of those types.\n"
            "Do not switch away from an obvious projected-outcome winner.\n\n"
            'Return ONLY a JSON object like {"bundle_id": "B1", "risk_tag": "none", "reason": "..."}.' 
        )
        return prompt

    def _parse_bundle_critic_choice(self, raw: str) -> tuple[str | None, str, str]:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            bundle_id_match = re.search(r"B\d+", raw)
            return (bundle_id_match.group(0), "none", "") if bundle_id_match else (None, "none", "")

        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            bundle_id_match = re.search(r"B\d+", raw)
            return (bundle_id_match.group(0), "none", "") if bundle_id_match else (None, "none", "")

        candidate_id = payload.get("bundle_id")
        risk_tag = payload.get("risk_tag", "none")
        reason = payload.get("reason", "")
        return candidate_id, risk_tag, reason

    def _execute_bundle(
        self,
        selected_bundle: DispatchBundle,
        bundles: list[DispatchBundle],
    ) -> list[tuple[DispatchCandidate, dict]]:
        results: list[tuple[DispatchCandidate, dict]] = []
        fallback_bundles = [bundle for bundle in bundles if bundle.bundle_id != selected_bundle.bundle_id]
        current_bundle = selected_bundle

        while True:
            bundle_failed = False
            results = []
            for action in current_bundle.actions:
                valid, err_msg = self.validator.validate_dispatch(
                    action.vehicle_id,
                    action.incident_id,
                    action.hospital_node,
                    route_strategy=action.route_strategy,
                )
                if not valid:
                    self._remember("validation_failure", err_msg)
                    print(
                        f"  [AgentKit] Post-selection validator rejection "
                        f"{action.vehicle_id}→{action.incident_id}: {err_msg}"
                    )
                    bundle_failed = True
                    break
                result = self.tool.dispatch_vehicle(
                    vehicle_id=action.vehicle_id,
                    incident_id=action.incident_id,
                    hospital_node=action.hospital_node,
                    route_strategy=action.route_strategy,
                )
                if not result.get("success", False):
                    self._remember("validation_failure", result.get("error", "Dispatch failed."))
                    print(
                        f"  [AgentKit] Dispatch failure "
                        f"{action.vehicle_id}→{action.incident_id}: {result.get('error', 'unknown error')}"
                    )
                    bundle_failed = True
                    break
                self.step_count += 1
                resolved_flag = result.get("incident_resolved", False)
                print(
                    f"  [AgentKit] {action.vehicle_id} → {action.incident_id} | "
                    f"t={result.get('travel_time_minutes', 0):.1f}min | resolved={resolved_flag}"
                )
                results.append((action, result))

            if not bundle_failed:
                return results
            if not fallback_bundles:
                return []
            current_bundle = fallback_bundles.pop(0)

    def _record_bundle_execution(
        self,
        selected: DispatchBundle,
        results: list[tuple[DispatchCandidate, dict]],
        bundles: list[DispatchBundle],
    ) -> None:
        top = bundles[0]
        actions_text = ", ".join(f"{action.vehicle_id}->{action.incident_id}" for action, _ in results)
        summary = (
            f"Selected {selected.bundle_id} ({actions_text}) "
            f"with projected PWRS {selected.projected_pwrs:.3f}; "
            f"executed {len(results)} dispatch(es)."
        )
        self._remember("execution", summary)
        if selected.bundle_id != top.bundle_id:
            self._remember(
                "reflection",
                f"LLM overrode heuristic {top.bundle_id} in favor of {selected.bundle_id}.",
            )
        alert_payload = [result.get("dynamic_alerts", []) for _, result in results if result.get("dynamic_alerts")]
        if alert_payload:
            self._remember(
                "reflection",
                f"Dynamic alert triggered after bundle: {alert_payload}",
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
