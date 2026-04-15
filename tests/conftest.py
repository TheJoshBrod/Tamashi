import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _uid(base: str) -> str:
    """Unique user ID per test run to avoid Jac in-process graph bleed."""
    return f"{base}_{uuid.uuid4().hex[:8]}"
