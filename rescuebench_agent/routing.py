from __future__ import annotations

from .world import WorldState


def nearest_hospital(
    world: WorldState,
    from_node: str,
    vehicle_type: str | None,
    preferred_node: str | None = None,
    speed_multiplier: float = 1.0,
    required_load: int = 0,
) -> str | None:
    """Return the preferred reachable hospital, or else the nearest open hospital."""
    vehicle_proxy = {
        "type": vehicle_type,
        "speed_multiplier": speed_multiplier,
    }
    return world.choose_hospital(
        from_node=from_node,
        vehicle=vehicle_proxy,
        preferred_node=preferred_node,
        required_load=required_load,
    )
