"""AI Package Tracking Line: an external API call with no backend of your own.

Governance point: track_package is a DataMap tool. Its whole pipeline (the HTTP
GET, the response-to-sentence template and the not-found fallback) is declared
here and shipped in the SWML. SignalWire's servers run it. There is no Python
handler and no /swaig webhook for it, so nothing on this server runs during
the call, and the model only ever sees the rendered sentence.
"""
from signalwire import AgentBase, DataMap, FunctionResult

import config


def build_track_package() -> DataMap:
    headers = {"Accept": "application/json"}
    if config.TRACKING_API_KEY:
        headers["Authorization"] = f"Bearer {config.TRACKING_API_KEY}"
    return (
        DataMap("track_package")
        .purpose("Get the delivery status for one tracking number.")
        .parameter("tracking_number", "string",
                   "The tracking number, digits only, no spaces or dashes", required=True)
        .webhook("GET", config.TRACKING_URL, headers=headers)
        .error_keys(["error"])                 # a JSON {"error": ...} counts as a failure
        .output(FunctionResult(config.OUTPUT_TEMPLATE))
        .fallback_output(FunctionResult(config.NOT_FOUND_TEMPLATE))  # 404, timeout, error
    )


class TrackingAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="package-tracking", route=config.ROUTE, port=config.PORT, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You answer the package tracking line for {config.COMPANY_NAME}. Be brief.",
            bullets=[
                "Ask for the tracking number. Read it back digit by digit to confirm.",
                "Call track_package with the digits only, then tell the caller what it says.",
                "Only give status that track_package returned. Never guess a delivery date.",
                "Offer to look up another number, then say goodbye.",
            ],
        )
        self.register_swaig_function(build_track_package().to_swaig_function())


agent = TrackingAgent()

if __name__ == "__main__":
    agent.run()
