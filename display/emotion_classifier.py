from __future__ import annotations

from litellm import acompletion
from core.events import EmotionState

CLASSIFIER_MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = """You are an emotion classifier for a cute AI assistant creature displayed on a screen.

Based on the conversation, pick the single most appropriate emotion:
- idle: nothing happening, relaxed
- listening: user just sent a message, attentive
- thinking: processing a complex question
- working: actively doing a task
- searching: looking up information
- calculating: doing math or analysis
- delegating: asking another system for help
- success: completed task, happy, helpful
- confused: uncertain, error occurred, puzzled
- error: something went wrong, apologetic

Respond with ONLY the emotion word, nothing else."""


async def classify_reply(user_text: str, reply: str) -> EmotionState:
    """Classify the appropriate emotion for a completed agent reply.

    Uses prompt caching on the static system block to reduce token cost on
    repeated calls within the same 5-minute cache window.
    """
    try:
        response = await acompletion(
            model=CLASSIFIER_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": f"User asked: {user_text}\nAssistant replied: {reply}",
                },
            ],
            max_tokens=20,
            temperature=0,
        )
        emotion_text = response.choices[0].message.content.strip().lower()
        return EmotionState(emotion_text)
    except Exception:
        return EmotionState.SUCCESS  # safe fallback — IDLE fires 3 s later via EmotionManager
