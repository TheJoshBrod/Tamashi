# Implementation Details

## Dynamic UI States
Tamashi uses a "minimum hold time" policy to ensure UI transitions are readable and aesthetically pleasing. Each "work" state is guaranteed visible for at least 1 second, while terminal replies snap the UI back to a success state immediately.

For instructions on how to add new UI states for custom tools or subagents, see the [Extension Guide](extending_tamashi.md).

State persistence allows subagents (like Nutrition) to keep their unique "Nutrition Mode" face active even while calling other tools like web search.

## Subagent Architecture
Specialized subagents (like Nutrition) operate in isolated LLM loops with their own memory and tool sets. They communicate with the main orchestrator through standard tool-calling interface but maintain their own persistent data in dedicated SQLite databases.

## Event System
The `EventBus` provides real-time updates to the dashboard. The `EmotionManager` acts as the policy layer, translating raw tool and agent events into user-facing emotional states while enforcing the hold-time and snap-back rules.

---
[← Back to Documentation Hub](README.md)
