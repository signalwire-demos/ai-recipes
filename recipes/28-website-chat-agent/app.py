"""Website chat agent: the concierge agent from concierge.py, served over voice and a web widget.

Voice: the platform fetches this agent's SWML at ROUTE, like any agent.
Web: web/index.html is a sample hotel site with a chat widget. The widget talks to a
ChatGateway mounted at /chat on this same app. The gateway holds the API token, pins
config_url to this agent's own SWML URL (the browser can't pick another agent), and
forwards each turn to the AI Chat service. The browser only ever sees a publishable key.
"""
import json

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from signalwire.ai_chat import AIChatClient, AIChatError, ChatGateway

import config
from concierge import HotelConcierge

WEB_DIR = config.HERE / "web"


class WebConcierge(HotelConcierge):
    """The shared agent plus the gateway and the sample site. No prompt, step or tool is added."""

    def __init__(self, chat_client: AIChatClient | None = None, **kwargs):
        super().__init__(**kwargs)
        self.gateway = self.build_gateway(chat_client)
        self.mount(self.gateway.router() if self.gateway else self.not_configured(), prefix=config.CHAT_ROUTE)
        self.mount(self.site_router(), prefix=config.SITE_ROUTE)
        self.mount(StaticFiles(directory=WEB_DIR, html=True), prefix=config.SITE_ROUTE, name="site")
        # ChatGateway lets a service error on start/log/end escape as a bare 500; answer JSON instead.
        self.get_app().add_exception_handler(AIChatError, self.chat_failed)

    def chat_failed(self, request, exc: AIChatError) -> JSONResponse:
        self.log.warning("ai_chat_failed", error=str(exc))
        return JSONResponse({"error": "chat service error"}, status_code=502)

    def config_url(self) -> str:
        """The SWML URL a voice call uses is also the chat config_url."""
        return config.CHAT_CONFIG_URL or self.get_full_url(include_auth=True).rstrip("/") + config.ROUTE

    def build_gateway(self, chat_client: AIChatClient | None) -> ChatGateway | None:
        if chat_client is None:
            try:  # credentials from SIGNALWIRE_PROJECT_ID / SIGNALWIRE_API_TOKEN
                chat_client = AIChatClient(url=config.CHAT_API_URL or None)
            except ValueError as exc:  # a clean clone with no .env still serves voice SWML
                self.log.warning("web_chat_disabled", reason=str(exc))
                return None
        return ChatGateway(
            config_url=self.config_url(),
            key=config.CHAT_KEY or None,
            allowed_origins=config.ALLOWED_ORIGINS,
            client=chat_client,
            max_new_conversations=config.MAX_NEW_CONVERSATIONS,
            max_turns=config.MAX_TURNS,
        )

    @staticmethod
    def not_configured() -> APIRouter:
        router = APIRouter()

        @router.post("/")
        async def chat_unavailable() -> JSONResponse:
            return JSONResponse({"error": "web chat is not configured: set SIGNALWIRE_* in .env"}, 503)

        return router

    def site_router(self) -> APIRouter:
        """widget-config.js: what the page needs to reach the gateway. Nothing in it is secret."""
        router = APIRouter()

        @router.get("/widget-config.js")
        async def widget_config() -> Response:
            settings = {**config.WIDGET, "endpoint": config.CHAT_ROUTE + "/",
                        "key": self.gateway.key if self.gateway else ""}
            return Response(f"window.CONCIERGE_CHAT = {json.dumps(settings)};\n",
                            media_type="application/javascript")

        return router


agent = WebConcierge()

if __name__ == "__main__":
    agent.run()
