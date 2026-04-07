# phone-claw

A modular LLM-over-WhatsApp framework. Swap models, session stores, and messaging interfaces without touching business logic. Add tools by dropping a Python file in `tools/`.

## Structure

```
phone-claw/
├── app.py                  # FastAPI entrypoint — wires everything together
├── config/agent.yaml       # Prompt, model, temperature (non-secret config)
├── .env                    # Secrets (copy from .env.example)
├── core/
│   ├── config.py           # Unified settings (pydantic-settings + agent.yaml)
│   ├── orchestrator.py     # Tool-calling agent loop
│   └── schemas.py          # Message / ToolCall / ProviderResponse types
├── providers/
│   ├── base.py             # BaseProvider ABC
│   └── litellm_provider.py # LiteLLM (covers OpenAI, Anthropic, Gemini, …)
├── interfaces/
│   ├── base.py             # MessagingInterface ABC
│   └── twilio_whatsapp.py  # Twilio WhatsApp webhook + async reply via REST API
├── sessions/
│   ├── base.py             # SessionStore ABC
│   └── sqlite_store.py     # SQLite-backed conversation history
└── tools/
    ├── registry.py         # @tool decorator + auto-discovery
    ├── open_browser.py     # Opens a URL in Brave browser
    ├── web_search.py       # Web search via Tavily API
    └── __init__.py         # Triggers discovery on import
```

## Quickstart

### 1. Create a virtualenv and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure secrets

```bash
cp .env.example .env
```

Edit `.env`:

```env
# LLM — add whichever provider you're using
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Twilio — from console.twilio.com dashboard
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...

# Tavily web search — from app.tavily.com
TAVILY_API_KEY=tvly-...

# Set True during local ngrok testing (skips Twilio signature validation)
DEBUG=True
```

### 3. Tune the agent

Edit `config/agent.yaml`:

```yaml
model: "anthropic/claude-opus-4-6"   # any LiteLLM model string
temperature: 0.7
max_tool_iters: 10
system_prompt: |
  You are a helpful assistant available over WhatsApp.
  Keep replies concise — WhatsApp messages should be easy to read on a phone.
  When you have access to tools, prefer using them over guessing.
```

### 4. Run the server

```bash
source .venv/bin/activate
uvicorn app:app --reload --port 8000
```

Check `http://localhost:8000/health` — it reports the active model and how many tools are registered.

### 5. Expose locally with ngrok

```bash
ngrok http 8000
```

Copy the `https://....ngrok-free.app` URL, then in the [Twilio Console](https://console.twilio.com):

- Go to **Messaging → Try it out → Send a WhatsApp message** (sandbox)
- Set **"When a message comes in"** to: `https://<your-ngrok-url>/webhook/twilio`
- Method: **HTTP POST**
- Click **Save**

Send a WhatsApp message to your sandbox number — you should get a reply.

## Built-in commands

| Command | What it does |
|---|---|
| `/clear` | Wipes your conversation history and starts a fresh session |

## Built-in tools

Tools are auto-discovered from `tools/` on startup. Current tools:

### `open_browser(url)`
Opens a URL in Brave browser on the host machine. Only `http`/`https` URLs are allowed.

Example: *"open https://github.com"*

### `web_search(query)`
Searches the web via Tavily and returns the top results with a summarized answer.
Requires `TAVILY_API_KEY` in `.env`. Free tier: 1,000 queries/month.

Example: *"search for the latest AI news"*

## Adding a tool

Create any `.py` file in `tools/`. Use the `@tool` decorator:

```python
# tools/weather.py
from tools.registry import tool

@tool
def get_weather(city: str) -> str:
    """Return the current weather for a city."""
    return f"It's sunny in {city}."
```

Restart the server — the model can now call `get_weather`. No other changes needed.

The schema is derived automatically from:
- **type hints** → JSON Schema types
- **docstring first line** → tool description

## Swapping the LLM provider

Change `model` in `config/agent.yaml` to any [LiteLLM-supported model string](https://docs.litellm.ai/docs/providers):

```yaml
model: "anthropic/claude-opus-4-6"
# model: "openai/gpt-4o"
# model: "gemini/gemini-1.5-pro"
```

Add the corresponding API key to `.env`.

## How async messaging works

The webhook returns `204` immediately so Twilio never times out. A background task then:
1. Marks the message as read (blue ticks — requires paid WhatsApp Business account)
2. Sends a typing indicator (requires paid WhatsApp Business account)
3. Runs the agent loop
4. Sends the reply as an outbound REST API call

On the free sandbox only the reply step is visible — read receipts and typing indicators are silently ignored by Twilio.

## Swapping the session store

Subclass `sessions/base.py → SessionStore` and swap the instance in `app.py`:

```python
from sessions.redis_store import RedisSessionStore  # your new impl
_store = RedisSessionStore(url=settings.redis_url)
```

## Debug mode

Set `DEBUG=True` in `.env` to skip Twilio signature validation during local ngrok testing. Never deploy with `DEBUG=True`.
