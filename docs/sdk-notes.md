# SDK fact sheet: signalwire-sdk 3.7.5

Checked on 2026-10-30 against the installed package (import, `dir()`, `inspect.signature`,
and by running every snippet below) and against the SignalWire MCP `get_sdk_guide`.
**Where the MCP guide and the installed code disagree, the code wins**, and the
disagreement is listed in [Surprises](#surprises-read-this-first).

Don't guess names. If something isn't here, check it in the installed package:

```bash
sw-pydocs api FunctionResult.pay      # signature + docstring from the installed code
sw-pydocs grep live_transcribe        # search the docs and examples that ship with 3.7.5
python -c "import inspect, signalwire; print(inspect.signature(signalwire.AgentBase.add_language))"
```

Python: **3.12** (`/opt/homebrew/bin/python3.12`, Docker `python:3.12-slim`). 3.14 also installs
and imports cleanly, including `[search]` (an index built and queried on both). 3.12 is the house
choice for Docker/CI parity and wheel coverage.

## Surprises (read this first)

| Plan / guide says | Reality in 3.7.5 |
|---|---|
| `FunctionResult.transfer(...)` | **NOT FOUND.** Use `connect(destination, final=True, from_addr=None)` for phone/SIP, or `swml_transfer(dest, ai_response, final=True)` for another agent URL |
| Context `isolated` (as an attribute) | It's a setter: `ctx.set_isolated(True)`. Gather has its own `isolated=` kwarg on `set_gather_info` / `add_gather_question` |
| `rpc_dial(to, from_addr, dest_swml)` (MCP guide) | `rpc_dial(to_number, from_number, dest_swml, device_type="phone")`. `dest_swml` is a URL string |
| `rpc_ai_message(call_id, text)` (MCP guide) | `rpc_ai_message(call_id, message_text=None, role="system", global_data=None)` |
| `swaig-test --to-number` (MCP guide) | Not a flag. Real: `--from-number`, `--to-extension` |
| REST `client.messaging` | **NOT FOUND.** It's `client.messages.create(to=, from_=, body=)` |
| REST `client.compat` | **NOT FOUND** in 3.7.5. Calls are `client.calling.*`, call logs are `client.logs.voice.*` |
| Action names in tests | Wire names differ from helper names: `swml_change_step()` emits `{"change_step": ...}`, `swml_change_context()` emits `{"change_context": ...}`, `update_global_data()` emits `{"set_global_data": ...}`. `pay`, `send_sms`, `rpc_dial`, `connect`, `record_call` emit `{"SWML": {...}}` wrapping the verb |
| Prefab class names | `InfoGathererAgent`, `SurveyAgent`, `ReceptionistAgent`, `FAQBotAgent`, `ConciergeAgent` (all in `signalwire.prefabs`) |
| A step with no `set_functions` gets no tools | **It inherits** the previous step's tool set. Call `set_functions([...])` or `set_functions([])` on every step |
| `step.set_end(True)` ends the call | It ends *step mode* only. To hang up, return `FunctionResult(...).hangup()` |
| `swaig-test --list-agents` | Lists the agent, then prints `Error discovering agents: 'agent_name'` (harmless SDK bug). `--list-tools`, `--dump-swml`, `--exec` work |
| Inbound SMS handler `relay_script` | Not a valid `message_handler`. Use `laml_webhooks` + `message_request_url` (cXML-style form POST) |
| `transcribe`, `stream` as SWML verbs | Not SWML verbs in the 3.7.5 schema. They're REST Calling commands (`client.calling.transcribe`, `client.calling.stream`). See `docs/track-c-research.md` |
| "sidecar", "chat-mode kernel" | Shipped as the SWML `ai_sidecar` verb and the AI Chat API (`signalwire.ai_chat.AIChatClient`, `ChatGateway`). See `docs/track-c-research.md` |
| `set_prompt_llm_params(model=...)` | Works; `model`, `temperature`, `top_p` land inside `ai.prompt` in the SWML |

Other behavior worth knowing:

- Handlers are called as `handler(args: dict, raw_data: dict)`; methods decorated with
  `@AgentBase.tool` get `self` first. Handler exceptions are logged, not spoken.
- Tools are `secure=True` by default: a live SWAIG POST needs the per-call token the SDK puts in
  the SWML. A bare `curl` to `/swaig/` is refused. Use `swaig-test --exec` or call the handler directly.
- Basic auth comes from `SWML_BASIC_AUTH_USER` / `SWML_BASIC_AUTH_PASSWORD`. If they're unset the
  SDK generates a random password per process (the warning says so) and the platform gets 401s.
- The public base URL comes from `SWML_PROXY_URL_BASE`. The template's `config.py` copies
  `PUBLIC_URL` into it. `PORT` sets the listen port (default 3000).
- `[search]` query-side NLTK data (`averaged_perceptron_tagger_eng`) isn't downloaded by pip. Without
  it you get a warning and basic token processing, and search still works. To silence it:
  `python -m nltk.downloader averaged_perceptron_tagger_eng punkt_tab`.

## AgentBase

```python
from signalwire import AgentBase, FunctionResult

class MyAgent(AgentBase):
    def __init__(self):
        super().__init__(name="my-agent", route="/", port=3000)   # basic_auth=(u, p) optional
        self.add_language("English", "en-US", "rime.spore")
        self.prompt_add_section("Role", "You answer the phone for Example Co.")

agent = MyAgent()
if __name__ == "__main__":
    agent.run()            # serves SWML on :PORT; also detects Lambda / Cloud Functions / CGI
```

Signature: `AgentBase(name, route="/", host="0.0.0.0", port=None, basic_auth=None, use_pom=True,
token_expiry_secs=3600, auto_answer=True, record_call=False, record_format="mp4",
record_stereo=True, default_webhook_url=None, agent_id=None, native_functions=None,
schema_path=None, suppress_logs=False, enable_post_prompt_override=False,
check_for_input_override=False, config_file=None, schema_validation=True, signing_key=None,
trust_proxy_for_signature=False, swaig_secret=None)`.

Prompt helpers: `prompt_add_section(title, body="", bullets=None, numbered=False, numbered_bullets=False, subsections=None)`,
`prompt_add_subsection`, `prompt_add_to_section`, `set_prompt_text(text)`, `set_prompt_pom(pom)`.
Data: `set_global_data(dict)`, `update_global_data(dict)`. Params: `set_params(dict)`, `set_param(k, v)`.
Hints: `add_hint`, `add_hints`, `add_pattern_hint`, `add_pronunciation(replace, with_text, ignore_case=False)`.
Verbs around the AI: `add_pre_answer_verb`, `add_answer_verb`, `add_post_answer_verb`, `add_post_ai_verb(verb_name, config)`.

## Tools: `@AgentBase.tool` and `define_tool`

```python
class MyAgent(AgentBase):
    @AgentBase.tool(
        name="check_hours",
        description="Look up opening hours for one day of the week.",
        parameters={"type": "object",
                    "properties": {"day": {"type": "string", "description": "e.g. monday"}},
                    "required": ["day"]},
    )
    def check_hours(self, args, raw_data):
        return FunctionResult(f"Open 9 to 5 on {args['day']}.")

# On an instance (no subclass): same kwargs
@agent.tool(name="ping", description="Health check", parameters={"type": "object", "properties": {}})
def ping(args, raw_data):
    return FunctionResult("pong")

# Imperative form
agent.define_tool(name="lookup", description="...", parameters={"order_id": {"type": "string"}},
                  handler=lambda args, raw: FunctionResult("ok"), secure=True,
                  fillers={"en-US": ["One moment."]}, required=["order_id"])
```

`define_tool(name, description, parameters, handler, secure=True, fillers=None, webhook_url=None,
required=None, is_typed_handler=False, gates=None, gate_fillers=None, **swaig_fields)`.
`parameters` may be a full JSON Schema object or just the `properties` map.

## FunctionResult and its actions

`FunctionResult(response=None, post_process=False, tool_result=None, tool_prompt=None)`. Every
helper returns `self`; chain them. `to_dict()` gives `{"response": ..., "action": [...]}`.

```python
from signalwire import FunctionResult

r = (FunctionResult("Verified. What can I help with?")
     .update_global_data({"customer": {"id": "C-01", "tier": "gold"}})   # -> {"set_global_data": {...}}
     .swml_change_step("account_menu"))                                  # -> {"change_step": "account_menu"}

FunctionResult("...").swml_change_context("billing")                     # -> {"change_context": "billing"}
FunctionResult("...").remove_global_data(["otp"])

# PCI: stop recording, then pay. Amount from global_data, never from model args.
amount = raw_data["global_data"]["balance_due"]
FunctionResult("Transferring you to secure payment.") \
    .stop_record_call(control_id="main") \
    .pay(payment_connector_url=f"{PUBLIC_URL}/pay", charge_amount=f"{amount:.2f}",
         security_code=True, postal_code=True, max_attempts=2)
# pay(payment_connector_url, input_method="dtmf", status_url=None, payment_method="credit-card",
#     timeout=5, max_attempts=1, security_code=True, postal_code=True, min_postal_code_length=0,
#     token_type="reusable", charge_amount=None, currency="usd", language="en-US", voice="woman",
#     description=None, valid_card_types="visa mastercard amex", parameters=None, prompts=None,
#     ai_response="The payment status is ${pay_result}, ...")
# Helpers: FunctionResult.create_payment_prompt(for_situation, actions, card_type=None, error_type=None),
#          create_payment_action(action_type, phrase), create_payment_parameter(name, value)

FunctionResult("Recording started.").record_call(control_id="main", stereo=True, format="mp3")
# record_call(control_id=None, stereo=False, format="wav"|"mp3"|"mp4", direction="both",
#             terminators=None, beep=False, input_sensitivity=44.0, initial_timeout=None,
#             end_silence_timeout=None, max_length=None, status_url=None)
FunctionResult("Paused.").stop_record_call(control_id="main")

# Screened transfer: hold caller, dial the human with a briefing SWML URL
FunctionResult("Let me get an adjuster.").rpc_dial(
    to_number=ADJUSTER_NUMBER, from_number=FROM_NUMBER,
    dest_swml=f"{PUBLIC_URL}/brief?claim=CL-0101")   # device_type="phone"

FunctionResult("Sent.").rpc_ai_message(call_id=other_call_id, message_text="Customer is upset.",
                                       role="system")
FunctionResult("...").rpc_ai_unhold(call_id=held_call_id)

FunctionResult("Connecting you to booking.").swml_transfer(
    dest=f"{PUBLIC_URL}/booking?h=abc123", ai_response="Welcome back.", final=False)

FunctionResult("Connecting you now.").connect("+15550100", final=True, from_addr=FROM_NUMBER)

FunctionResult("I've texted you the details.").send_sms(
    to_number=caller, from_number=SMS_FROM, body="Booked: Fri 10:00, ref R-0142")
# send_sms(to_number, from_number, body=None, media=None, tags=None, region=None)

FunctionResult("...").toggle_functions([{"function": "issue_refund", "active": False}])
FunctionResult("Goodbye.").hangup()
```

Also present: `say`, `hold(prompt=None, timeout=300, step=None, timeout_step=None)`, `stop`,
`wait_for_user`, `execute_swml(swml, transfer=False)`, `join_conference`, `join_room`, `sip_refer`,
`tap(uri, control_id=None, direction="both", codec="PCMU", rtp_ptime=20, status_url=None)`,
`stop_tap`, `play_background_file`, `stop_background_file`, `switch_context` (a prompt reset, not
`swml_change_context`), `simulate_user_input`, `update_settings`, `set_end_of_speech_timeout`,
`set_speech_event_timeout`, `enable_functions_on_timeout`, `enable_extensive_data`,
`replace_in_history`, `add_dynamic_hints`, `clear_dynamic_hints`, `change_voice`, `set_metadata`,
`remove_metadata`, `swml_user_event`, `execute_rpc`, `rpc_ai_global_data`, `add_action(name, data)`,
`add_actions(list)`, `set_post_process(bool)`. **NOT FOUND:** `transfer`, `change_step`, `change_context`.

## Contexts and steps

```python
ctx = self.define_contexts().add_context("default")      # a single context must be named "default"
ctx.add_step("verify") \
   .set_text("Ask for the account number and date of birth, then call verify_identity.") \
   .set_functions(["verify_identity"]) \
   .set_valid_steps([])                                   # [] = no next_step tool; only handlers move
ctx.add_step("account_menu") \
   .set_text("Help with balance, transactions or disputes for ${global_data.customer.name}.") \
   .set_functions(["get_balance", "list_transactions", "open_dispute"]) \
   .set_valid_steps(["wrap_up"])
ctx.add_step("wrap_up").set_text("Say goodbye.").set_functions([])

# Multiple isolated personas
cb = self.define_contexts()
billing = cb.add_context("billing").set_isolated(True).set_valid_contexts(["sales", "support"])
billing.add_section("Role", "You are Bea in billing.")      # or set_prompt(text)
billing.add_enter_filler("en-US", ["Let me get billing."])
billing.add_step("main").set_text("...").set_functions(["issue_refund"])
```

`Context`: `add_step(name, *, task=None, bullets=None, criteria=None, functions=None, valid_steps=None)`,
`set_valid_steps`, `set_valid_contexts`, `set_isolated(bool)`, `set_prompt`, `add_section(title, body)`,
`add_bullets`, `set_system_prompt`, `add_system_section`, `add_system_bullets`, `set_user_prompt`,
`set_consolidate`, `set_full_reset`, `set_post_prompt`, `set_initial_step`, `add_enter_filler(lang, list)`,
`add_exit_filler`, `set_enter_fillers(dict)`, `set_exit_fillers`, `get_step`, `move_step`, `remove_step`, `set_history`.

`Step`: `set_text`, `add_section`, `add_bullets`, `set_step_criteria`, `set_functions(list | "none")`,
`set_valid_steps`, `set_valid_contexts`, `set_end`, `set_skip_user_turn`, `set_skip_to_next_step`,
`set_gather_info`, `add_gather_question`, `set_reset_system_prompt/_user_prompt/_consolidate/_full_reset`,
`clear_sections`, `set_history`. A step takes `set_text` **or** sections, not both.

### Gather

```python
ctx.add_step("screen") \
   .set_text("Ask the screening questions one at a time.") \
   .set_functions([]) \
   .set_gather_info(output_key="candidate", completion_action="submit",
                    prompt="I have a few quick questions.") \
   .add_gather_question(key="work_auth", question="Are you authorized to work in the US?",
                        type="boolean", confirm=True) \
   .add_gather_question(key="years", question="How many years of experience?", type="integer") \
   .add_gather_question(key="start", question="Earliest start date?", confirm=True)
ctx.add_step("submit").set_text("Call submit_candidate.").set_functions(["submit_candidate"])
# handler reads raw_data["global_data"]["candidate"]
```

`set_gather_info(output_key=None, completion_action=None, prompt=None, isolated=False)`;
`completion_action` is `"next_step"`, a step name in the same context, or `None`.
`add_gather_question(key, question, type="string", confirm=False, prompt=None, functions=None, isolated=None)`;
types: `string`, `integer`, `number`, `boolean`. While gathering, only `gather_submit` and that
question's `functions` are callable.

## Languages

```python
self.add_language("English", "en-US", "rime.spore",
                  speech_fillers=["Um..."], function_fillers=["One moment."])
self.add_language("Spanish", "es-MX", "rime.spore", engine=None, model=None)
```

`add_language(name, code, voice, speech_fillers=None, function_fillers=None, engine=None, model=None, params=None)`.
Also `set_languages(list)`, `set_multilingual(...)`, `set_language_params`.

## Prefabs (`signalwire.prefabs`)

```python
from signalwire.prefabs import (InfoGathererAgent, SurveyAgent, ReceptionistAgent,
                                FAQBotAgent, ConciergeAgent)

survey = SurveyAgent(survey_name="CSAT", brand_name="Example Co", questions=[
    {"id": "rating", "text": "From 1 to 5, how did we do?", "type": "rating", "scale": 5},
    {"id": "best", "text": "What did you like most?", "type": "multiple_choice", "options": ["price", "service"]},
    {"id": "recommend", "text": "Would you recommend us?", "type": "yes_no"},
    {"id": "more", "text": "Anything else?", "type": "open_ended", "required": False},
])                                      # tools: validate_response, log_response
info = InfoGathererAgent(questions=[{"key_name": "name", "question_text": "Your name?"},
                                    {"key_name": "dob", "question_text": "Date of birth?", "confirm": True}])
                                        # tools: start_questions, submit_answer
rec = ReceptionistAgent(departments=[{"name": "sales", "description": "Buying", "number": "+15550100"}])
                                        # tools: collect_caller_info, transfer_call
```

Signatures: `SurveyAgent(survey_name, questions, introduction=None, conclusion=None, brand_name=None,
max_retries=2, name="survey", route="/survey", **kwargs)`; `InfoGathererAgent(questions=None,
name="info_gatherer", route="/info_gatherer", **kwargs)`; `ReceptionistAgent(departments,
name="receptionist", route="/receptionist", greeting=..., voice="rime.spore", **kwargs)`;
`FAQBotAgent(faqs, suggest_related=True, persona=None, name="faq_bot", route="/faq", **kwargs)`;
`ConciergeAgent(venue_name, services, amenities, hours_of_operation=None, special_instructions=None,
welcome_message=None, name="concierge", route="/concierge", **kwargs)`. Results: override
`on_summary` or read the tool calls in a subclass.

## Skills

```python
agent.add_skill("native_vector_search", {
    "tool_name": "search_docs",
    "index_file": "data/knowledge.swsearch",
    "description": "Search the product docs",
    "count": 3,
    "similarity_threshold": 0.2,
    "no_results_message": "That's not in the docs.",
})
```

`native_vector_search` params (from `get_parameter_schema()`): `tool_name` (default
`search_knowledge`), `index_file`, `build_index`, `source_dir`, `remote_url`, `index_name`, `count` (5),
`similarity_threshold` (0.0), `tags`, `global_tags`, `file_types`, `exclude_patterns`,
`no_results_message`, `response_prefix`, `response_postfix`, `max_content_length`,
`response_format_callback`, `description`, `hints`, `nlp_backend`, `query_nlp_backend`,
`index_nlp_backend`, `backend` (`sqlite`|`pgvector`), `connection_string`, `collection_name`,
`keyword_weight`, `model_name` (`mini`), `overwrite`, `verbose`, `skip_prompt`, `swaig_fields`.
Needs `pip install "signalwire-sdk[search]==3.7.5"`.

Writing and registering a custom skill:

```python
from signalwire import register_skill, FunctionResult
from signalwire.core.skill_base import SkillBase

class StockQuoteSkill(SkillBase):
    SKILL_NAME = "stock_quote"
    SKILL_DESCRIPTION = "Spoken stock quotes"
    SKILL_VERSION = "1.0.0"
    REQUIRED_PACKAGES: list = []
    REQUIRED_ENV_VARS: list = []
    SUPPORTS_MULTIPLE_INSTANCES = False

    @classmethod
    def get_parameter_schema(cls):
        schema = super().get_parameter_schema()
        schema.update({
            "provider": {"type": "string", "description": "mock|alphavantage|finnhub", "default": "mock", "required": False},
            "api_key": {"type": "string", "description": "Market data key", "required": False, "hidden": True},
        })
        return schema

    def setup(self) -> bool:                    # self.params holds the add_skill() dict
        self.provider = self.params.get("provider", "mock")
        return True

    def register_tools(self) -> None:
        self.define_tool(name="get_quote", description="Get a stock quote",
                         parameters={"ticker": {"type": "string", "description": "Ticker symbol"}},
                         handler=self._quote)

    def _quote(self, args, raw_data):
        return FunctionResult(f"{args['ticker'].upper()} is trading at 101.25.")

register_skill(StockQuoteSkill)                 # or signalwire.add_skill_directory("skills/")
agent.add_skill("stock_quote", {"provider": "mock"})
```

Other hooks: `get_hints()`, `get_global_data()`, `get_prompt_sections()`, `get_instance_key()`,
`cleanup()`. Agent side: `list_skills()`, `has_skill(name)`, `remove_skill(name)`. Module-level:
`signalwire.list_skills()`, `signalwire.list_skills_with_params()`.

## DataMap (runs on SignalWire, not your server)

```python
from signalwire import DataMap, FunctionResult

track = (DataMap("track_package")
         .purpose("Get the delivery status for a tracking number")
         .parameter("tracking_number", "string", "The tracking number", required=True)
         .webhook("GET", "https://raw.githubusercontent.com/signalwire-demos/ai-recipes/main/recipes/05-x/data/${args.tracking_number}.json")
         .output(FunctionResult("Package ${input.args.tracking_number} is ${status}, last seen in ${location}."))
         .fallback_output(FunctionResult("I couldn't find that tracking number.")))
agent.register_swaig_function(track.to_swaig_function())
```

`parameter(name, param_type, description, required=False, enum=None)`,
`webhook(method, url, headers=None, form_param=None, input_args_as_params=False, require_args=None)`,
`body(dict)`, `params(dict)`, `output(FunctionResult)`, `fallback_output(FunctionResult)`,
`expression(test_value, pattern, output, nomatch_output=None)`, `foreach(dict)`, `error_keys`,
`global_error_keys`, `webhook_expressions`. Shortcuts: `signalwire.create_simple_api_tool`,
`create_expression_tool`. **Variable scopes (checked against the 3.7.5 simulator):** inside a webhook's `output`, response fields are read from the root (`${status}`, not `${response.status}`), and function arguments are `${input.args.x}`. `${args.x}` works only in the webhook URL and in `fallback_output`. Writing `${response.x}` renders an empty string. The simulator blocks localhost URLs unless `SWML_ALLOW_PRIVATE_URLS=true` is set. Working example: `recipes/05-package-tracking-line`.

`swaig-test --exec track_package --tracking_number X --verbose` simulates
the pipeline locally.

## MCP

```python
agent.add_mcp_server("https://mcp.example.com/mcp", headers={"Authorization": f"Bearer {token}"})
# add_mcp_server(url, headers=None, resources=False, resource_vars=None)
# renders ai.SWAIG.mcp_servers = [{"url": ..., "headers": {...}}]; the platform discovers the tools per call,
# so they do NOT appear in SWAIG.functions in a local dump.

agent.enable_mcp_server()   # exposes this agent's tools as JSON-RPC at POST /mcp (behind basic auth)
# verified: {"jsonrpc":"2.0","id":1,"method":"tools/list"} -> {"result":{"tools":[...]}}
```

## Dynamic config (per-request agents)

```python
def configure(query_params, body_params, headers, agent):
    tenant = query_params.get("tenant") or body_params.get("call", {}).get("to_number")
    cfg = load_tenant(tenant)
    agent.set_global_data({"tenant": cfg["id"]})
    agent.prompt_add_section("Role", cfg["prompt"])
    for tool in cfg["tools"]:
        agent.define_tool(**TOOLS[tool])          # only this tenant's tools are registered

agent.set_dynamic_config_callback(configure)
```

The callback gets a per-request **copy** of the agent; changes apply to that request only. It runs
in a worker thread. Test per tenant with `swaig-test app.py --dump-swml --query-params '{"tenant":"dental"}'`.

## LLM params, post_prompt and on_summary

```python
class SalesAgent(AgentBase):
    def __init__(self):
        super().__init__(name="sales", route="/")
        self.set_prompt_llm_params(model="gpt-4.1-nano", temperature=0.3, top_p=0.9)
        self.set_post_prompt('Return only JSON: {"outcome": "won|lost", "competitor": string|null}')
        self.set_post_prompt_llm_params(temperature=0.1)

    def on_summary(self, summary, raw_data=None):   # summary = parsed post-prompt output
        with open("data/calls.jsonl", "a") as f:     # raw_data = full post-prompt payload
            f.write(json.dumps({"summary": summary}) + "\n")
```

`set_post_prompt(text)` and `set_post_prompt_url(url)`; the SDK serves `/post_prompt` and calls
`on_summary(summary, raw_data)`. Per context: `Context.set_post_prompt(text)`.

## AgentServer (several agents, one port)

```python
from signalwire import AgentServer
server = AgentServer(host="0.0.0.0", port=3000)     # log_level="info"
server.register(ConciergeDesk(), "/concierge")   # your AgentBase subclasses
server.register(BookingDesk(), "/booking")
server.serve_static_files("web", route="/captions")  # optional static dir
server.run()
```

Also `unregister(route)`, `get_agents()`, `get_agent(route)`, `setup_sip_routing(route="/sip", auto_map=True)`,
`register_global_routing_callback`. swaig-test: `--route /booking` picks one agent.

## swaig-test

```bash
swaig-test app.py --list-tools                       # tools + params
swaig-test app.py --list-agents                      # (prints a harmless 'agent_name' error after the list)
swaig-test app.py --dump-swml --raw | jq '.sections.main[-1].ai.prompt.contexts'
swaig-test app.py --exec check_hours --day friday    # all options go BEFORE --exec
swaig-test app.py --call-id s1 --custom-data '{"global_data": {"tier": "gold"}}' --exec get_balance
swaig-test app.py --dump-swml --query-params '{"tenant": "dental"}' --header X-Foo=bar --user-vars '{...}'
swaig-test multi.py --route /booking --list-tools    # or --agent-class BookingAgent
swaig-test app.py --simulate-serverless lambda --dump-swml
```

Other flags: `--verbose`, `--minimal`, `--fake-full-data`, `--call-type sip|webrtc`,
`--call-direction inbound|outbound`, `--call-state`, `--from-number`, `--to-extension`,
`--override call.state=answered`, `--env KEY=VALUE`, `--env-file`, `--parse-only`/`--dry-run`.

## sw-search

```bash
pip install "signalwire-sdk[search]==3.7.5"
sw-search ./docs --output data/knowledge.swsearch --chunking-strategy markdown --file-types md,txt
sw-search search data/knowledge.swsearch "when are you open"        # query an index
sw-search validate data/knowledge.swsearch                          # prints chunk/file counts
```

Build flags: `--output`, `--output-dir`, `--output-format index|json`, `--backend sqlite|pgvector`,
`--connection-string`, `--chunking-strategy sentence|sliding|paragraph|page|semantic|topic|qa|json|markdown`,
`--max-sentences-per-chunk`, `--chunk-size`, `--overlap-size`, `--min-chunk-size`, `--file-types`,
`--exclude`, `--languages`, `--model mini|base`, `--tags`, `--index-nlp-backend nltk|spacy`, `--validate`.
The first build downloads the `all-MiniLM-L6-v2` model (about 90 MB).

## REST client

```python
from signalwire.rest import RestClient          # or: from signalwire import RestClient
client = RestClient(project=os.environ["SIGNALWIRE_PROJECT_ID"],
                    token=os.environ["SIGNALWIRE_API_TOKEN"],
                    host=os.environ["SIGNALWIRE_SPACE"])          # all three also read from env

# Outbound call into an agent (or inline SWML with swml={...})
call = client.calling.dial(from_=os.environ["OUTBOUND_1"], to=candidate,
                           url=f"{PUBLIC_URL}/?candidate=C-01", status_url=f"{PUBLIC_URL}/status")
call["id"]                                      # call SID
# dial(*, from_, to, caller_id=None, fallback_url=None, status_url=None, status_events=None,
#      url_method=None, url=None, codecs=None, swml=None)

client.logs.voice.get(call_id)                  # status, duration, ...; logs.voice.list(**filters)

# Numbers
client.phone_numbers.list(filter_number="+19183951340")["data"]
client.phone_numbers.search(areacode="918", max_results=10)["data"]   # [{"e164", "capabilities", ...}]
client.phone_numbers.create(number="+19185550100")                    # BUYS a number: lead only
client.phone_numbers.set_swml_webhook(number_id, "https://user:pass@host/")   # call_handler=relay_script
# Inbound SMS: message_handler accepts ONLY relay_context | relay_topic | relay_application |
# laml_webhooks | laml_application (no relay_script). For a webhook use laml_webhooks: the platform
# POSTs a form-encoded cXML-style request (From, To, Body, MessageSid...) to message_request_url.
client.phone_numbers.update(number_id, message_handler="laml_webhooks",
                            message_request_url=f"{PUBLIC_URL}/sms", message_request_method="POST")
# The other route (documented for AI chat over SMS, see docs/track-c-research.md (c)): a Fabric SWML
# Webhook resource with used_for "messaging" receives JSON {"message": {"from","to","body",...}} and
# replies with messaging SWML ({"reply": "..."}). In 3.7.5, fabric.swml_webhooks.create() types
# used_for as Literal['calling'] only, and fabric.resources.assign_phone_route(id, phone_route_id=,
# handler=) does the number binding. Messaging via that path is UNVERIFIED in the SDK: pass
# extras={"used_for": "messaging"} and ask the lead to confirm on a live number before relying on it.

# Messaging (namespace is `messages`)
client.messages.create(to="+15550142", from_=os.environ["SMS_1"], body="Your booking is confirmed.")

# Live-call control: client.calling.ai_message, ai_hold, ai_unhold, live_transcribe, transcribe,
# stream, tap, record, play, collect, transfer, update, end, ...
# 10DLC: client.registry.brands.list(), .list_campaigns(id), client.registry.campaigns.list_numbers(id),
#        client.registry.campaigns.create_order(id, phone_numbers=[...])
# SWML scripts: client.fabric.swml_scripts.create(name=..., contents=yaml_text)
```

Response objects are plain dicts (TypedDicts). `from_` has a trailing underscore.

## AI Chat (AIChatClient, ChatGateway): gotchas found in #27/#28

- `AIChatClient` builds `https://{SIGNALWIRE_SPACE}.signalwire.com/api/ai/chat`. Our `.env` stores the full host (`example.signalwire.com`), which produces `...signalwire.com.signalwire.com` and fails TLS. Pass the API URL explicitly (see `CHAT_API_URL` in recipes 27/28).
- An unhandled `ChatGateway` error returns a plain-text 500 on `start`, `log` and `end`. Add a JSON error handler if a browser widget calls it.
- `agent.mount(...)` is the supported way to add extra routes (`/sms`, `/pay`, static pages) next to the agent.
