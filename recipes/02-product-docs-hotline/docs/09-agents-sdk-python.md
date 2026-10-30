# The Python Agents SDK

The Agents SDK builds AI agents in code. Install it with `pip install signalwire-sdk`.

An agent is a class that extends `AgentBase`. You add a language and voice, write the prompt, define tools and call `run()`. The agent serves SWML on port 3000 by default and handles the SWAIG requests for its tools.

```python
from signalwire import AgentBase, FunctionResult

class HoursAgent(AgentBase):
    def __init__(self):
        super().__init__(name="hours", route="/")
        self.add_language("English", "en-US", "rime.spore")
        self.prompt_add_section("Role", "You answer the phone for Example Co.")

    @AgentBase.tool(name="check_hours", description="Opening hours for a day",
                    parameters={"type": "object", "properties": {"day": {"type": "string"}}})
    def check_hours(self, args, raw_data):
        return FunctionResult("We are open 9 to 5.")

HoursAgent().run()
```

## Environment variables

- `PORT` sets the listen port.
- `SWML_BASIC_AUTH_USER` and `SWML_BASIC_AUTH_PASSWORD` set basic authentication. If they are not set, the SDK makes up a random password each time it starts.
- `SWML_PROXY_URL_BASE` is the public URL of the app, used to build the webhook URLs in the SWML.

`run()` also detects serverless platforms such as AWS Lambda and Google Cloud Functions.
