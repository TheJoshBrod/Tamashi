import json
from typing import Callable
from litellm import completion
from tools.registry import tool, _build_spec
from core.config import settings
from core.context import session_id_var

import yaml
from pathlib import Path

def define_subagent(name: str, tools: list[Callable]):
    """
    Registers a subagent by generating a delegate tool for the main agent.
    Reads 'description', 'system_prompt', and optional 'model' from config/subagents/{name}.yaml
    When the main agent uses this delegate tool, it spins up an isolated LLM loop
    that only has access to the provided subagent tools and the specific system prompt.
    """
    yaml_path = Path(f"config/subagents/{name}.yaml")
    if not yaml_path.exists():
        raise FileNotFoundError(f"Missing config file {yaml_path}")
        
    with open(yaml_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
        
    description = config.get("description", f"Subagent {name}")
    system_prompt = config.get("system_prompt", "You are a helpful subagent.")
    model = config.get("model", None)

    
    tools_spec = [_build_spec(fn) for fn in tools]
    tools_dict_by_name = {fn.__name__: fn for fn in tools}
    litellm_tools = [spec.to_dict() for spec in tools_spec]

    def _delegate_func(query: str) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
        
        model_to_use = model or settings.model
        executed_tools = []
        iters = 0
        while iters < settings.max_tool_iters:
            # Note: litellm expects 'function' dictionaries for tools
            if litellm_tools:
                response = completion(model=model_to_use, messages=messages, tools=litellm_tools)
            else:
                response = completion(model=model_to_use, messages=messages)
                
            iters += 1
            response_msg = response.choices[0].message
            
            # If the model didn't call any tools, we are highly done
            if not getattr(response_msg, "tool_calls", None):
                final_output = response_msg.content or ""
                if executed_tools:
                    trace = ", ".join(executed_tools)
                    return f"*[Subagent Trace: {trace}]*\n{final_output}"
                return final_output
            
            # Append assistant message with tool calls
            messages.append(response_msg.model_dump())
            
            # Execute all tools the model asked for
            for tool_call in response_msg.tool_calls:
                func_name = tool_call.function.name
                func_args = tool_call.function.arguments
                
                executed_tools.append(func_name)
                
                # NATIVELY track the assistant calling the tool directly to the DB!
                session_id = session_id_var.get()
                if session_id:
                    import sqlite3
                    tool_calls_json = json.dumps([{
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": func_name,
                            "arguments": func_args
                        }
                    }])
                    with sqlite3.connect(settings.db_path) as con:
                        con.execute(
                            "INSERT INTO messages (session_id, role, tool_calls, name) VALUES (?, ?, ?, ?)",
                            (session_id, f"subagent:{name}", tool_calls_json, f"subagent_{name}")
                        )
                
                try:
                    args_dict = json.loads(func_args)
                    if func_name in tools_dict_by_name:
                        func = tools_dict_by_name[func_name]
                        from core.events import event_bus
                        event_bus.emit({"event": "TOOL_STARTED", "tool": func_name})
                        result = str(func(**args_dict))
                        event_bus.emit({
                            "event": "TOOL_COMPLETED",
                            "tool": func_name,
                            "result": result,
                            "is_error": False
                        })
                    else:
                        result = f"Error: unknown tool '{func_name}' for this subagent."
                except Exception as e:
                    result = f"Error executing '{func_name}': {e}"
                    from core.events import event_bus
                    event_bus.emit({
                        "event": "TOOL_COMPLETED",
                        "tool": func_name,
                        "result": result,
                        "is_error": True
                    })
                    
                # NATIVELY track the tool execution output back into the DB!
                if session_id:
                    with sqlite3.connect(settings.db_path) as con:
                        con.execute(
                            "INSERT INTO messages (session_id, role, content, tool_call_id, name) VALUES (?, ?, ?, ?, ?)",
                            (session_id, f"subagent:{name}", result, tool_call.id, func_name)
                        )
                    
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": result
                })
        
        return f"*[Subagent Trace: {', '.join(executed_tools)}]*\nSubagent failed to complete the task within max iterations."

    # Give the delegate function the metadata the main agent needs to see it as a normal tool
    _delegate_func.__name__ = f"delegate_to_{name}_subagent"
    _delegate_func.__doc__ = description
    
    # Finally, register the delegate into the main registry
    tool(_delegate_func)
