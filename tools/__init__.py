from tools.registry import discover

# Auto-import every module in this package so @tool decorators fire at startup.
discover("tools")
