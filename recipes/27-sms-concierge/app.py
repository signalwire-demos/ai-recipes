"""SMS concierge: the concierge agent from concierge.py, served over voice and SMS.

Voice: the platform fetches this agent's SWML at ROUTE, like any agent.
SMS: an inbound text hits /sms. The handler hands the text to the AI Chat service with
AIChatClient.chat(), passing this same agent's URL as config_url, and replies with what
the agent said. One conversation per sender, so the agent keeps context between texts.

Two inbound payloads are accepted at /sms:
- JSON {"message": {"from", "to", "body", ...}} from a SWML Webhook resource used for
  messaging (the route in the AI chat docs). The reply is messaging SWML {"reply": ...}.
- A form-encoded laml_webhooks POST (From, To, Body, MessageSid). The reply is cXML <Message>.
Texts from our own SMS number (or a number texting itself) get no reply, so replies can't loop.
TODO(blocked: needs live verification) A handset texting the number is untested. See the README.
"""
import json
from urllib.parse import parse_qsl
from xml.sax.saxutils import escape

import aiohttp
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from signalwire.ai_chat import AIChatClient, AIChatError, ChatInProgressError
from signalwire.core.security import validate_webhook_signature

import config
from concierge import HotelConcierge

EMPTY_REPLY = "Please send your question as text."
BUSY_REPLY = "One moment, I'm still working on your last message."
ERROR_REPLY = "Sorry, I couldn't answer that just now. Please try again in a minute."


def conversation_id(sender: str) -> str:
    """One conversation per phone number. Ids keep only [a-zA-Z0-9_-.:], so use digits."""
    return config.SMS_CONVERSATION_PREFIX + "".join(ch for ch in sender if ch.isdigit())


def parse_inbound(raw: str, content_type: str) -> tuple[str, str, str, str]:
    """Return (format, sender, recipient, body) for either inbound payload."""
    if content_type.startswith("application/json"):
        message = json.loads(raw or "{}").get("message") or {}
        return "swml", str(message.get("from", "")), str(message.get("to", "")), str(message.get("body") or "")
    form = dict(parse_qsl(raw))
    return "cxml", form.get("From", ""), form.get("To", ""), form.get("Body", "")


def is_own_number(sender: str, recipient: str) -> bool:
    """A text from our SMS number, or a number texting itself. Answering it would loop:
    each reply arrives back at /sms as a new inbound text (seen live in recipe 29)."""
    return bool(sender) and sender in {recipient, config.SMS_NUMBER}


def render_reply(fmt: str, text: str | None) -> Response:
    """Messaging SWML or cXML. text=None sends no reply at all."""
    if fmt == "swml":
        main = [{"reply": text}] if text is not None else []
        return JSONResponse({"version": "1.0.0", "sections": {"main": main}})
    message = f"<Message>{escape(text)}</Message>" if text is not None else ""
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response>{message}</Response>'
    return Response(xml, media_type="application/xml")


class SmsConcierge(HotelConcierge):
    """The shared agent plus one extra route. No prompt, step or tool is added here."""

    def __init__(self, chat_client: AIChatClient | None = None, **kwargs):
        super().__init__(**kwargs)
        self._chat = chat_client
        self.mount(self.sms_router())

    @property
    def chat_client(self) -> AIChatClient:
        if self._chat is None:  # built on first use, so a clean clone imports without creds
            self._chat = AIChatClient(url=config.CHAT_API_URL or None)  # creds: SIGNALWIRE_* env
        return self._chat

    def config_url(self) -> str:
        """The SWML URL a voice call uses is also the chat config_url."""
        return config.CHAT_CONFIG_URL or self.get_full_url(include_auth=True).rstrip("/") + config.ROUTE

    async def answer(self, sender: str, body: str) -> str:
        if not body.strip():
            return EMPTY_REPLY
        try:
            reply = await self.chat_client.chat(conversation_id(sender), body, config_url=self.config_url())
        except ChatInProgressError:
            return BUSY_REPLY
        except (AIChatError, aiohttp.ClientError) as exc:
            self.log.warning("ai_chat_failed", error=str(exc))
            return ERROR_REPLY
        return reply.text or ERROR_REPLY

    def sms_router(self) -> APIRouter:
        router = APIRouter()

        @router.post(config.SMS_ROUTE)
        async def inbound_sms(request: Request) -> Response:
            raw = (await request.body()).decode()
            if config.SIGNING_KEY and not validate_webhook_signature(
                config.SIGNING_KEY, request.headers.get("X-SignalWire-Signature", ""),
                config.PUBLIC_URL.rstrip("/") + config.SMS_ROUTE, raw,
            ):
                return Response(status_code=403)
            fmt, sender, recipient, body = parse_inbound(raw, request.headers.get("content-type", ""))
            if is_own_number(sender, recipient):
                return render_reply(fmt, None)
            return render_reply(fmt, await self.answer(sender, body))

        return router


agent = SmsConcierge()

if __name__ == "__main__":
    agent.run()
