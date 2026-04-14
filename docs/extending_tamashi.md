# Extending Tamashi

Tamashi is designed to be modular. You can extend its capabilities by adding new tools or entire subagents.

## 1. Adding a New Tool

Tools are standalone Python functions that the main orchestrator (or a subagent) can call.

### Creating the Tool
1.  Add a new Python file to the `tools/` directory.
2.  Use the `@tool` decorator to register the function.
3.  **Docstrings and Type Hints**: These are critical. They are used to generate the JSON schema that the LLM sees. The full docstring is passed as the tool description.

Example:
```python
# tools/calculator.py
from tools.registry import tool

@tool
def add_numbers(a: int, b: int) -> int:
    """Adds two integers together. Use this for all basic arithmetic."""
    return a + b
```

### Custom UI Feedback
If you want your tool to have a unique "face" on the dashboard while it runs:
1.  Open `display/emotion_manager.py`.
2.  Add your tool name and desired `EmotionState` to `TOOL_REACTIONS`:
    ```python
    TOOL_REACTIONS: dict[str, EmotionState] = {
        "add_numbers": EmotionState.CALCULATING,
        ...
    }
    ```

---

## 2. Adding a New Subagent

Subagents are isolated LLM loops that handle complex, multi-step tasks.

### Steps to Create
1.  **Define the Logic**: Create a file in `subagents/` (e.g., `subagents/research.py`).
2.  **Registration**: Call `define_subagent` with a name and a list of functions/tools.
    ```python
    from subagents.registry import define_subagent
    from tools.web_search import web_search

    def private_subagent_tool():
        """Specialized logic for this subagent."""
        pass

    define_subagent(
        name="researcher",
        tools=[private_subagent_tool, web_search]
    )
    ```

### Sharing Global Tools
Often, you will want your subagent to have access to general-purpose tools like `web_search` or `get_current_time`. Because Tamashi auto-discovers all tools in the `tools/` directory, you can simply import them and include them in the `tools` list during registration.

Example (from `subagents/nutrition.py`):
```python
from tools.web_search import web_search
from tools.time import get_current_time

define_subagent(
    name="nutrition",
    tools=[log_meal_data, query_nutrition_db, web_search, get_current_time]
)
```

3.  **Configuration**: Create `config/subagents/researcher.yaml` to define the system prompt and description.

### Dynamic UI States for Subagents
To give a subagent its own persistent face that "snaps back" after tool calls (see the underlying logic in [Implementation Details](implementation.md)):

1.  **Define the Emotion**: In `core/events.py`, add a new member to the `EmotionState` enum:
    ```python
    RESEARCHER = "researcher"
    ```
2.  **Map the Delegation**: In `display/emotion_manager.py`, update `_on_event` to recognize the subagent's delegation tool:
    ```python
    if name == "delegate_to_researcher_subagent":
        self._base_emotion = EmotionState.RESEARCHER
    ```
3.  **Ensure Reversion**: Add the new state to `WORK_STATES` in `emotion_manager.py` so the hold-timer handles it.
4.  **Frontend Branding**:
    - **Label**: Add the mapping in `display/static/app.js`.
    - **Visuals**: Add a CSS block for `.creature.researcher` in `display/static/styles.css` (e.g., change body color or animation).

---
[← Back to Documentation Hub](README.md)
