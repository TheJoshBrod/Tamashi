# Configuration

Tamashi's settings are layered: `config/agent.yaml` sets agent-level defaults, and `.env` provides secrets and environment overrides.

---

## Changing the Model

Edit `config/agent.yaml`:

```yaml
model: "anthropic/claude-opus-4-6"
```

The model string uses LiteLLM's `provider/model-name` format. Common examples:

| Provider | Model string |
|---|---|
| Anthropic | `anthropic/claude-opus-4-6` |
| Anthropic | `anthropic/claude-sonnet-4-6` |
| OpenAI | `openai/gpt-4o` |
| OpenAI | `openai/gpt-4o-mini` |

See the [LiteLLM docs](https://docs.litellm.ai/docs/providers) for the full list of supported providers and model strings.

### Per-Subagent Model

Each subagent can run on a different model. Add a `model` key to its config file:

```yaml
# config/subagents/nutrition.yaml
model: "openai/gpt-4o-mini"
system_prompt: |
  You are a nutrition logging assistant...
```

If `model` is omitted, the subagent inherits `settings.model` from `agent.yaml`.

---

## All agent.yaml Fields

```yaml
model: "anthropic/claude-opus-4-6"   # LiteLLM provider/model string
temperature: 0.7                      # 0.0–2.0
max_tool_iters: 10                    # max agentic loop iterations before giving up
system_prompt: |
  You are a helpful assistant...
```

---

## Environment Variables (.env)

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Required for OpenAI models |
| `ANTHROPIC_API_KEY` | Required for Anthropic models |
| `TWILIO_ACCOUNT_SID` | Twilio WhatsApp integration |
| `TWILIO_AUTH_TOKEN` | Twilio WhatsApp integration |
| `TAVILY_API_KEY` | `web_search` tool |
| `DEBUG` | Set to `true` to skip Twilio signature validation locally |

---
[← Back to Documentation Hub](README.md)