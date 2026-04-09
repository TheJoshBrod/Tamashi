from __future__ import annotations

def discover() -> None:
    """
    Import all modules in 'subagents' so that define_subagent calls fire.
    Called once at startup from subagents/__init__.py (or app.py).
    """
    import importlib
    import pkgutil

    package = importlib.import_module("subagents")
    for _finder, module_name, _ispkg in pkgutil.walk_packages(
        package.__path__, prefix="subagents."
    ):
        if module_name.endswith("registry") or module_name.endswith("__init__"):
            continue
        importlib.import_module(module_name)

# Auto-discover when this package is imported by app.py
discover()
