from __future__ import annotations
import asyncio

from fastapi import APIRouter, BackgroundTasks, Form, Header, HTTPException, Request
from fastapi.responses import Response

from core.config import settings
from interfaces.base import InboundMessage, MessagingInterface

router = APIRouter()


class TwilioWhatsAppInterface(MessagingInterface):
    def parse_inbound(self, raw: dict) -> InboundMessage:
        return InboundMessage(
            session_id=raw["From"],
            text=raw["Body"],
        )

    def format_outbound(self, text: str) -> str:
        # Kept for compatibility; outbound is now sent via REST API, not TwiML
        from twilio.twiml.messaging_response import MessagingResponse
        resp = MessagingResponse()
        resp.message(text)
        return str(resp)


_interface = TwilioWhatsAppInterface()


def _twilio_client():
    from twilio.rest import Client
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def _validate_twilio_signature(request: Request, x_twilio_signature: str | None) -> None:
    if settings.debug:
        return
    if not x_twilio_signature:
        raise HTTPException(status_code=403, detail="Missing Twilio signature")
    from twilio.request_validator import RequestValidator
    validator = RequestValidator(settings.twilio_auth_token)
    if not validator.validate(str(request.url), {}, x_twilio_signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


def _mark_read(message_sid: str) -> None:
    """Tell WhatsApp the message has been seen (blue ticks).
    Requires a non-sandbox WhatsApp Business account; silently ignored otherwise."""
    try:
        _twilio_client().messages(message_sid).update(status="read")
    except Exception:
        pass  # sandbox / free accounts silently ignore this


def _send_typing(from_whatsapp: str, to_whatsapp: str) -> None:
    """Send a typing indicator via the Twilio Conversations / WhatsApp API.
    Not available on the sandbox; silently ignored if unsupported."""
    try:
        # Twilio exposes typing indicators through the Conversations API.
        # For direct WhatsApp numbers this call is a best-effort.
        client = _twilio_client()
        client.messages.create(
            from_=from_whatsapp,
            to=to_whatsapp,
            content_sid="typing",   # sentinel — replace with actual template SID if needed
        )
    except Exception:
        pass  # fails gracefully on sandbox


def _reply(from_whatsapp: str, to_whatsapp: str, text: str) -> None:
    _twilio_client().messages.create(
        from_=from_whatsapp,
        to=to_whatsapp,
        body=text,
    )


async def _process(
    session_id: str,
    user_text: str,
    message_sid: str,
    from_whatsapp: str,   # e.g. "whatsapp:+14155238886"  (the sandbox number)
    to_whatsapp: str,     # e.g. "whatsapp:+1..."          (the user's number)
) -> None:
    from app import orchestrator
    from core.events import event_bus

    # 1. Blue ticks — tell WhatsApp we've seen the message
    _mark_read(message_sid)

    # 2. Typing indicator — show the "..." bubble while the LLM thinks
    _send_typing(from_whatsapp, to_whatsapp)

    # 3. Run the agent stream
    full_reply = ""
    async for reply_chunk in orchestrator.handle_stream(session_id, user_text):
        if not reply_chunk:
            continue
        
        # Send each chunk as a separate WhatsApp message
        await asyncio.to_thread(_reply, from_whatsapp, to_whatsapp, reply_chunk)
        full_reply += reply_chunk + "\n\n"
        
        # Optional: slight delay between messages for "typing" feel
        await asyncio.sleep(0.5)

    # 4. Signal final completion
    event_bus.emit({"event": "AGENT_REPLY_SENT", "user_text": user_text, "reply": full_reply.strip()})


@router.post("/webhook/twilio")
async def twilio_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    Body: str = Form(...),
    From: str = Form(...),                        # user's WhatsApp number
    To: str = Form(...),                          # our sandbox/business number
    MessageSid: str = Form(...),
    x_twilio_signature: str | None = Header(default=None),
):
    _validate_twilio_signature(request, x_twilio_signature)

    background_tasks.add_task(
        _process,
        session_id=From,
        user_text=Body,
        message_sid=MessageSid,
        from_whatsapp=To,    # we reply *from* our number
        to_whatsapp=From,    # we reply *to* the user
    )

    # Return empty 204 immediately — Twilio doesn't need a TwiML body
    return Response(status_code=204)
