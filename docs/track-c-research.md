# Track C research: live transcription, AI sidecar, AI chat, pay

Research note for builders B6, B10, B11, B12. Read-only research, done 2026-10-30 against
signalwire-sdk 3.7.5 (installed source) and the SignalWire docs MCP (docs.signalwire.com content).
Every claim cites its source. "SDK:" paths are relative to
`site-packages/signalwire/` in the 3.7.5 install. "Docs:" slugs are signalwire.com/docs URLs.
Nothing here was run against a live Space.

## Verdict

| Topic | Documented? | Mechanism to use | Builder action |
|---|---|---|---|
| (a) Live transcript to my webhook (#21, #22, #26) | Partial | SWML `live_transcribe` with `action.start.webhook` + `live_events: true` (or REST `client.calling.live_transcribe`) | Build the consumer now; parse payload defensively. TODO(blocked: live_transcribe webhook payload schema undocumented). Conference/per-participant behavior undocumented. |
| (b) AI sidecar / copilot (#23, #24) | Yes (new) | SWML `ai_sidecar` verb (both legs, SWAIG tools, events to `url`) | Build now on `ai_sidecar`. Card push = your own UI fed by sidecar callbacks. "Whisper" via `rpc_ai_message` only reaches an AI agent, not a human rep. |
| (c) Chat / SMS mode (#27, #28) | Yes | AI Chat API `POST /api/ai/chat` via `signalwire.ai_chat.AIChatClient`; browser via `ChatGateway` | Build now. Same SWML agent served at `config_url`. SMS = inbound messaging webhook calling `AIChatClient.chat`. #29 needs no chat mode. |
| (d) `pay` connector contract (#10) | Yes | SWML `pay` / `FunctionResult.pay(payment_connector_url=PUBLIC_URL/pay, ...)` | Build mock connector now from documented request/response. Space-level "pay enabled" requirement: not found in any source read. |

## Name corrections versus the plan

- "sidecar" is real and shipped in docs: SWML verb `ai_sidecar` (Docs: swml/reference/calling/ai-sidecar; SDK: schema.json `$defs.AiSidecar`, core/swml_verbs_generated.py `AiSidecarConfig`; CHANGELOG 3.4.0 "typed `ai_sidecar` verb").
- "chat-mode kernel" (strategy doc `mary` L211/L483, listed as roadmap) shipped as the **AI Chat API** (`POST /api/ai/chat`) plus SDK `signalwire.ai_chat` (CHANGELOG 3.4.0).
- "pay connector" = the `payment_connector_url` param of SWML `pay`.
- `transcribe` and `stream` are **not** SWML verbs in the SDK 3.7.5 schema. `SWMLService.add_verb("transcribe"|"stream", ...)` raises `SchemaValidationError: Unknown verb` (verified offline). The docs site does have a SWML `transcribe` page (Docs: swml/reference/calling/transcribe) and mentions `stream` under `connect` (Docs: platform/voice/call-streaming). Use the REST Calling commands `transcribe` / `stream` from the SDK instead.

---

## (a) Live transcription to the developer's own webhook

**Documented today: partial.** Start/stop/summarize and params are documented. The live event
payload schema is **not documented** in any source read.

### What pushes transcript TEXT to a URL I own

| Mechanism | Pushes text? | When | Source |
|---|---|---|---|
| SWML `live_transcribe` `start.webhook` | Yes, live | "When `live_events` is enabled, partial results are sent as they occur. When `ai_summary` is enabled, a summary is sent when the session ends." | Docs: swml/reference/calling/live-transcribe (Actions) |
| REST `calling.live_transcribe` | Yes, live (same action object) | mid-call by call_id | SDK: rest/namespaces/calling_resources_generated.py `live_transcribe`; Docs: server-sdks/reference/python/rest/calling/live-transcribe |
| `ai_sidecar` `url` | Yes ("Webhook URL for transcribe events AND sidecar events") | live, both legs | SDK: schema.json `AiSidecar.url` |
| SWML/REST `transcribe` `status_url` | Yes, but only at end of call: `calling.transcript.completed` with `text`, or `calling.transcript.failed` | after call | Docs: swml/reference/calling/transcribe (StatusCallbacks) |
| `tap` | No, raw audio (RTP/WS, PCMU/PCMA) | live | SDK: schema.json `$defs.Tap` |
| REST `stream` | No, raw audio over WebSocket | live | SDK: calling_resources_generated.py `stream` |
| `record` / `record_call` | No transcription params in schema | n/a | SDK: schema.json `$defs.Record`, `RecordCall` |

Answer to the key question: **`live_transcribe` with `webhook` + `live_events: true` is the only
documented mechanism that pushes live transcript text to a plain URL** (outside of `ai_sidecar`).

### SWML `live_transcribe` params (SDK: schema.json `$defs.TranscribeStartAction`, `TranscribeAction`, `TranscribeSummarizeAction`)

`live_transcribe.action` is one of:
- `{start: {...}}`. Required: `lang`, `direction`. Optional: `webhook`, `live_events`, `ai_summary`,
  `ai_summary_prompt`, `speech_timeout` (default 60000, docs say min 1500), `vad_silence_ms`,
  `vad_thresh` (0-1800), `debug_level`, `speech_engine` (`deepgram` | `google`, default `deepgram`).
  `direction` is an array of `remote-caller` / `local-caller`.
- `"stop"` (string).
- `"summarize"` (string) or `{summarize: {webhook, prompt}}`.

Webhook auth: "Authentication can also be set in the URL in the format of `username:password@url`"
(Docs: swml/reference/calling/live-transcribe).

```yaml
# Docs example (swml/reference/calling/live-transcribe), lang changed to en-US
version: 1.0.0
sections:
  main:
    - answer: {}
    - live_transcribe:
        action:
          start:
            webhook: "https://PUBLIC_URL/transcript"
            lang: en-US
            live_events: true
            direction: [remote-caller, local-caller]
            speech_engine: deepgram
```

Python, SWML builder (validated offline with `SWMLService.add_verb`, returns True):

```python
from signalwire.core.swml_service import SWMLService
svc = SWMLService(name="meeting-line", route="/meeting")
svc.add_verb("answer", {})
svc.add_verb("live_transcribe", {"action": {"start": {
    "lang": "en-US", "direction": ["remote-caller", "local-caller"],
    "webhook": f"{PUBLIC_URL}/transcript", "live_events": True}}})
```

Python, REST mid-call (Docs: server-sdks/reference/python/rest/calling/live-transcribe):

```python
client.calling.live_transcribe(call_id=call_id, action={"start": {
    "lang": "en-US", "direction": ["local-caller", "remote-caller"],
    "webhook": f"{PUBLIC_URL}/transcript", "live_events": True}})
client.calling.live_transcribe(call_id=call_id, action="stop")
```

REST signature: `live_transcribe(call_id, *, action, extras=None, request_options=None)`, posts
`{"command": "calling.live_transcribe", "params": {"action": ...}, "id": call_id}`
(SDK: rest/namespaces/calling_resources_generated.py).

### Caveats

- **Payload schema undocumented.** No source read gives the JSON body POSTed to `webhook`: no field
  names for text, speaker/leg, partial vs final flag, timestamps. Docs only say "partial results are
  sent as they occur". The consumer must log raw bodies and parse defensively.
- RELAY docs disagree with SWML/REST on the action shape: RELAY `live_transcribe` documents
  `action.action` (`"start"`/`"stop"`), `action.language`, `action.status_url`
  (Docs: server-sdks/reference/python/relay/call/live-transcribe). SWML schema uses `start.lang` /
  `start.webhook`. Use the SWML/REST shape; do not use the RELAY shape.
- Only one transcriber per call: "`ai_sidecar` and plain `live_transcribe` cannot run on the same
  call at the same time" (Docs: swml/reference/calling/ai-sidecar, Limitations).
- **Conference / per-participant: undocumented.** No source documents `live_transcribe` on a
  conference object, nor how `direction` behaves on a leg that is inside `join_conference`.
  Inference only (untested): each dial-in leg runs its own SWML, so a `live_transcribe` placed
  before `join_conference` on each leg would be per-participant.

### Builder B10: build now vs TODO

Build now:
- #21: dial-in SWML = `answer`, `live_transcribe` start (webhook to FastAPI `/transcript`),
  `join_conference`. FastAPI consumer stores raw JSON per call_id.
- #22: SSE endpoint fan-out from the consumer store (pure app code).
- #26: rule engine over whatever text field arrives; keep the field extractor in one function.
- Post-call fallback: `transcribe` via REST `client.calling.transcribe(call_id, status_url=...)`,
  which has a documented completion event with `text`.

TODO:
- `TODO(blocked: live_transcribe webhook payload schema undocumented; capture a real body before hard-coding fields)`
- `TODO(blocked: live_transcribe behavior inside join_conference / per-participant undocumented)`
- `TODO(blocked: partial vs final distinction in live_events payload undocumented)`

---

## (b) AI sidecar / copilot

**Documented today: yes.** SWML `ai_sidecar` has a full reference page with params, callbacks,
response format, stop reasons and limitations (Docs: swml/reference/calling/ai-sidecar,
.../ai-sidecar/params, .../ai-sidecar/prompt). The platform record-calls guide lists it as
"Advice for a human agent mid-call | `ai_sidecar` | An AI observer on a human-to-human call,
streaming events to your application without speaking" (Docs: platform/voice/record-calls).

Status: no source states GA/beta. Strategy docs still call the drop-in script-tag product
roadmap ("AI sidecar productization. Drop-in script tag for any existing contact center UI",
`mary` L482). Canonical terms: "Live copilots (sidecar) ride a live human conversation,
listening and executing scoped tools in real time" (`signalwire_canonical_terms` L21). The verb
itself is shipped in docs and in SDK schema since 3.4.0 (SDK: _docs/CHANGELOG.md).

### Verb params (SDK: schema.json `$defs.AiSidecar`; required `prompt`, `lang`; `additionalProperties: false`)

`prompt` (string, POM object, or `{file}`), `lang` (BCP-47, required), `model`, `direction`
(array, `minItems: 2`, "Both legs are required for sidecar mode"), `customer_role`
(`remote-caller` | `local-caller`, "turn-end trigger source"), `url` ("Webhook URL for transcribe
events AND sidecar events"), `SWAIG` (uppercase), `permissions`, `global_data`, `hints`, `params`
(pass-through tunables, e.g. `idle_timeout_ms`, `ai_summary`, `debug`, `debug_level`), `action`
("Reserved for future runtime sub-actions").

### How it works (Docs: swml/reference/calling/ai-sidecar, How it works)

Listens, never speaks. On each customer turn end (a "tick") it sends the running transcript plus
prompt and SWAIG tools to the model, which returns one `insight` line or calls built-in
`sidecar_skip`. Tools run through your SWAIG `web_hook_url`. Every step is a callback to `url`.

Callback body (Docs, Callback body shape): `{"call_info": {project_id, space_id, call_id,
content_type, content_disposition, conversation_type}, "sidecar_event": {"type", "ts"
(microseconds), "tick_id", "channel_data", ...}}`. Event types seen in docs: `insight` (with
`raw`, `iter`, `total_iters`), `say` (reported, not spoken), `error` (`error_reason: tool_loop`),
`final` (with `stop_reason`: `transcribe_close`, `transferred`, `hung_up`, `stop_action`,
`api_stop`). Full per-type list: Docs apis/rest/webhooks/ai-sidecar-callback (not read here).

Tool webhook response (Docs, Response): `{"response": "...", "action": [...]}`; actions such as
`user_event`, `set_global_data` take effect on the call only when `act_on_channel` is true.

Example (Docs: swml/reference/calling/ai-sidecar, Example, plus `direction` from the SDK example):

```yaml
version: 1.0.0
sections:
  main:
    - answer: {}
    - ai_sidecar:
        prompt: "You are a real-time sales copilot. After each customer turn, give the agent one concise piece of advice or call sidecar_skip if no advice is needed."
        lang: en-US
        direction: [remote-caller, local-caller]
        url: "https://PUBLIC_URL/sidecar/events"
        SWAIG:
          defaults: { web_hook_url: "https://PUBLIC_URL/sidecar/swaig" }
    - connect: { from: "+15555550100", to: "+15555550199", answer_on_bridge: true }
    - hangup: {}
```

Python host: SDK _docs/examples/swmlservice_ai_sidecar.py (`SWMLService` + `add_verb_to_section(
"main", "ai_sidecar", {...})` + `define_tool(...)` + `register_routing_callback(cb, path="/events")`).
The docs say the host is `SWMLService`, not `AgentBase`, because the sidecar does not own the call.

### Caveats

- **SDK example vs docs disagree on event shape.** The SDK example reads `body.get("type")` at top
  level; docs say the event is nested under `sidecar_event` ("unwrap that in your code before
  reading `type`"). Follow the docs: `body["sidecar_event"]["type"]`.
- The docs' own example omits `direction` while Limitations says a single-leg `direction` is
  rejected and the schema requires 2 items if present. Always send both legs.
- One transcriber per call (no `live_transcribe` alongside). Turn detection tuned for Deepgram.
  `sidecar_skip` is reserved. Tool loops capped (Docs, Limitations).
- No REST/RELAY command to attach a sidecar to an already-running call was found in the SDK
  (`grep sidecar` over rest/ finds nothing). Attach it in the SWML before `connect`.

### What the copilot recipes need, and what exists

| Need | Mechanism | Documented? |
|---|---|---|
| Listen to both legs without joining | `ai_sidecar` before `connect` | Yes |
| Scoped tools mid-call | `ai_sidecar.SWAIG` functions | Yes |
| Push cards to the rep | Your app: sidecar callbacks (`insight`, tool events) -> your SSE/WebSocket rep UI | Callbacks yes; rep UI is app code |
| Raw audio + own classifier (alternative) | `tap` (`uri`, `direction` both) or REST `stream` | Yes, audio only |
| `rpc_ai_message` "whisper" | `FunctionResult.rpc_ai_message(call_id, message_text=None, role="system", global_data=None)` emits `execute_rpc` method `ai_message` (SDK: core/function_result.py) | Yes, but targets "an AI agent on another call" |
| REST equivalent | `client.calling.ai_message(call_id, *, role, message_text, reset, global_data)` | Yes |

Key caveat for #24: `ai_message` injects into an **AI agent's** conversation (docstring: "Send a
message and/or global_data to an AI agent on another call"). It does not speak to a human rep
and is not documented as targeting an `ai_sidecar`. A whisper to a human needs the rep UI (card)
or a separate audio mechanism; neither "whisper audio to one leg" nor "ai_message into a sidecar"
was found documented.

### Builder B11: build now vs TODO

Build now: #23 and #24 on `ai_sidecar` + `SWMLService` + an `/events` consumer that unwraps
`sidecar_event` and pushes `insight` cards over SSE to a rep page; scoped tools via `define_tool`.
TODO:
- `TODO(blocked: full per-type ai_sidecar callback field list lives at docs apis/rest/webhooks/ai-sidecar-callback, not verified here)`
- `TODO(blocked: no documented way to whisper audio to the human rep; rpc_ai_message targets AI agents only)`
- `TODO(blocked: no documented REST/RELAY command to start ai_sidecar on an in-progress call)`

---

## (c) Chat / SMS mode for AI agents

**Documented today: yes.** Docs: platform/ai/chat ("Chat with an AI agent"), platform/ai ("One
agent across voice and text"), REST spec `POST /api/ai/chat`, SDK reference
server-sdks/reference/python/agents/ai-chat-client/*, SDK _docs/docs/ai_chat_gateway.md.

### Endpoint, protocol, auth (SDK: ai_chat/client.py module docstring and `_request`)

- `POST https://{space}.signalwire.com/api/ai/chat`, HTTP Basic `project:api_token`, JSON-RPC 2.0
  body `{"jsonrpc","method","params","id"}`. Token needs the _Chat_ scope (REST spec).
- URL resolution: `url=` arg, then `RAILS_DEV_MODE` env, then built from `space` /
  `SIGNALWIRE_SPACE`. Creds from args or `SIGNALWIRE_PROJECT_ID` / `SIGNALWIRE_API_TOKEN`.
- Errors arrive as HTTP 200 with `{"error": {...}}`; gate on the body, not the status.
- Methods and SDK wrappers: `create_conversation(conversation_id, config_url, user_message=None,
  timeout=None, user_metadata=None, reinit=False)`, `chat(conversation_id, message, role="user",
  config_url=None, user_metadata=None, timeout=None, reinit=False) -> ChatResponse(text,
  conversation_id, user_event)`, `end` (RPC `end_conversation`), `delete`, `log` (RPC `chat_log`),
  `summarize(conversation_id, summary_prompt=None)`.

### Same agent?

Yes. `config_url` is the URL of the agent's SWML; "The same resource also answers voice calls"
(Docs: platform/ai/chat). The config fetch carries `conversation_type: "chat"`,
`conversation_id`, `call_id`, `params.user_meta_data` (SDK: ai_chat_gateway.md). Tool webhooks and
post-prompt get `conversation_type: chat`; SDK 3.7.4 fixed post-prompt token checks for chat
(SDK: _docs/CHANGELOG.md). Voice-only settings do not apply to text (Docs: platform/ai).

A turn: one `chat` request = one user message + agent reply including tool calls; expect seconds
(SDK: client.py `chat` docstring). Conversation ids are sanitized to `[a-zA-Z0-9_\-.:]`; use `.`
to compose ids (SDK: client.py `_warn_if_id_will_be_altered`).

### SMS inbound driving it (#27), documented

Docs: platform/ai/chat, "Hold an AI chat conversation over SMS text messages":

```python
from fastapi import FastAPI, Request
from signalwire.ai_chat import AIChatClient
client = AIChatClient()  # env creds
app = FastAPI()

@app.post("/sms")
async def sms(request: Request):
    message = (await request.json())["message"]
    if not message.get("body"):
        return {"version": "1.0.0", "sections": {"main": [{"reply": "Please send your question as text."}]}}
    conversation_id = "sms." + message["from"].lstrip("+")
    reply = await client.chat(conversation_id, message["body"], config_url=CONFIG_URL)
    return {"version": "1.0.0", "sections": {"main": [{"reply": reply.text}]}}
```

Route the number's inbound messaging to a SWML Webhook resource (`used_for: messaging`, number
`handler: messaging`). Docs warn: verify the webhook signature, since anyone reaching `/sms` runs
billed turns.

Wiring caveat (lead, wave 0): in SDK 3.7.5, `fabric.swml_webhooks.create(used_for=...)` is typed
`Literal['calling']` only, and `phone_numbers.update(message_handler=...)` has no SWML option (only
`relay_context`, `relay_topic`, `relay_application`, `laml_webhooks`, `laml_application`). So binding a
number's messaging to a SWML webhook from the SDK is unverified. Build and test the `/sms` handler
against fixtures, and ask the lead to wire the number and confirm on a live SMS. See
`docs/sdk-notes.md` (REST client).

### Website chat (#28)

`ChatGateway(config_url=..., key="pk_...", allowed_origins=[...])` then
`app.include_router(gateway.router(), prefix="/chat")`. Browser posts `{"message"}` with
`Authorization: Bearer <publishable key>`; handle returned in `X-Chat-Handle`; methods `start`,
`chat`, `log`, `end`; caps `max_new_conversations=60/min`, `max_turns=200`; set `secret=` for
multi-replica (SDK: _docs/docs/ai_chat_gateway.md). `HandoffRouter` adds `/handoff`, `/escalate`,
`/say` for voice/text switching used by `@signalwire/address-widget` (SDK: ai_chat/handoff.py).

### Caveats

- Rate limits and nonce registry are per-process (SDK: ai_chat_gateway.md, handoff.py).
- `chat_log` includes system prompt and tool traffic; filter before showing users (Docs: platform/ai/chat).
- Messaging SWML `reply` is not in the SDK 3.7.5 calling schema; return the dict directly as in the docs.

### Builder B12

Build now: #27 (FastAPI `/sms` + `AIChatClient.chat` keyed by sender), #28 (`ChatGateway` mounted on
the agent app). #29 needs no chat mode: `FunctionResult.send_sms(to_number, from_number, body, ...)`
on the voice agent plus an ordinary inbound SMS webhook (Docs: server-sdks/guides/result-actions).
No blocked items found.

---

## (d) SWML `pay` payment-connector contract

**Documented today: yes** (Docs: swml/reference/calling/pay; cXML twin at
compatibility-api/cxml/reference/voice/pay).

### Verb params (SDK: schema.json `$defs.Pay`; only `payment_connector_url` required)

`payment_connector_url`, `charge_amount` (string float, no currency prefix), `currency` (default
`usd`), `description`, `input` (const `dtmf`), `language` (default `en-US`), `max_attempts`
(default 1), `min_postal_code_length` (default 0), `parameters` (array of `{name, value}`),
`payment_method` (const `credit-card`), `postal_code` (bool or the actual code; default true),
`prompts` (array of `{for, actions[{type: Say|Play, phrase}], attempts, card_type, error_type}`),
`security_code` (default true), `status_url`, `timeout`, `token_type` (`one-time` | `reusable`,
default `reusable`), `valid_card_types` (space-separated), `voice`.
Caller can press `#` to submit an entry, `*` to cancel (Docs, `pay.input`).

### Request SignalWire POSTs to `payment_connector_url` (Docs: swml/reference/calling/pay, Request example)

```json
{"transaction_id": "8c9d14d5-52ae-4e2e-b880-a14e6e1cda7d", "method": "credit-card",
 "cardnumber": "************1234", "cvv": "***", "postal_code": "123456",
 "description": "Payment description", "chargeAmount": "10.55", "token_type": "reusable",
 "expiry_month": "12", "expiry_year": "99", "currency_code": "usd"}
```

The cXML page also lists `parameters` (object, custom key-value) in the connector body; the SWML
example omits it. Note mixed casing: `chargeAmount` vs `currency_code`.

### Response the connector must return (Docs: swml/reference/calling/pay, Response format)

- Charge success: HTTP 200 `{"charge_id": "ch_123456789", "error_code": null, "error_message": null}`
- Tokenize success: HTTP 200 `{"token_id": "tok_test_token", "error_code": null, "error_message": null}`
- Failure: non-200 `{"charge_id": null, "error_code": "insufficient_funds", "error_message": "Card has insufficient funds"}` (or `token_id: null`). Errors trigger the `payment-failed` prompt.
- Tokenization is `charge_amount: 0` (Docs, `pay_payment_results.payment_token`).

### `status_url` callback (Docs: swml/reference/calling/pay, Request format)

```json
{"event_type": "calling.call.pay", "event_channel": "swml:...", "timestamp": 1743707517.12267,
 "project_id": "...", "space_id": "...",
 "params": {"status_url": "...", "status_url_method": "POST", "for": "payment-completed",
  "error_type": "", "payment_method": "credit-card", "payment_card_number": "************1234",
  "payment_card_type": "visa", "security_code": "***", "expiration_date": "1225",
  "payment_card_postal_code": "23112", "control_id": "...", "call_id": "...", "node_id": "..."}}
```

### Variables after `pay` (Docs: swml/reference/calling/pay, Variables)

`pay_result`: `success`, `too-many-failed-attempts`, `payment-connector-error`,
`caller-interrupted-with-star`, `relay-pay-stop`, `caller-hung-up`, `validation-error`,
`internal-error`. `pay_payment_results.{payment_token, payment_confirmation_code,
payment_card_number, payment_card_type, payment_card_expiration_date, payment_card_security_code,
payment_card_postal_code, payment_error, payment_error_code, connector_error.{code,message}}`.

### SDK `FunctionResult.pay` (SDK: core/function_result.py)

```
pay(payment_connector_url, input_method="dtmf", status_url=None, payment_method="credit-card",
    timeout=5, max_attempts=1, security_code=True, postal_code=True, min_postal_code_length=0,
    token_type="reusable", charge_amount=None, currency="usd", language="en-US", voice="woman",
    description=None, valid_card_types="visa mastercard amex", parameters=None, prompts=None,
    ai_response="The payment status is ${pay_result}, do not mention anything else about collecting payment if successful.")
```

It emits an `execute_swml` action whose `main` is `[{set: {ai_response: <template>}}, {pay: {...}}]`
(verified offline). So `ai_response` is a SWML variable set right before `pay`; `${pay_result}`
expands into what the agent is told afterwards. Docs say "Set to `None` to disable"
(server-sdks/reference/python/agents/function-result/pay), but the 3.7.5 code always emits the
`set`, so `None` yields `{set: {ai_response: null}}`. Do not rely on `None` to suppress it.

```python
@agent.tool(name="pay_bill", description="Take a card payment for the bill")
def pay_bill(args, raw_data):
    return FunctionResult("I'll take your card details on the keypad now.").pay(
        payment_connector_url=f"{PUBLIC_URL}/pay",
        status_url=f"{PUBLIC_URL}/pay/status",
        charge_amount=amount_str, max_attempts=3,
        parameters=[{"name": "account_id", "value": acct}])
```

Mock connector minimum: `POST /pay` reads `transaction_id`, `chargeAmount`, `parameters`; returns
200 `{"charge_id": "ch_<id>", "error_code": null, "error_message": null}`, or a non-200 with
`charge_id: null` to exercise `payment-failed`.

### Caveats

- **Type mismatch, verified offline.** `FunctionResult.pay` sends `timeout`, `max_attempts`,
  `min_postal_code_length`, `security_code`, `postal_code` as strings ("the platform's pay verb
  requires security_code and postal_code to be strings", SDK docstring), but
  `SWMLService.add_verb("pay", {... "security_code": "true"})` fails schema validation; booleans
  pass. Use `FunctionResult.pay` from an AI tool; if hand-building SWML, follow the SDK's strings
  and skip `add_verb` validation.
- Python SDK docstring says `input_method` only accepts `"dtmf"`; Ruby/Go/TS docs still show
  `"voice"`/`"speech"`. Use `dtmf`.
- Space enablement: no source read says `pay` must be enabled on the Space or requires a support
  request. Treat as unknown.

### Builder B6

Build now: #10 tool calling `FunctionResult.pay`, mock `/pay` connector, `/pay/status` logger,
agent step that branches on `${pay_result}`.
TODO: `TODO(blocked: unknown whether pay must be enabled per Space; confirm before live test)`.

---

## Sources

SignalWire docs (via SignalWire MCP `search`):
- swml/reference/calling/live-transcribe (Actions, Examples)
- swml/reference/calling/transcribe (StatusCallbacks)
- swml/reference/calling/ai-sidecar (How it works, Example, Callback body shape, Response, Stop reasons, Limitations, Supported SWAIG actions); .../ai-sidecar/params; .../ai-sidecar/prompt
- swml/reference/calling/pay (Properties, Request example, Response format, Request format for status_url, Variables)
- compatibility-api/cxml/reference/voice/pay (paymentConnectorUrl request parameters)
- platform/ai/chat; platform/ai; platform/voice/record-calls; platform/voice/call-streaming
- REST spec `POST /api/ai/chat` (api_spec_signalwire_rest.json)
- server-sdks/reference/python/rest/calling/live-transcribe; .../rest/calling/transcribe
- server-sdks/reference/python/relay/call/live-transcribe; .../relay/call/transcribe
- server-sdks/reference/python/agents/function-result/pay; .../ai-chat-client/chat
- server-sdks/reference/python/agents/swml-service/register-routing-callback
- server-sdks/guides/result-actions

Strategy docs (MCP `get_doc_section` / `search_docs`): `introducing_pgi1` ("Calls that reach the
right person"), `mary` (L210-211, L482-483 roadmap), `signalwire_canonical_terms` (L21).

SDK 3.7.5 files (site-packages/signalwire/):
- schema.json (`$defs`: LiveTranscribe, TranscribeStartAction, TranscribeAction, TranscribeSummarizeAction, TranscribeDirection, SpeechEngine, AiSidecar, Tap, StopTap, Record, RecordCall, Pay, PayParameters, PayPrompts, PayPromptSayAction, PayPromptPlayAction, SWMLMethod)
- core/swml_verbs_generated.py (`AiSidecarConfig`, `live_transcribe`, `ai_sidecar`, `tap`, `pay` builders)
- core/swml_service.py (`add_verb` validation)
- core/function_result.py (`pay`, `tap`, `rpc_ai_message`, `rpc_ai_global_data`, `rpc_ai_unhold`)
- rest/namespaces/calling_resources_generated.py (`ai_hold`, `ai_unhold`, `ai_message`, `live_transcribe`, `live_translate`, `tap`, `tap_stop`, `stream`, `stream_stop`, `transcribe`, `transcribe_stop`)
- rest/namespaces/calling_types_generated.py (`CallAIMessageResetParams`, `LiveTranscribe*Action`)
- ai_chat/__init__.py, ai_chat/client.py, ai_chat/gateway.py (via docs), ai_chat/handoff.py
- _docs/docs/ai_chat_gateway.md, _docs/CHANGELOG.md (3.4.0, 3.4.3, 3.7.4), _docs/examples/swmlservice_ai_sidecar.py, _docs/examples/tap_example.py
