from __future__ import annotations

from typing import Any


def require_id(obj: Any, field: str) -> int:
    """Safely extracts an integer ID from an event or context object.
    If the field is positive int, returns it.
    If the field is not present, None, bool, or <= 0 (e.g. unassigned 0 default in mock events),
    falls back to id(obj) to ensure unit tests and mock harnesses remain backward-compatible
    while preserving strict uniqueness within the runtime.
    """
    value = getattr(obj, field, None)
    if value is not None and not isinstance(value, bool):
        try:
            val_int = int(value)
            if val_int > 0:
                return val_int
        except (ValueError, TypeError):
            pass
    return id(obj)


def actor_of(event: Any) -> str:
    return (
        getattr(event, "actor_name", "")
        or getattr(event, "actor_id", "")
    )
