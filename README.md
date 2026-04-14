# Tamashi (魂)

A modular, personal LLM-over-WhatsApp framework designed for low-friction tool use and emotional UI feedback. 

## Naming
Tamashi (魂) means "soul" or "spirit" in Japanese. The project draws inspiration from the "ghost in the machine" concept popularized by Ghost in the Shell—an intelligent presence operating within a digital shell.

## Core Features
- **WhatsApp Interface**: Interact with your personal agent through Twilio.
- **Emotional UI**: A dedicated websocket-driven dashboard features a reactive creature that changes its "face" based on the agent's internal state (thinking, searching, calculating, or logging nutrition).
- **Subagent Architecture**: Specialized loops for tasks like nutrition logging that maintain their own memory and tool sets.
- **SQL Persistence**: All conversation history and subagent data (e.g., meals) are stored in SQLite for easy local querying.
- **Tool Discovery**: Drop any Python function into `tools/` and it becomes available to the agent via automatic JSON schema generation.

## Project Structure
```
Tamashi/
├── app.py                  # FastAPI server and routing
├── config/
│   ├── agent.yaml          # Main agent personality and model settings
│   └── subagents/          # Individual subagent configurations
├── core/
│   ├── orchestrator.py     # Main agent loop and tool dispatching
│   ├── events.py           # EventBus for UI state updates
│   └── config.py           # Pydantic-based settings management
├── display/
│   ├── emotion_manager.py  # UI policy layer (state hold times and snap-backs)
│   └── static/             # Real-time dashboard (HTML/CSS/JS)
├── interfaces/             # Messaging layer (WhatsApp/Twilio)
├── sessions/               # SQLite-backed history
├── subagents/              # Isolated LLM loops (e.g., Nutrition)
└── tools/                  # Extensible tool registry
```

## Documentation
Comprehensive technical documentation, including architecture overviews, interface setup, and extension guides, can be found in the [Documentation Hub](docs/README.md).

## Quick Start
1.  **Environment**: `pip install -r requirements.txt`
2.  **Secrets**: Copy `.env.example` to `.env` and provide your API keys (OpenAI, Twilio, Tavily).
3.  **Run**: `uvicorn app:app --reload`
4.  **UI**: Open `http://localhost:8000/display/` to see the reactive dashboard.
