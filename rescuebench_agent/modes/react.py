from __future__ import annotations

import json
from typing import Any, Callable

from ..metrics import compute_metrics
from ..prompts import GEMINI_TOOLS, SYSTEM_PROMPT, TOOL_DEFINITIONS
from ..tools import ValidatorTool, WorldTool
from ..world import WorldState


def _make_dispatch_tool(
    world_tool: WorldTool,
    validator: ValidatorTool,
    use_validator: bool,
) -> Callable[[str, dict], Any]:
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
        if name == "advance_to_next_event":
            return world_tool.advance_to_next_event()
        if name == "report_status":
            return world_tool.report_status()
        return {"error": f"Unknown tool: {name}"}

    return dispatch_tool


def _run_react_gemini(
    scenario_dict: dict,
    api_key: str,
    model: str,
    use_validator: bool,
    max_steps: int,
    max_llm_calls: int,
) -> dict:
    import google.generativeai as genai

    world = WorldState(scenario_dict)
    world_tool = WorldTool(world)
    validator = ValidatorTool(world)
    dispatch_tool = _make_dispatch_tool(world_tool, validator, use_validator)

    genai.configure(api_key=api_key)
    gemini_model = genai.GenerativeModel(
        model_name=model,
        tools=GEMINI_TOOLS,
        system_instruction=SYSTEM_PROMPT,
    )
    chat = gemini_model.start_chat()

    step_count = 0
    llm_calls = 0
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

        function_calls = [part.function_call for part in response.parts if part.function_call and part.function_call.name]
        if not function_calls:
            print(f"  [ReAct/Gemini] Agent finished after {step_count} steps.")
            break

        tool_responses = []
        for function_call in function_calls:
            args = {key: value for key, value in function_call.args.items()} if function_call.args else {}
            result = dispatch_tool(function_call.name, args)
            print(f"  [ReAct/Gemini] {function_call.name} → {str(result)[:80]}")
            tool_responses.append({"function_response": {"name": function_call.name, "response": result}})

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
    """Run the tool-using ReAct loop on a scenario."""
    if provider == "gemini":
        return _run_react_gemini(scenario_dict, api_key, model, use_validator, max_steps, max_llm_calls)

    import anthropic

    world = WorldState(scenario_dict)
    world_tool = WorldTool(world)
    validator = ValidatorTool(world)
    dispatch_tool = _make_dispatch_tool(world_tool, validator, use_validator)
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
        tool_blocks = [block for block in response.content if block.type == "tool_use"]

        if not tool_blocks or response.stop_reason == "end_turn":
            print(f"  [ReAct] Agent finished after {step_count} steps.")
            break

        tool_results: list[dict] = []
        for block in tool_blocks:
            result = dispatch_tool(block.name, block.input or {})
            result_str = json.dumps(result, indent=2)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                }
            )

        messages.append({"role": "user", "content": tool_results})

    return compute_metrics(world, validator, step_count, "react" if use_validator else "ablated")
