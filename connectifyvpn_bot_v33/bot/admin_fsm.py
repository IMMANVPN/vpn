from __future__ import annotations
from typing import Any, Dict, Optional

_state: Dict[int, Dict[str, Any]] = {}

def set_state(admin_id: int, action: str, payload: Optional[dict]=None):
    _state[int(admin_id)] = {"action": action, "payload": payload or {}}

def get_state(admin_id: int) -> Optional[dict]:
    return _state.get(int(admin_id))

def clear_state(admin_id: int):
    _state.pop(int(admin_id), None)
