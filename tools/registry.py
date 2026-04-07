from __future__ import annotations
import importlib
import inspect
import pkgutil
from typing import Any, Callable

from core.schemas import ToolSpec


class _Registry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[Callable, ToolSpec]] = {}

    def register(self, fn: Callable) -> Callable:
        spec = _build_spec(fn)
        self._tools[spec.name] = (fn, spec)
        return fn

    def specs(self) -> list[ToolSpec]:
        return [spec for _, spec in self._tools.values()]

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        if name not in self._tools:
            return f"Error: unknown tool '{name}'"
        fn, _ = self._tools[name]
        try:
            result = fn(**arguments)
            return str(result)
        except Exception as exc:
            return f"Error executing '{name}': {exc}"

    def __len__(self) -> int:
        return len(self._tools)


def _build_spec(fn: Callable) -> ToolSpec:
    """Derive a ToolSpec from a function's type hints and docstring."""
    hints = {}
    sig = inspect.signature(fn)
    required: list[str] = []
    properties: dict[str, Any] = {}

    _type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
    }

    for param_name, param in sig.parameters.items():
        ann = param.annotation
        json_type = _type_map.get(ann, "string")
        properties[param_name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    description = (inspect.getdoc(fn) or fn.__name__).split("\n")[0]
    return ToolSpec(name=fn.__name__, description=description, parameters=schema)


registry = _Registry()


def tool(fn: Callable) -> Callable:
    """Decorator that registers a function as an LLM-callable tool."""
    return registry.register(fn)


def discover(package_name: str = "tools") -> None:
    """
    Import all modules in *package_name* so that @tool decorators fire.
    Called once at startup from tools/__init__.py.
    """
    import importlib
    package = importlib.import_module(package_name)
    for _finder, module_name, _ispkg in pkgutil.walk_packages(
        package.__path__, prefix=f"{package_name}."
    ):
        if module_name.endswith("registry") or module_name.endswith("__init__"):
            continue
        importlib.import_module(module_name)
