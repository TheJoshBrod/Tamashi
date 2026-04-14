# Messaging Interfaces

Messaging interfaces define how Tamashi communicates with the outside world. They handle the translation between platform-specific webhooks and Tamashi's internal message format.

## The MessagingInterface Base Class

All interfaces must inherit from `interfaces.base.MessagingInterface` and implement the following methods:

- `parse_inbound(raw_payload: dict)`: Converts a platform's raw JSON/Form data into an `InboundMessage` (session_id and text).
- `format_outbound(text: str)`: Prepares a string for transmission back to the platform.

Existing interfaces are located in the `interfaces/` directory and are automatically registered in `app.py`.

---

## Twilio (WhatsApp)

The primary interface for Tamashi is WhatsApp via Twilio.

### Configuration
1.  **Secrets**: Add `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` to your `.env` file.
2.  **Sandbox**: Use the [Twilio Console](https://console.twilio.com) to join a WhatsApp sandbox number.
3.  **Webhook**: Point the "When a message comes in" field to `https://<your-domain>/webhook/twilio`.

### Local Development (ngrok)
To test locally, use ngrok to expose your server:
```bash
ngrok http 8000
```
Update your Twilio webhook URL with the resulting `https://...` address.

**Note**: Set `DEBUG=True` in `.env` to bypass Twilio signature validation during local testing.

---

## Adding New Interfaces
To add support for Discord, Slack, or Telegram:
1.  Create a new file in `interfaces/` (e.g., `discord.py`).
2.  Implement a FastAPI router with a webhook endpoint.
3.  Use the `orchestrator.handle_message(message: InboundMessage)` method to process messages.
4.  Include your new router in `app.py`.

---
[← Back to Documentation Hub](README.md)
