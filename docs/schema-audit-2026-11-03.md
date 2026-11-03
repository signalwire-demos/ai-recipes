# SWAIG tool-schema audit, 2026-11-03

Scope: every recipe under `recipes/` (01 through 36 and `_template`). Trigger: on a live call to
recipe 01 (call `d68bc7a9-879e-437b-8da8-efb4ce916582`) the agent never asked for the reservation
date and booked today's date, which the dynamic-config callback had put in `global_data`. The
`date` parameter was described only as "Date as YYYY-MM-DD" and the step said "Collect ... date".

## What "proper schema" means on this platform

A SWAIG function's `parameters` is the same JSON Schema that OpenAI-style tool calling uses,
wrapped by the SDK (`define_tool`, `@AgentBase.tool`, DataMap `.parameter()` all land there).
The platform's SWML schema (`signalwire/schema.json` in signalwire-sdk 3.7.5, `$defs
FunctionParameters` and the per-type `*Property` defs) is strict per property
(`unevaluatedProperties: {not: {}}`). Verified allowed keys:

| type | allowed keys |
|---|---|
| string | type, description, nullable, enum, default, pattern, format |
| integer, number | type, description, nullable, enum, default |
| boolean | type, description, nullable, default |
| array | type, description, nullable, default, items (required) |
| object | type, description, nullable, default, properties, required |

`format` is one of `date_time`, `time`, `date`, `duration`, `email`, `hostname`, `ipv4`, `ipv6`,
`uri`, `uuid`. `minimum`, `maximum`, `minLength`, `maxLength`, `examples`, `title` and
`additionalProperties` are violations. Runtime argument validation in the SDK is soft (warn and
proceed), so handlers must still validate. The SDK guide's canonical parameter description ends
with "Ask if not provided."

Checks applied by 15 read-only audit agents, one block of recipes each, after dumping each
recipe's SWML with `swaig-test --dump-swml --raw` and running `scripts/validate_swml.py` on it:

- E1 schema violation; E2 schema/handler type or required mismatch (ERROR)
- W1 description missing, shapeless, or silent about asking; W2 fixed-shape value with no
  format/pattern/enum; W3 arrays without items (WARN)
- P1 step/prompt text that lets the model fill in a caller-supplied value; P2 step and tool
  description disagree (WARN)

## Already fixed: 01-restaurant-reservation-line

`book_table` now carries `format: date` on `date`, patterns on `time` (HH:MM) and `phone`, and
every description ends in "Ask if not provided" (the date one says "never assume today"). The
`take_booking` step says "Ask for, one at a time ... Never fill in a value the caller did not
give, and never assume the date is today." A governance test pins this. 21 tests pass and the
dump validates against the platform schema. Server restarted; re-test by calling +1 918 395 1340.

## Results at a glance

37 recipes audited (36 plus `_template`). Every SWML dump that could be produced validates
against the platform schema at the function-parameter level: no recipe ships an unsupported
keyword. The problems are one level up: handlers that do not enforce `required`, caller-supplied
values with no `format`, `pattern` or `enum`, and descriptions and step texts that never tell
the model to ask, so it fills values in (the recipe-01 date trap, found in 14 more recipes).

| Severity | Count | Meaning |
|---|---|---|
| ERROR | 11 (7 in recipe code, 4 SDK-owned*) | schema/handler mismatch, or a schema violation |
| WARN | 102 | shapeless or ask-less parameter, missing enum/format/pattern, step text that lets the model assume |
| INFO | 24 | style, or SDK schema lag that only affects `scripts/validate_swml.py` |

| # | Recipe | dump / validate | E | W | I | Headline |
|---|---|---|---|---|---|---|
| 02 | product-docs-hotline | ok / ok | 1* | 1 | 1 | SDK skill `search_docs` has no `required: ["query"]` though its handler needs one |
| 03 | front-desk-receptionist | ok / 1 (SDK ctx shapes) | 0 | 6 | 0 | plan/service need enums, invoice needs a pattern, refund-confirm rule lives only in the tool description |
| 04 | hiring-phone-screen | ok / 1 (gather_info) | 0 | 1 | 0 | gather `earliest_start` has no date shape (live test stored "Monday, November 9") |
| 05 | package-tracking-line | ok / ok | 0 | 2 | 0 | `tracking_number` no pattern, no ask |
| 06 | movie-showtimes (SWML) | n/a / ok | 0 | 1 | 0 | prompt must say the listing is today-only |
| 07 | trivia-hotline | ok / ok | 0 | 1 | 0 | `answer` description should forbid supplying one |
| 08 | bank-balance-line | ok / ok | 0 | 6 | 0 | `date_of_birth` free-form with no format; a parse miss counts as a failed verification |
| 09 | insurance-claim-intake | ok / 1 (gather_info) | 0 | 1 | 1 | `preferred_time` is example-only |
| 10 | utility-bill-payment | ok / ok | 0 | 2 | 0 | ZIP/account no pattern; ZIP matched stricter than described |
| 11 | collections-agent | ok / ok | 0 | 5 | 2 | model can compute `months` from the balance it is shown; `escalate.reason` undescribed |
| 12 | medical-appointment-line | ok / ok | 0 | 3 | 1 | `day` needs a weekday enum, `slot_id` a pattern; `schedule_limited` never asks |
| 13 | lead-qualification-line | ok / 1 (prompt.model) | 1* | 4 | 0 | every description and the step let the model infer values (seen on live call 44f199dd) |
| 14 | appointment-reminder-caller | ok / ok | 0 | 2 | 0 | `new_start`: date trap, no pattern, no `local_tz` |
| 15 | support-line-with-callback | ok / ok | 1 | 1 | 0 | `summary` required but unchecked |
| 16 | travel-concierge | ok / booking 1 (prompt.model) | 1 | 4 | 1 | `travelers` `int()` crash on "two"; destination/month need enums; handoff never asks |
| 17 | customer-survey-caller | ok / ok | 2 | 2 | 0 | `log_response` has no `required` list; prefab `validate_response` still `int()`-parses ratings |
| 18 | drive-thru-order-taker | ok / ok | 0 | 7 | 0 | menu choices need enums from menu.json; size/side/drink get assumed |
| 19 | answering-service | ok / ok | 0 | 3 | 1 | `callback_number` unvalidated ("555-0142 ext 3" texted verbatim); `message` must be verbatim |
| 20 | absence-reporting | ok / 1 (prompt.model) | 1* | 3 | 2 | `org_type` enum; `id` shape; model may ISO-normalize dates the handler cannot parse |
| 21 | meeting-transcription-line | ok / ok | 0 | 0 | 0 | no SWAIG functions |
| 22 | live-caption-display | ok / ok | 0 | 0 | 0 | no SWAIG functions |
| 23 | sales-call-copilot | ok / ok | 0 | 0 | 1 | clean |
| 24 | support-copilot-that-acts | ok / ok | 1 | 2 | 1 | `reason` required but unchecked; the silent sidecar can invent a credit amount |
| 25 | win-loss-analyzer | ok / ok | 0 | 1 | 0 | post_prompt "use null or []" contradicts the extraction schema |
| 26 | compliance-call-monitor | failed (httpx) / ok | 0 | 0 | 0 | no SWAIG functions |
| 27 | sms-concierge | ok / ok | 0 | 5 | 1 | `amenity` needs an enum; wake-up time never asked; `room` pattern |
| 28 | website-chat-agent | ok / ok | 0 | 5 | 1 | same `concierge.py` as 27; fix once |
| 29 | appointment-confirmation-sms | ok / booking 1 (initial_step) | 1 | 5 | 1 | `name` required but unchecked (blank booking texted); slot date/time no format/pattern; reschedule can hand back the current slot |
| 30 | calendar-assistant-over-mcp | ok / 1 (mcp_servers) | 0 | 6 | 2 | `get_today` plus "find slots for the date" is the date trap; MCP server descriptions are bare shapes |
| 31 | give-claude-a-phone-number | ok / ok | 0 | 4 | 2 | `book_callback.when` date trap, 24-hour unstated; `phone` no pattern |
| 32 | order-status-line | ok / ok | 0 | 4 | 1 | refund `reason` never asked; ZIP/order patterns |
| 33 | agency-answering-service | ok / ok (4 tenants) | 2 | 8 | 2 | no handler enforces `required` (blank rows, callback promised); `emergency` defaults unsafe; no descriptions |
| 34 | stock-quote-line | ok / ok | 0 | 3 | 1 | stock-plan line is never told its only ticker; enum from watchlist |
| 35 | bilingual-support-line | ok / 1 (internal_fillers) | 0 | 2 | 1 | account/ZIP patterns and ask |
| 36 | voice-latency-lab | ok / 1 (prompt.model) | 0 | 2 | 1 | `day` enum; step never asks for the day |
| — | _template | ok / ok | 0 | 1 | 0 | `day`: no enum, no ask; this is the seed every clone inherits |

`*` SDK-owned: the error is in signalwire-sdk 3.7.5 (a skill, a prefab, or where
`set_prompt_llm_params(model=...)` places the key), not in recipe code.

## Cross-cutting patterns

1. **`required` is a promise the handler must keep.** SDK argument validation is soft, so a
   parameter in `required` that the handler reads with `args.get(k, "")` is optional in practice.
   Seven handlers save blank records or take the wrong branch: 15 `summary`, 17 `log_response`
   (no `required` list at all), 24 `reason`, 29 `name`, 33 every tool plus the `emergency`
   boolean (a missing value opens a routine ticket for a gas smell), and 16 `travelers`
   (`int("two")` raises and the SWAIG call fails). Fix pattern: check each required field at the
   top of the handler and return a `FunctionResult` that tells the model what to ask for.
2. **The date trap is everywhere a caller-supplied value has a plausible default.** 14 recipes
   let the model fill in a value the caller never gave: today's date (08, 14, 29, 30, 31, 36,
   _template), the current month or one traveler (16), a size or combo side (18), a computed
   `months` (11), a budget or timeline (13), a wake-up time (27/28), a credit amount (24), the
   caller ID as the callback number (19, 31, 33). Fix pattern, from the SDK guide: end every
   caller-supplied parameter's description with "Ask if not provided" (and "never assume today"
   for dates), and make the step text say "Ask for, one at a time: ..." rather than "collect".
3. **Fixed sets should be enums built from config or data.** 03 plan/service, 12 day, 13 need
   (already), 16 destination/month, 17 question_id, 18 item/size/side/drink/modifiers, 20
   org_type, 27/28 amenity, 33 day/practice_area, 34 ticker watchlist, 36 and _template day.
   Build the list from the same source the handler checks so code and schema cannot drift.
4. **Fixed shapes should carry `format` or `pattern`.** Dates: `format: date` (08 dob, 29,
   30). `YYYY-MM-DD HH:MM` values: a pattern, not `format: date_time` (14, 30, 31). HH:MM: a
   pattern, not `format: time` (29). Phone numbers (19, 31, 33), ZIPs (10, 11, 32, 35), IDs with a
   known shape (03 invoice, 08 transaction, 12 slot, 20 id, 30 meeting, 32 order, 35 account, 05
   tracking): a pattern. The one deliberate exception is 20, whose handler parses spoken dates;
   there the description must forbid normalizing to ISO.
5. **Six validator failures are schema.json lag, not recipe defects.** `ai.prompt.model`
   (13, 16 booking, 20, 36: the SDK writes it there, the SWML reference documents it, and
   `docs/sdk-notes.md` records it working live), `gather_info` (04, 09), context `enter_fillers`
   as a language map and context-level `valid_contexts`/`pom` (03), `initial_step` (29),
   `SWAIG.mcp_servers` (30), and multi-language `internal_fillers` (35). Decide once: either
   switch the model key to `set_params({"ai_model": ...})`, which validates, and re-verify live, or
   teach `scripts/validate_swml.py` to ignore these known gaps and report them upstream.

## Suggested fix order

1. The seven handler-side `required` bugs (15, 16, 17, 24, 29, 33): blank records, a crash, and
   an unsafe emergency default. Small, mechanical, each with a test.
2. `_template`, so every future clone starts right, then the date-trap group (pattern 2).
3. Enums and patterns (patterns 3 and 4), one recipe per PR per the contributing rules.
4. The schema-lag decision (pattern 5) and the SDK-owned items in 02 and 17, reported upstream.

## Per-recipe findings

## 02-product-docs-hotline
dump: ok ; validate_swml: ok
tools: search_docs* (schema built by the `native_vector_search` skill, `skill.py:576`; recipe sets only `tool_name` and `description`)
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| ERROR | search_docs* | query | E2 | Handler rejects an empty query (`_search_handler`: "Please provide a search query.") but the skill's `define_tool` passes a bare properties map, so the dumped schema has no `required` list at all. SDK-owned; not settable through `add_skill` params. | In `skill.py` `define_tool(parameters=...)`: `{"type":"object","properties":{"query":{...},"count":{...}},"required":["query"]}` |
| INFO | search_docs* | count | W1 | `count` is model-settable (`count = args.get("count", self.count)`), so `config.SEARCH_COUNT` is only a default; the gate still applies but README says it is "chunks returned per search". | In `grounded_only`: `kept = [...][:config.SEARCH_COUNT]` |
verdict: Clean recipe-side; the only error is the SDK skill omitting `required: ["query"]` while its handler requires it.

## 03-front-desk-receptionist
dump: ok ; validate_swml: 1 error (top-level `ai.prompt` oneOf; leaf causes are SDK-emitted context shapes the bundled `schema.json` lags on: `contexts.*.enter_fillers` emitted as `{"en-US":[...]}` where the schema wants an array, and context-level `valid_contexts`/`pom` unevaluated by `ContextsPOMObject`; platform accepted them on the live call. All five `functions[].parameters` validate clean in isolation against `$defs/FunctionParameters`)
tools: check_service_status, get_invoice, get_plan_price, issue_refund, open_ticket (plus platform `change_context` via `valid_contexts`, not in `SWAIG.functions`)
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | issue_refund | billing step + Role text | P2 | Tool says "Only call after the caller confirms" but the billing Role ("Look up invoices with get_invoice and refund them with issue_refund. Ask for the invoice number.") and step text never say to look up first, read the amount back, or get a yes. Nothing stops `issue_refund` being the first call. | `config.py` billing `role`, append: `"Before issue_refund: call get_invoice, read the amount back to the caller, and get an explicit yes."` |
| WARN | get_plan_price | plan | W1, W2 | "basic, plus or gigabit" is a fixed set from `data/plans.json` with no `enum`; description does not say to ask. Handler does `.strip().lower()` then `in plans`. | `{"type":"string","description":"Which plan the caller is asking about. Ask if not provided.","enum":["basic","plus","gigabit"]}` (build as `"enum": list(load(config.PLANS_FILE))`) |
| WARN | check_service_status | service | W1, W2 | "internet, tv or phone" is a fixed set from `data/service_status.json` with no `enum`; no "ask". Handler `.lower()` + `in status`. | `{"type":"string","description":"Which service the caller is asking about. Ask if not provided.","enum":["internet","tv","phone"]}` (`list(load(config.STATUS_FILE))`) |
| WARN | get_invoice | invoice_id | W1, W2 | "Invoice number" gives no shape and no `pattern`; handler `invoice_key()` normalizes ASR variants to `INV-####`, so the model should be told the canonical form. | `{"type":"string","description":"The caller's invoice number, normalized to INV-#### (for example INV-1001). Ask for it if not provided.","pattern":"^(INV-)?[0-9]{4}$"}` |
| WARN | issue_refund | invoice_id | W1, W2 | Same as `get_invoice`, and the description does not tie it to the invoice already looked up. | `{"type":"string","description":"Invoice number already looked up with get_invoice, as INV-#### (for example INV-1001). Ask if not provided.","pattern":"^(INV-)?[0-9]{4}$"}` |
| WARN | open_ticket | summary | W1 | "What is wrong" says neither whose words nor the shape; the model can compose a summary from a vague complaint. Handler only rejects blank. | `"description": "One-sentence summary of the problem in the caller's own words. Ask the caller to describe the problem if they have not."` |
verdict: No schema errors, but every caller-supplied parameter lacks an enum/pattern and "ask" wording, and the refund-confirmation rule lives only in the tool description.

## 04-hiring-phone-screen
dump: ok (plain, and `--query-params '{"candidate":"C-0101"}'` per README) ; validate_swml: 1 error on each variant (top-level `ai.prompt` oneOf; leaf cause is SDK-emitted `contexts.default.steps[0].gather_info`, unevaluated by `ContextPOMSteps`/`ContextTextSteps` in the bundled `schema.json`; platform accepted it on the live call. `submit_screen` parameters validate clean in isolation)
tools: submit_screen (plus platform `gather_submit*`, whose schema is derived from `config.QUESTIONS`; not in `SWAIG.functions`)
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | gather_submit* | earliest_start | W2 | "What is the earliest date you could start?" is `type: string` with no shape; the live test stored `"Monday, November 9"` (no year, not ATS-parseable). `add_gather_question` takes only `type/confirm/prompt/functions/isolated`, so there is no `format`; pin the shape in `prompt`. | `config.QUESTIONS[2]`: `{"key": "earliest_start", "type": "string", "confirm": True, "question": "What is the earliest date you could start?", "prompt": "Submit a full calendar date as YYYY-MM-DD. If the candidate gives only a weekday or a month and day, ask which year, then read the full date back."}` |
verdict: Clean except one date-shaped gather answer with no shape constraint; `submit_screen` takes no model arguments and the gather locks out every other tool.

TOTAL: E=1 W=7 I=1

## 05-package-tracking-line
dump: ok ; validate_swml: ok
tools: track_package (DataMap, platform-run; `defaults.web_hook_url` is SDK-owned and unused)
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | track_package | tracking_number | W1 | Description "The tracking number, digits only, no spaces or dashes" gives the shape but not the source; it never tells the model to ask. The Role bullet "Ask for the tracking number" carries that today, and global_data is empty so there is nothing to mistake for it, but the SDK's own `DataMap.parameter` docstring gives the canonical form ("...Ask the user if they don't provide it."). | `.parameter("tracking_number", "string", "The caller's tracking number, digits only, no spaces or dashes. Ask the caller if they don't provide it.", required=True)` |
| WARN | track_package | tracking_number | W2 | Digits-only value with no `pattern`; a model that passes "4001 0001" gets URL-encoded into a 404 and the fallback. `DataMap.parameter()` has no `pattern` kwarg (signature: name, param_type, description, required, enum), so it must be set on the dict. `tests/golden/track_package.json` and the README YAML block are pinned by tests and must change in step. | In `TrivialAgent.__init__` (app.py:44): `fn = build_track_package().to_swaig_function(); fn["parameters"]["properties"]["tracking_number"]["pattern"] = "^[0-9]+$"; self.register_swaig_function(fn)` and add `pattern: "^[0-9]+$"` to the golden file and README `tracking_number` line |
verdict: Schema valid and the prompt already says "Ask for the tracking number"; the one caller-supplied parameter just lacks the ask-if-missing wording and a digits pattern.

## 06-movie-showtimes-hotline
dump: n/a (SWML-only, no app.py; audited showtimes.swml.yaml directly) ; validate_swml: ok
tools: get_showtimes (DataMap, zero parameters: `properties: {}`)
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | get_showtimes | prompt.text, Rules bullet 2 | P1 | The feed is today-only (tool description, filler and the "no showtimes listed for today" expression all say so) but the prompt's list of things to decline ("prices, concessions, a film that isn't listed") never mentions other days, so a caller asking "what's on Saturday" can be read today's list as that day's. Same class as the date trap, with the day supplied by the caller and no parameter to carry it. | Replace `(prices, concessions, a film that isn't listed)` with `(prices, concessions, a film that isn't listed, or any day other than today)` |
verdict: No parameters to audit and the schema is valid; the only gap is the prompt not saying the listing is today-only.

## 07-trivia-hotline
dump: ok ; validate_swml: ok
tools: submit_answer
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | submit_answer | answer | W1 | "What the caller said, verbatim" names the value but does not tell the model to wait for the caller or forbid supplying one itself. The `play` step and the Role section cover it at prompt level, but the description is what the model reads at call time, and every call consumes a round. Handler side is fine. | `"answer": {"type": "string", "description": "The caller's spoken answer to the current question, verbatim, or their words if they give up. Only call after the caller has spoken. Never supply an answer yourself."}` |
verdict: Schema and handler agree, step text asks and gates the call correctly; only the parameter description lacks the do-not-assume wording.

TOTAL: E=0 W=4 I=0

## 08-bank-balance-line
dump: ok ; validate_swml: ok
tools: verify_identity, get_balance, list_transactions, open_dispute, escalate_call
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | verify_identity | date_of_birth | W2+W1 | Description "Date of birth as the caller said it" invites spoken forms, but `normalize_dob` parses only 6 strptime shapes: "14th of March 1985", "March fourteenth 1985", "3/14/85", "the 14th of March, 1985" all return None, and a parse miss is charged as a failed verification ("don't match our records"), three of which escalate. No format, no ask instruction. | `{"type":"string","format":"date","description":"Date of birth as YYYY-MM-DD, converted from what the caller says (e.g. 'March 14th 1985' -> 1985-03-14). Ask if not provided; never guess it."}` |
| WARN | verify_identity | account_number | W1+W2 | "The account number, digits only" has no pattern and no ask instruction; handler strips non-digits. | `{"type":"string","pattern":"^[0-9]+$","description":"The account number, digits only. Ask if not provided."}` |
| WARN | open_dispute | transaction_id | W1+W2 | Example "T-9005" is a real id on test account ACC-0101; nothing says the id must come from list_transactions or the caller, and there is no pattern. | `{"type":"string","pattern":"^T-[0-9]+$","description":"The transaction id exactly as returned by list_transactions, e.g. T-1234. Call list_transactions and ask the caller which one if not already known."}` |
| WARN | open_dispute | reason | W1 | "Why the caller disputes it" does not tell the model to ask; nothing stops it inventing a reason, which the handler writes to disputes.jsonl verbatim. | `"The caller's reason for the dispute, in their words. Ask if not provided."` |
| WARN | list_transactions | count | W1 | "How many to list" gives no range or default; handler defaults to 3 and clamps to 1..config.MAX_TRANSACTIONS (5). | `{"type":"integer","description":"How many transactions to read out, 1 to 5. Omit for the default of 3.","default":3}` (build "1 to {config.MAX_TRANSACTIONS}" from config) |
| WARN | step account_menu | text | P1 | "Help with ... disputing a transaction" never says to list transactions and ask which one and why before open_dispute; the handler recovers from an unknown id but not from an invented reason. | `"The caller is verified as ${global_data.customer.name}. Help with their balance, recent transactions, or disputing a transaction. To dispute, call list_transactions, ask which transaction and why, then call open_dispute. When they are done, move to wrap_up."` |
verdict: Schemas validate, but date_of_birth is the recipe-01 class of problem (free-form date, no format) with the added cost that a parse miss silently counts as a failed verification attempt.

## 09-insurance-claim-intake
dump: ok ; validate_swml: 1 error (step `intake`: `gather_info` is not a step key in the 3.7.5 bundled schema; see INFO row)
tools: check_policy_number, check_incident_date, check_location, check_injuries, submit_claim, join_adjuster, promise_callback
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | promise_callback | preferred_time | W1 | Description gives an example value ('tomorrow after 2pm') and no ask instruction; the value is stored verbatim as the callback promise, so the example can be echoed as the answer (the callback step text does say "ask", which limits the risk). | `"When the caller wants the callback, in their words (day and time window). Ask if not provided."` |
| INFO | step intake | gather_info | validator (SDK-owned) | validate_swml fails only because signalwire-sdk 3.7.5's bundled schema.json has zero occurrences of `gather_info` while the SDK's own set_gather_info/add_gather_question emit it. Not a parameter issue; not fixable in app.py. | None in the recipe; note in README that validate_swml flags `gather_info` until the bundled schema catches up. |
verdict: Parameter schemas are clean by design (every tool takes the caller's exact words and code decides); the only validator failure is the SDK's bundled schema lagging its own gather_info API.

## 10-utility-bill-payment-line
dump: ok (plain and `--query-params '{"pay_ref":"deadbeef"}'`) ; validate_swml: ok (both)
tools: verify_account, take_payment, resume_recording
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | verify_account | service_zip | W1+W2 | "ZIP code of the service address" gives no shape, pattern or ask instruction. Handler compares `str(..).strip()` exactly against the 5-digit record and, unlike account_number, does not strip inner spaces or a ZIP+4 suffix, so "7 4 1 0 1" or "74101-1234" fails as "didn't match". | `{"type":"string","pattern":"^[0-9]{5}$","description":"The 5-digit ZIP code of the service address, digits only. Ask if not provided."}` and in the handler: `zip_code = "".join(ch for ch in str(args.get("service_zip", "")) if ch.isdigit())[:5]` |
| WARN | verify_account | account_number | W1+W2 | "Six-digit account number" states the shape but has no pattern and no ask instruction; handler strips non-digits. | `{"type":"string","pattern":"^[0-9]{6}$","description":"The six-digit account number, digits only. Ask if not provided."}` |
verdict: Clean by design (payment tools take no arguments and the amount comes from global_data); only the two verify parameters lack patterns and ask instructions, and service_zip is matched more strictly than its description suggests.

TOTAL: E=0 W=9 I=1

## 11-collections-agent
dump: ok ; validate_swml: ok
tools: find_account, propose_plan, decline_plan, choose_hardship_option, escalate, transfer_to_agent
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | propose_plan | months | W1/P1 | "Number of monthly payments" never says to ask; the step text puts `${global_data.account.balance_text}` in front of the model, so when the caller names only a monthly figure it can compute months = balance / amount instead of asking (the README's own example `--monthly_amount 20 --months 62` is exactly 1240/20) | `"months": {"type": "integer", "description": "Number of monthly payments the caller is offering. Ask if not provided; never compute it from the balance."}` |
| WARN | propose_plan | monthly_amount | W1 | "Dollars per month the caller offers" gives no shape and no instruction to ask | `"monthly_amount": {"type": "number", "description": "Dollars per month the caller says they can pay, e.g. 125 or 62.50. Ask if not provided."}` |
| WARN | find_account | postal_code | W2/W1 | "Five-digit ZIP code", no pattern; handler compares the exact string to the ledger; no "ask" wording | `"postal_code": {"type": "string", "description": "Caller's five-digit ZIP code as printed on the letter. Ask if not provided.", "pattern": "^[0-9]{5}$"}` |
| WARN | find_account | reference | W1 | "Reference number from the letter" says nothing about shape (two letters + five digits; `ledger.find` strips spaces/dashes and uppercases) or asking | `"reference": {"type": "string", "description": "Reference number printed on the caller's letter: two letters then five digits, e.g. CA20417. Ask if not provided."}` |
| WARN | escalate | reason | W1 | enum has no description at all | `"reason": {"type": "string", "enum": ["requested_person", "abuse"], "description": "requested_person = the caller asked for a human; abuse = the caller is abusive or threatening"}` |
| INFO | propose_plan | handler | E2 (soft) | both params are `required` but the handler tolerates None via `.get()`, maps it to `policy.INVALID` and sends that through `_refuse`, so a garbled argument burns one of the caller's `MAX_REFUSALS` | in `propose_plan`, before `_refuse`: `if verdict == policy.INVALID: return FunctionResult(REFUSAL_HINTS[verdict])` |
| INFO | hardship_options step | text | style | step text hands the model the raw keys (`payment_pause: ...`), which TTS may read as "payment underscore pause" | list only the descriptions and let the enum carry the key |
verdict: Schema is valid and enums come from config; the real risk is the model deriving `months` from the balance it is shown instead of asking, plus an undescribed `escalate.reason`.

## 12-medical-appointment-line
dump: ok ; validate_swml: ok
tools: record_consent, find_slots, book_slot, hold_slot
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | find_slots | day | W2/W1 | free string compared case-insensitively to the slot file's weekday names; "Mon", "Tuesdays", "tomorrow" or a date all miss and the handler answers "No open slots for that day", which the model relays as fact; description does not say omit = all days or to ask | `"day": {"type": "string", "enum": ["Monday",...,"Sunday"], "description": "Day of the week the caller asked for. Ask which day suits them; omit to list every open slot."}` (or derive the enum from `{s["day"] for s in load_slots()}`) |
| WARN | book_slot, hold_slot | slot_id | W2 | fixed shape `S-NNNN` with no pattern; a malformed id is answered with "That slot isn't available", which reads as the slot being gone | `SLOT_ID = {"type": "string", "description": "Slot id exactly as returned by find_slots, e.g. S-0101", "pattern": "^S-[0-9]{4}$"}` |
| WARN | schedule_limited step | text | P1 | unlike `schedule` ("Ask which day suits the caller, call find_slots, offer the options"), this step says only "Call find_slots, and call hold_slot for the one they want", so the model may pick a day or a slot itself | "Ask which day suits the caller, call find_slots, offer the options, and call hold_slot for the one they choose. Explain that the front desk will call back to confirm the hold." |
| INFO | find_slots | day | P1 | slots are keyed by weekday only and nothing in the prompt or global_data gives today's date, so "tomorrow" / "next week" cannot be mapped | tell the model to ask for a day of the week by name, or inject today's weekday into global_data and say so |
verdict: The consent gate is tight; the scheduling side needs a weekday enum, a slot-id pattern, and the unrecorded step should ask for the day the way the recorded one does.

## 13-lead-qualification-line
dump: ok ; validate_swml: 1 error
tools: record_budget, record_timeline, record_authority, record_need
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| ERROR | (prompt) | ai.prompt.model | E1 | validator: `'model' was unevaluated and invalid` under AIPromptPom. SDK-owned: `set_prompt_llm_params(model=config.MODEL)` passes `model` straight into `ai.prompt`; schema.json 3.7.5's home for the model is `ai.params.ai_model`. Same emission in recipes 09, 16, 20, 36. The dump with the key moved to `params.ai_model` validates ok (platform behaviour not live-verified) | `self.set_params({"ai_model": config.MODEL})` in place of `self.set_prompt_llm_params(model=config.MODEL)`, or document it as a known schema.json gap |
| WARN | record_budget | amount_usd | W1/P1 | "Whole dollars. 0 if no budget yet." never says to ask, and hands the model a legal value to send before the caller answers; `record()` then counts the field as collected. Live call 44f199dd already showed a guessed `record_timeline(0)` | `"amount_usd": {"type": "integer", "description": "Budget in whole US dollars as stated by the caller, e.g. 20000. Ask if not provided. Send 0 only if the caller says they have no budget yet."}` |
| WARN | record_timeline | months | W1/P1 | "0 = this month. 24 if just researching." gives two encodings and no rule for "next quarter" or for asking; the model inferred 0 from "mark me as a hot lead" on the live call | `"months": {"type": "integer", "description": "Whole months from now until the caller wants to buy, as stated by the caller: this month = 0, next month = 1, next quarter = 3, just researching = {MAX}. Ask if not provided; never infer it."}` |
| WARN | record_authority, record_need | is_decision_maker, need | W1 | neither description says to ask; "The closest match to what the caller needs" invites a guess from a vague pitch | `"true if the caller says they make or sign off on the purchase, false if someone else does. Ask if not provided."` / `"The category closest to what the caller says they need; use other if none fits. Ask if not provided."` |
| WARN | qualify step | text | P1 | "Learn four things, in any order" never says to ask the caller for each one; nothing forbids inferring a value from the pitch or from "mark me as hot" (the live log shows exactly that inference) | "Ask the caller for four things, one question at a time and in any order: budget (record_budget), timeline (record_timeline), whether they sign off on the purchase (record_authority), and what they need (record_need). Call a tool only with a value the caller actually stated, never a guess or an inference from how they want to be marked. ..." |
verdict: Parameter types match the handlers and `need` comes from config, but the SDK's `prompt.model` fails the bundled schema, and every parameter description plus the step text let the model fill in values the caller never gave, which the recipe's own live test already demonstrated.

TOTAL: E=1 W=12 I=3

## 14-appointment-reminder-caller
dump: ok (plain; `--query-params '{"appt":"A-0101"}'`) ; validate_swml: ok (both)
tools: confirm_identity, confirm_appointment, reschedule_appointment, cancel_appointment, opt_out
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | reschedule_appointment | new_start | W1+W2 | Caller-supplied date+time. Description "Local time, YYYY-MM-DD HH:MM (24h)" gives the shape but never tells the model to ask for the date or read it back; no pattern although the handler parses strictly with `%Y-%m-%d %H:%M`. Same class as the recipe-01 date trap. | `{"type":"string","description":"New local date and time the contact asked for, YYYY-MM-DD HH:MM (24h). Ask for the date and the time; read both back before calling. Never assume the date is today.","pattern":"^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}$"}` |
| WARN | manage (step) | new_start | P1 | Step says only "Use ... reschedule_appointment"; nothing tells the model to ask for a full date and time, so "Thursday at 3" is resolved against the model's own idea of today. `ai.params.local_tz` is never set, so that "today" is platform time, not the contact's (their timezone is already in appointments.csv and used by dialer.py). | Step text: "...If they want to move it, ask for the new date and the time, one at a time, read them back, then call reschedule_appointment. Never assume the date is today." In `configure()`: `agent.set_param("local_tz", contact["timezone"])` |
verdict: Schemas are valid and the manage tools correctly take nothing from the model, but the one caller-supplied value (new_start) has exactly the recipe-01 exposure: shape without ask/read-back, no pattern, and no local_tz.

## 15-support-line-with-callback
dump: ok (SupportAgent; CallbackAgent plain and with `--query-params '{"id":"CB-0001"}'`) ; validate_swml: ok (all three)
tools: SupportAgent: request_human, schedule_callback; CallbackAgent: connect_human
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| ERROR | request_human | summary | E2 | Listed in `required` but the handler treats it as optional: only `issue` is checked, `summary` defaults to "" and is stored on the ticket. | `if not issue or not summary: return FunctionResult("Ask the caller what the problem is first, then call request_human with both an issue and a summary.")` (or drop "summary" from `required`) |
| WARN | schedule_callback | preferred_time | W1 | Description is only an example ("e.g. 'today after 4pm'"); does not say what the value is, that it is the caller's own words, or to ask. The step text does say "ask when suits them", so P1 is covered there; the worker never parses this field. | `{"type":"string","description":"When the caller wants to be called back, in their own words (e.g. 'today after 4pm'). Ask if not provided; do not guess a time."}` |
verdict: Valid schemas, and the callback number comes from caller_id_num rather than the model; only `summary` is required-but-unchecked and `preferred_time` needs a real description.

## 16-travel-concierge
dump: ok (concierge default route; booking `--route /booking`) ; validate_swml: concierge ok; booking 1 error: `ai.prompt.model` (emitted by `set_prompt_llm_params(model=...)`) is not in schema.json's AIPromptPom; not a tool schema
tools: concierge: destination_info, handoff_to_booking; booking: search_flights, hold_flight, return_to_concierge
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| ERROR | handoff_to_booking | travelers | E2 | Schema says integer but the handler does `int(args.get("travelers") or 0)` with no guard; SDK validation is soft, so "two" or "2 adults" raises ValueError and the SWAIG call fails instead of returning the "Ask how many" reply. | `try: travelers = int(args.get("travelers") or 0)` / `except (TypeError, ValueError): travelers = 0` |
| WARN | destination_info, handoff_to_booking | destination | W1+W2 | Fixed set of choices (destinations.json keys: lisbon, kyoto, reykjavik) but the description is only "e.g. lisbon" and there is no enum; the handler lowercases and looks up by key. | `{"type":"string","description":"Destination key, lowercase.","enum":list(self.destinations)}` |
| WARN | handoff_to_booking | travelers | W1 | "Number of travelers": caller-supplied, no range, no ask instruction. The booking desk's static_greeting opens with "I have N travelers to X", so a guessed 1 is spoken as fact. | `{"type":"integer","description":"Number of travelers, 1 to 6. Ask if not provided; never assume one."}` (range text from `config.MAX_TRAVELERS`) |
| WARN | handoff_to_booking | month | W1+W2 | "Month of travel": caller-supplied, no ask instruction, no enum; the model can fill it from the current date. | `{"type":"string","description":"Month of travel as the caller said it. Ask if not provided; never assume the current month.","enum":["January",...,"December"]}` |
| WARN | Role section / explore (step) | destination, travelers, month | P1 | Role says "confirm the destination, how many travelers and which month, then call handoff_to_booking" and the step says only "Hand off to booking when they're ready"; neither says ask. | explore text: "Help the caller choose a trip. Before handing off, ask for the destination, the number of travelers and the month of travel, one at a time if needed, and read them back. Never assume one traveler or the current month. Then call handoff_to_booking." |
| INFO | BookingDesk (agent) | ai.prompt.model | validate | `set_prompt_llm_params(model=...)` lands under `ai.prompt` as `model`, which 3.7.5's schema.json does not list although the SDK docstring says the server accepts it. `scripts/validate_swml.py` will keep failing on `/booking`. | None in the recipe (SDK/schema lag); note it in the README's swaig-test section |
verdict: The booking desk is well guarded (everything comes from global_data), but the concierge's three handoff fields are caller-supplied with example-only descriptions, no enums, and no ask instruction, and `travelers` can crash the handler on a non-numeric value.

TOTAL: E=2 W=7 I=1

## 17-customer-survey-caller
dump: ok (plain; `--query-params '{"customer":"P-0101"}'`) ; validate_swml: ok (both)
tools: log_response, validate_response*
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| ERROR | log_response | question_id, response | E2 | Handler refuses a missing `question_id` ("Unknown question") and, for the three required questions, a missing `response`, but the schema has no `required` list: `@AgentBase.tool(parameters=<props map>)` wraps without one (app.py:101-108) | `parameters={"type":"object","properties":{...},"required":["question_id","response"]}` |
| ERROR | validate_response* | response | E2 | SDK-owned prefab handler still parses ratings with `int(response.strip())`, so "nine" (what the model sent on live call 46145b42) returns "Invalid rating" while the recipe's overridden `log_response` accepts it via `spoken_number()`; the two shipped tools disagree on the same answer | Override `validate_response` in `SurveyCaller` with the same schema as `log_response` and reuse `normalize(q, response)` |
| WARN | log_response | question_id | W2 | Fixed set of ids (`config.QUESTIONS`) but no enum; "The ID of the question" does not say which ids exist | `"question_id": {"type":"string","description":"ID of the question just answered.","enum":[q["id"] for q in config.QUESTIONS]}` |
| WARN | log_response | response | W1 | "The caller's answer" gives no shape (number for ratings, one listed option, yes/no, free text) and does not tell the model to record only what the caller said | `"description": "The caller's answer exactly as spoken: for a rating the number (digits or words), for multiple choice one of the listed options, for yes/no 'yes' or 'no', otherwise their words; empty string if they decline an optional question. Never fill this in yourself; ask if the caller has not answered."` |
verdict: Schema is platform-valid, but the recipe's tool has no `required` list and the un-overridden prefab `validate_response` still `int()`-parses ratings; add the question-id enum and answer-shape text.

## 18-drive-thru-order-taker
dump: ok ; validate_swml: ok
tools: add_item, modify_item, remove_item, finish_order, accept_substitute, decline_substitute, confirm_order, change_order
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | add_item | size | W1 | "Size, e.g. large. Omit if the item has one size" never tells the model to ask; the handler forces the ask only when size is omitted, so a guessed "single" or "medium" for a multi-size item is accepted silently (the date trap) | `"description": "Size the caller asked for, one of the sizes listed for that item. Ask if the item has more than one size and the caller did not say one; never assume. Omit only for one-size items."` |
| WARN | add_item | side, drink | W1+W2 | "Combos only: the side item id" has no ask instruction (a guessed fries/soda is accepted by `check_line`) and no enum although the choices are fixed in `data/menu.json` | `"side": {"type":"string","description":"Combos only: the side the caller chose. Ask if not said; never assume.","enum":["fries","onion_rings"]}`, `"drink": {... "enum":["soda","milkshake"]}`, built from menu.json |
| WARN | add_item | item | W2 | Fixed set (menu.json keys) but no enum; the model must transcribe ids from the Menu prompt section | `"item": {"type":"string","description":"Menu item id.","enum": list(menu)}` (load the menu at module level before `ITEM_PARAMS`, app.py:16) |
| WARN | add_item, modify_item | size; modifiers / add_modifiers / remove_modifiers | W2 | Fixed sets from menu.json (sizes; 8 modifier strings) with no enum; `'e.g. ["no onions"]'` does not say values are the item's listed modifier names | size enum from menu; modifiers: `"items": {"type":"string","enum": sorted({m for v in menu.values() for m in v["modifiers"]})}` |
| WARN | modify_item | size, quantity | W1 | Descriptions are shared with add_item ("Omit if the item has one size", "How many. Default 1") but in modify_item omission keeps the current value; "Default 1" invites passing `quantity: 1` when only the size changes, silently resetting a multi-quantity line (app.py:115) | `"size": {"type":"string","description":"New size; omit to keep the current size"}`, `"quantity": {"type":"integer","description":"New quantity; omit to keep the current quantity"}` |
| WARN | accept_substitute | choice | W1 | "Substitute id" does not say it must be one of the ids just offered or where they are | `"description": "The substitute the caller picked: exactly one of the options just offered (global_data.pending.options), e.g. fries. Ask which one if they did not say."` |
| WARN | step take_order | text | P1 | "Take the order. Call add_item for each item." lets the model fill in size, side and drink itself; nothing says ask | `"Take the order one item at a time. Before calling add_item, ask for anything the caller has not said: the size when the item has more than one, and the side and drink for a combo. Never assume a size, side or drink. Use modify_item or remove_item to change a line. When the caller says that's everything, call finish_order."` |
verdict: No schema or type errors; the menu-driven choices should be enums built from menu.json, and both the size/side/drink descriptions and the take_order step need an explicit "ask, never assume".

TOTAL: E=2 W=9 I=0

## 19-answering-service
dump: ok (after-hours and office-hours variants, plus default) ; validate_swml: ok (all three)
tools: submit_call
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | submit_call | callback_number | W2 | Description says "digits only" but there is no pattern and the handler only checks non-empty; `--exec --callback_number "555-0142 ext 3"` was accepted and texted verbatim to the owner. Does not tell the model to ask. | `"callback_number": {"type": "string", "description": "Phone number to call the caller back, digits only, e.g. 5551234567. Ask the caller for it; never assume it is the number they called from.", "pattern": "^\\+?[0-9]{7,15}$"}` and in `submit_call`: `if len(re.sub(r"\D", "", args["callback_number"])) < 7: return FunctionResult("Still need: callback_number. Ask for it.")` |
| WARN | submit_call | name | W1 | "Caller's name" does not say to ask rather than assume. | `"description": "The caller's name, as they said it. Ask if not provided."` |
| WARN | submit_call | message | W1 | "in the caller's words" does not say why it must be verbatim: `is_urgent()` whole-word-matches `config.URGENT_KEYWORDS`, so a paraphrase changes routing (`--exec` confirmed: "water problem in basement" -> SMS, "my basement is flooding" -> connect to on-call). | `"description": "What the call is about, verbatim in the caller's own words; do not summarize or reword, the urgency check matches their words. Ask if not provided."` |
| INFO | step intake | text | P1 | Step already says "Ask for the caller's name, a callback number, and what the call is about"; only style gap is asking three fields in one breath. | `"Say the office is closed. Ask for, one at a time: the caller's name, a callback number, and what the call is about. Put the caller's own words in message. Then call submit_call."` |
verdict: Schema and step text are sound; the fixes are description-level plus a pattern and handler check for the unvalidated phone number.

## 20-absence-reporting
dump: ok ; validate_swml: 1 error (`ai.prompt.model` unevaluated; every SWAIG function schema passes)
tools: record_slots, submit_report
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| ERROR | (ai.prompt) | model | E1 | `set_prompt_llm_params(model=config.MODEL)` renders `"prompt": {..., "model": "gpt-4.1-mini"}`; the platform schema rejects `model` on both prompt variants. The sanctioned key is `ai.params.ai_model`. SDK-owned placement; `docs/sdk-notes.md:39` records `prompt.model` as working live (#59), so this is schema-vs-platform, but it leaves the recipe red under `validate_swml`. | Replace with `self.set_params({"ai_model": config.MODEL})`, update README, re-verify live. |
| WARN | record_slots | org_type | W2 | Fixed choice set (`one_of("school", "work")`) with no enum; `--exec --org_type "School absence"` -> "choose school or work" and a wasted turn. | `"org_type": {"type": "string", "enum": ["school", "work"], ...}`; build from config: `one_of` sets `check.choices`, and the `define_tool` comprehension adds `"enum": list(v.choices)` when present. |
| WARN | record_slots | id | W1/W2 | "letters and digits" does not state the shape the handler enforces (`[A-Z]{0,2}\d{4,8}` after stripping spaces and dashes). | `"description": "Student or employee ID: up to two letters then 4 to 8 digits, as the caller said it (spaces or dashes are fine). Ask if not provided."`; optional pattern `"^[A-Za-z]{0,2}[0-9 -]{4,}$"` |
| WARN | record_slots | start_date, end_date | W1 | "in the caller's exact words" is right for this design (handler parses spoken dates; `format: date` deliberately absent), but the description does not forbid normalization and `parse_date` cannot read ISO: `--exec --start_date 2026-11-05` -> "which date? Say the month and day." A model that normalizes dates loops on a question the caller already answered. | Append: `"Pass exactly what the caller said (e.g. 'next Monday', 'the fifth', 'tomorrow'); never convert to YYYY-MM-DD."` and add an ISO fast path at the top of `parse_date`. |
| INFO | record_slots | start_date, end_date (handler) | P1 | `slots.today()` is `date.today()` in the server zone with no TZ knob (Docker = UTC), so a 7 pm Chicago caller's "tomorrow" resolves one day late. | `TZ` in config and `datetime.now(ZoneInfo(config.TZ)).date()` |
| INFO | step done | valid_steps + end | E1 (descriptive) | `done` emits both `"valid_steps": []` and `"end": true`; the schema text for `end` says "Cannot be used along with the `valid_steps` parameter". The validator does not enforce it and #70 shipped it. | On `done` drop `.set_valid_steps([])` and keep `.set_end(True)` |
verdict: The tool schemas are valid and the Role/step text is already built against the date trap; the one validator error is the SDK's `prompt.model` placement, and the real hardening is an enum for `org_type`, exact-shape descriptions for `id`, and stopping the model from ISO-normalizing dates.

TOTAL: E=1 W=6 I=3

## 21-meeting-transcription-line
dump: ok (dictation and bridge variants) ; validate_swml: ok
tools: (none: no SWAIG functions)
verdict: Plain SWMLService document (answer -> live_transcribe -> play -> play silence/connect -> hangup) with no ai verb, no contexts/steps, no SWAIG functions; schema-clean in both variants.

## 22-live-caption-display
dump: ok (dictation and bridge variants) ; validate_swml: ok
tools: (none: no SWAIG functions)
verdict: Same SWML as recipe 21 plus a /captions HTTP page outside the SWML; nothing to audit, validates in both variants.

TOTAL: E=0 W=0 I=0

## 23-sales-call-copilot
dump: ok ; validate_swml: ok
tools: flag_objection (sidecar_skip* is a platform built-in, not in functions[])
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| INFO | flag_objection | customer_quote | W1 | "What the customer said, verbatim" does not say which turn (most recent), nor "not the rep's words / not a paraphrase". The handler is a regex classifier, so a paraphrase misses. Prompt already says "exact words", so style only. | `{"type":"string","description":"The customer's most recent words, quoted exactly as spoken. Not paraphrased, and never the rep's words."}` |
verdict: Schema is valid and matches the handler; the sidecar never collects a value from a caller, so the date-trap class does not apply.

## 24-support-copilot-that-acts
dump: ok ; validate_swml: ok
tools: lookup_order, issue_credit (sidecar_skip* is a platform built-in)
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| ERROR | issue_credit | reason | E2 | Listed in `required` but the handler treats it as optional: app.py:150 `reason = str(args.get("reason", "")).strip()[:200]` and `credit_refusal()` never checks it, so because runtime validation is soft a call with no reason still issues a credit and writes `"reason": ""` to the ledger. | Before `with self.ledger_lock:` add `if not reason: self.feed.push({**card, "status": "refused", "detail": "No reason given."}); return FunctionResult(REFUSED)` |
| WARN | issue_credit | amount / prompt | P1 | Prompt has no branch for a rep who offers a credit with no dollar figure, or as a percentage. The sidecar cannot ask, so the model fills `amount` in itself. The handler caps at CREDIT_CAP_USD and the order total, so damage is bounded, but a credit the rep never quantified can still be issued. | Prompt: "When the rep tells the customer a specific dollar amount they will credit, call issue_credit with the order number, that exact amount, and a short reason. If the rep offers a credit without a dollar amount, or as a percentage, do not call issue_credit; tell the rep in one line to state the amount in dollars." `amount`: `{"type":"number","description":"Credit amount in USD, the exact dollar figure the rep said aloud. Never compute, convert or choose an amount yourself."}` |
| WARN | lookup_order, issue_credit | order_id | W1 | "Order number, e.g. A-1001" gives an example only. `resolve_order_id()` accepts STT variants that keep the digits but not number words, and nothing tells the model to pass what was heard rather than guess a canonical ID. No `pattern` is correct here (one would fight the STT tolerance). | `{"type":"string","description":"Order number as heard, e.g. A-1001. Pass the digits as spoken (A 1002, 81002 and a1002 all resolve); never write digits as words and never guess an order number that was not said on the call."}` |
| INFO | issue_credit | reason | W1 | "Short reason for the credit" does not say whose words or how short; the handler silently truncates at 200 characters. | `{"type":"string","description":"Short reason for the credit, a few words taken from what the customer and rep said, e.g. 'arrived scratched'."}` |
verdict: Schema is valid, but `reason` is required in schema and not enforced in code, and the prompt lets the silent sidecar invent a credit amount when the rep does not state one.

TOTAL: E=1 W=2 I=2

## 25-win-loss-analyzer
dump: ok ; validate_swml: ok
tools: none (no `ai.SWAIG` block; both steps `functions: []`)
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | (post_prompt) | `extraction.POST_PROMPT` last line vs `extraction.SCHEMA` | P2 | The blanket fallback "If they did not say, use null or []." contradicts the schema it is built from: `outcome` is `enum ["won","lost","no_decision"]` with no null, and `reasons` has `minItems: 1`. A prospect who does not state a decision is steered into `null`/`[]`, which `on_summary` then flags instead of counting as `no_decision`. | Replace the last line of `POST_PROMPT` in extraction.py with: `"Use only what the prospect said. \"outcome\" is always one of the three values (\"no_decision\" if they have not bought or decided). Use null for \"competitor\" and [] for \"objections\" only when they did not say."` |
verdict: No SWAIG parameters exist to audit and the interview step already says "ask, one at a time"; the only disagreement is the post_prompt's null/[] fallback, which the extraction schema rejects for `outcome` and `reasons`.

## 26-compliance-call-monitor
dump: failed (swaig-test: `No module named 'httpx'` in the monorepo venv); rendered from source with `service.get_document()` and a stub httpx, dictation and bridge variants ; validate_swml: ok (both)
tools: none (SWMLService, no `ai` verb)
verdict: No SWAIG functions, parameters, prompts or steps; the SWML it produces validates cleanly in both modes.

TOTAL: E=0 W=1 I=0

## 27-sms-concierge
dump: ok ; validate_swml: ok
tools: verify_guest, amenity_hours, request_service (all in concierge.py; no global_data injected)
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | amenity_hours | amenity | W2 | Fixed set (keys of data/amenities.json: pool, gym, breakfast, spa, parking) and the handler does an exact lowercase key lookup, but there is no enum, so "swimming pool"/"fitness center" miss. | `"amenity": {"type": "string", "enum": ["pool", "gym", "breakfast", "spa", "parking"], ...}` built from `list(load_json(config.AMENITIES_FILE))` at module level or via `define_tool` in `__init__`. |
| WARN | amenity_hours | amenity | W1 | "e.g. pool, gym, breakfast" is examples only. | `"description": "The hotel amenity the guest is asking about, lowercase: pool, gym, breakfast, spa or parking. Ask which amenity if the guest did not name one."` |
| WARN | request_service | notes | W1 | For `wake-up call` (and `late checkout`) the time is a value only the guest can give, yet the field is optional and nothing tells the model to ask; a wake-up call can be logged with no time or an assumed one. | `"notes": {"type": "string", "description": "Details the guest gave, such as the wake-up time or late-checkout time. For a wake-up call or late checkout, ask the guest for the time if not provided; never assume one."}` |
| WARN | (step) concierge | step text | P1 | "log requests with request_service" gives no instruction to get the time first. | Append: ` For a wake-up call or late checkout, ask the guest for the time before calling request_service and put it in notes.` |
| WARN | verify_guest | room | W2 | Digits-only shape but no pattern. | `"room": {"type": "string", "pattern": "^[0-9]{1,5}$", "description": "The guest's room number, digits only. Ask if not provided."}` |
| INFO | verify_guest | room, last_name | W1 | Descriptions do not say "ask"; the verify step text is the only guard. | `"last_name": {"type": "string", "description": "The guest's last name as they gave it. Ask if not provided."}` |
verdict: Schema is valid and types match the handlers; the real gaps are a free-text `amenity` where an enum belongs and a wake-up-call time that nothing requires the model to ask for.

## 28-website-chat-agent
dump: ok ; validate_swml: ok
tools: verify_guest, amenity_hours, request_service (concierge.py byte-identical to recipe 27's)
verdict: Identical findings to 27 because concierge.py is shared (same 5 WARN + 1 INFO); fix it once in that file and both recipes are covered.

TOTAL: E=0 W=10 I=2

## 29-appointment-confirmation-sms
dump: ok (default; `--query-params '{"booking":"AC-1001"}'`) ; validate_swml: default ok, booking variant 1 error (`contexts.default.initial_step` not in bundled schema 3.7.5; SDK `set_initial_step`, not a parameter)
tools: book_appointment, reschedule_appointment
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| ERROR | book_appointment | name | E2 | Listed in `required` but the handler never checks it; verified: a call with no `name` returns "Booked.", saves a booking with `"name": ""` and texts it. | Before `slot_problem`: `name = str(args.get("name", "")).strip()` then `if not name: return FunctionResult("Ask for the caller's name before booking.")` |
| WARN | reschedule_appointment | step `reschedule` | P1 | Step text places `${global_data.booking.date}` / `${global_data.booking.time}` in front of the model, and `slot_problem(..., keep=confirmation)` exempts the booking's own slot, so handing the current slot back is accepted; verified: a no-op reschedule that still texts the caller. | Step text: ask for the new date then new time, one at a time, never reuse the current slot unless asked; handler: `if (date, time) == (row["date"], row["time"]): return FunctionResult("That is their current slot. Ask for a different one.")` |
| WARN | both | date (shared `SLOT`) | W2 | Handler matches `YYYY-MM-DD` keys exactly, but no `format`. | `"date": {"type": "string", "format": "date", ...}` |
| WARN | both | time (shared `SLOT`) | W2 | Handler matches zero-padded `HH:MM` exactly (verified: `"9:00"` -> "That isn't an open slot"); no `pattern`. | `"time": {"type": "string", "pattern": "^([01]\\d|2[0-3]):[0-5]\\d$", ...}` |
| WARN | both | date, time descriptions + step `book` | W1 | Descriptions give shape and source but never tell the model to ask; the `book` step asks for name and slot in one breath, so "tomorrow morning" lets the model pick a slot itself. | `"Slot date the caller chose, YYYY-MM-DD, one of the dates in the open slots list. Ask if not provided; never pick a date for the caller."` / `"Slot time the caller chose, HH:MM 24-hour, one of the times listed for that date. Ask if not provided."`; book step: `"Ask for, one at a time: the caller's name, then the date, then the time, matching an open slot. Never assume a slot. Then call book_appointment."` |
| WARN | book_appointment | name | W1 | "Caller's name" says what it is but not to ask. | `"Caller's full name as they say it. Ask if not provided."` |
| INFO | (SDK) | `contexts.default.initial_step` | E1 | SDK-owned schema lag. | none |
verdict: Schema is well-formed, but `name` is effectively optional in code and the shared `SLOT` date/time have no format/pattern or "ask" wording, and the reschedule step lets the model hand back the current slot.

## 30-calendar-assistant-over-mcp
dump: ok ; validate_swml: 1 error (`ai.SWAIG.mcp_servers` not in bundled schema 3.7.5; SDK `add_mcp_server`, not a parameter)
tools: get_today; external (MCP, schema defined by the recipe's reference server `mcp_calendar.py` `TOOLS`): find_free_slots, find_my_meetings, book_meeting, move_meeting; cancel_meeting (admin scope only)
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | find_free_slots / prompt "Rules" | date; rule bullets 1 and 3 | P1 | "Call get_today first ..." then "find_free_slots for the date ..." never say to ask the caller which day; get_today answers "Today is Monday, 2026-11-03", which is exactly the ready-made value the 01 trap used. | `"Ask the caller which day they want. Never assume today. Use get_today only to turn a relative day like 'next Tuesday' into YYYY-MM-DD."` and `"To book: ask for the day, then find_free_slots for that date, offer at most three times, ask which one, then book_meeting."` |
| WARN | book_meeting (external) | title | W1 | Required and caller-supplied, but the Rules never ask for it, so the model invents a title. | `"title": {"type": "string", "description": "Reason for the visit in the caller's words, e.g. Cleaning, Checkup. Ask if not provided."}` plus rule `"Ask what the visit is for before booking."` |
| WARN | find_free_slots (external) | date | W1,W2 | Bare shape "YYYY-MM-DD"; no `format`; handler is `strptime(date, "%Y-%m-%d")`. | `"date": {"type": "string", "format": "date", "description": "The day the caller wants, YYYY-MM-DD. Ask if not provided; never assume today."}` |
| WARN | book_meeting, move_meeting (external) | start, new_start | W1,W2 | Bare shape "YYYY-MM-DD HH:MM"; not RFC 3339, so `format: date_time` would be wrong; a pattern fits. | `"pattern": "^\\d{4}-\\d{2}-\\d{2} ([01]\\d|2[0-3]):[0-5]\\d$"`, description "The free slot the caller chose ... one returned by find_free_slots. Ask if not provided." |
| WARN | book_meeting vs find_my_meetings (external) | attendee | W1 | book_meeting says "Caller's name", find_my_meetings says "Caller's full name"; exact lowercased match, so "Dana" is invisible to a later lookup for "Dana Rivera". | `"Caller's full name exactly as they gave it (same value find_my_meetings uses). Ask if not provided."` |
| WARN | move_meeting, cancel_meeting (external) | meeting_id | W2 | Fixed shape `M-NNNN` with no `pattern`. | `"meeting_id": {"type": "string", "pattern": "^[Mm]-\\d+$", "description": "Meeting id from find_my_meetings, e.g. M-1001"}` |
| INFO | get_today | description | P2 | "in the office's time zone" but the handler uses `datetime.now()` with no TZ set. | Set a TZ in config and use `datetime.now(ZoneInfo(config.OFFICE_TZ))` |
| INFO | (SDK) | `ai.SWAIG.mcp_servers` | E1 | SDK-owned schema lag. | none |
verdict: The only local tool is clean; the real exposure is the prompt-side date trap (get_today plus "find_free_slots for the date" with no instruction to ask) and the reference server's bare-shape descriptions.

TOTAL: E=1 W=11 I=3

## 31-give-claude-a-phone-number
dump: ok ; validate_swml: ok
tools: book_callback, lookup_customer, transfer_to_human (`/mcp` re-exposes lookup_customer and book_callback with the same schemas)
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | book_callback | when | W1 | "Local date and time, YYYY-MM-DD HH:MM" gives the shape only: nothing tells the model to ask, and the platform gives the model the current date/time, so "book me a callback" can become a model-chosen slot (the recipe-01 trap). It never says 24-hour; `strptime("%H")` accepts "2:30" (verified), so 2:30 PM parses as 02:30 and is rejected with the misleading "weekdays 9:00 to 17:00" text. | `"when": {"type":"string","description":"Callback date and time, local, 24-hour clock, exactly YYYY-MM-DD HH:MM (e.g. 2026-11-10 14:30). Ask the caller for the day and the time; never assume today or pick a slot yourself.","pattern":"^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}$"}` |
| WARN | book_callback | when | W2 | Fixed shape, no pattern. `format: date_time` would be wrong (handler parses `%Y-%m-%d %H:%M`, not ISO 8601). | pattern as above (validated against schema.json) |
| WARN | (step) | help | P1 | "Offer to book a callback (book_callback) or ... transfer_to_human." never tells the model to ask for the date and time (also P2). | `"... Offer to book a callback. If they want one, ask for the day and then the time, one at a time; never assume today or pick a slot yourself. Then call book_callback. If they insist on a person now, call transfer_to_human."` |
| WARN | lookup_customer | phone | W2 | Phone number with no pattern; does not warn the model off the caller ID. | `"phone": {"type":"string","description":"The phone number on the caller's account, 10 US digits with no punctuation, e.g. 5555550101. Ask the caller for it; never use the caller ID.","pattern":"^(\\+?1)?\\d{10}$"}` |
| INFO | book_callback | account_id | W1 | Does not say the value comes from `global_data.account_id`; over MCP, Claude can guess one. Handler rejects unknown ids. | `"The account_id returned by lookup_customer (global_data.account_id), e.g. ACME-1001. Never ask the caller for it or invent one."` |
| INFO | (step) | help | P2 | Model is never told the booking window (`config.CALLBACK_HOURS`, `CALLBACK_DAYS`), so it offers slots the handler then rejects. | Prefix the help text with the hours from config. |
verdict: Schema is platform-valid, but `book_callback.when` has the exact recipe-01 date trap (no ask instruction, no pattern, 24-hour not stated) and the phone parameter has no shape.

## 32-order-status-line
dump: ok ; validate_swml: ok
tools: escalate_call, request_refund, verify_identity
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | request_refund | reason | W1 | Required and caller-supplied, but "Why the caller wants a refund" never says to ask; the model will invent a reason, which `crm.issue_credit` writes to `credits.jsonl`. | `"reason": {"type":"string","description":"The caller's own reason for the refund, in their words. Ask if not provided."}` |
| WARN | (step) | order_status | P1 | "If they want a refund, call request_refund." has no instruction to ask why first. | `"If they want a refund, ask why, then call request_refund."` |
| WARN | verify_identity | postal_code | W2 | Fixed shape with no pattern. | `"postal_code": {"type":"string","description":"The five-digit ZIP code the order ships to, digits only, e.g. 74012. Ask if not provided.","pattern":"^\\d{5}$"}` |
| WARN | verify_identity | order_number | W2 | States a shape with no pattern. | `"order_number": {"type":"string","description":"The order number as the caller reads it, digits only, e.g. 100234. Ask if not provided.","pattern":"^\\d+$"}` |
| INFO | (step) | verify_identity | P1 | Asks for order number and ZIP in one breath. | `"Greet the caller. Ask, one at a time, for their order number and then the ZIP code it ships to, then call verify_identity. Don't discuss any order before that."` |
verdict: Schema is platform-valid and the verify step already says "Ask"; the gaps are missing patterns on the two verification fields and a required `reason` that nothing tells the model to ask for.

TOTAL: E=0 W=8 I=3

## 33-agency-answering-service
dump: ok (4 variants: tenant dental, hvac, law, default) ; validate_swml: ok (4/4)
tools: check_hours, take_message, book_appointment, request_consultation, dispatch_technician, transfer_call (all recipe-defined in `TOOLS`/`define_tool`; default tenant exposes take_message only)
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| ERROR | dispatch_technician | emergency | E2 | Listed in `required`, but handler is `if args.get("emergency") is True:`; a missing or non-boolean value silently takes the non-emergency branch and opens a routine ticket. Unsafe default for a gas-smell or no-heat call. | Before the branch: `if not isinstance(args.get("emergency"), bool): return FunctionResult("Ask whether this is an emergency: no heat below freezing, a gas smell, or water leaking from equipment.")` |
| ERROR | take_message, book_appointment, request_consultation, dispatch_technician | caller_name, callback_number, message / patient_name, reason / name / address, issue | E2 | All in `required`, but every handler does `args.get(k, "")`, writes the row with blanks, then promises a callback. A missing callback_number is saved as "" and the caller is still promised a call. | In each handler: `missing = [k for k in (...) if not str(args.get(k,"")).strip()]` / `if missing: return FunctionResult(f"Ask the caller for their {missing[0].replace('_',' ')} before saving.")` |
| WARN | take_message | callback_number | W1, W2, P1 | Bare `{"type":"string"}`: no shape, no pattern, no "ask"; nothing stops the model assuming the inbound caller ID is the callback number. | `"callback_number": {"type":"string","pattern":"^\\+?[0-9]{10,15}$","description":"Phone number to call back, digits only with area code. Ask if not provided and read it back to confirm; never assume it is the number they are calling from."}` |
| WARN | take_message | caller_name, message | W1 | No descriptions at all. | `"caller_name": {"type":"string","description":"Caller's name as they gave it. Ask if not provided."}`, `"message": {"type":"string","description":"What the caller wants the business to know, in their words. Ask if not provided."}` |
| WARN | book_appointment | patient_name, reason | W1 | No descriptions. | `"patient_name": {"type":"string","description":"Patient's full name. Ask if not provided."}`, `"reason": {"type":"string","description":"Reason for the visit in the caller's words, e.g. cleaning, toothache. Ask if not provided."}` |
| WARN | dispatch_technician | address, issue, emergency | W1 | No descriptions on any of the three; the emergency criteria live only in the tenant prompt. | `"address": {...,"description":"Service address, street and city. Ask if not provided."}`, `"issue": {...,"description":"What is wrong, in the caller's words. Ask if not provided."}`, `"emergency": {"type":"boolean","description":"true only if the caller confirmed no heat below freezing, a gas smell, or water leaking from equipment; otherwise false. Ask if unsure."}` |
| WARN | dispatch_technician | required vs description | P2 | "emergency=true connects the on-call technician now", but `required=["address","issue","emergency"]` forces the model to finish collecting address and issue before it can place an emergency call; the emergency branch never reads them. | `required=["emergency"]` (guard address/issue in the non-emergency branch); description updated to say address and issue may be omitted for an emergency. |
| WARN | request_consultation | name, practice_area | W1 | No descriptions; enum values such as `real_estate` are not explained. | `"name": {...,"description":"Caller's full name. Ask if not provided."}`, `"practice_area": {"type":"string","enum": cfg.get("practice_areas", []),"description":"Kind of legal matter, picked from the list from what the caller described. Ask if unclear; do not guess."}` |
| WARN | check_hours | day | W2 | Handler accepts only the seven lowercase `DAYS`; schema is a free string. | `"day": {"type":"string","enum": DAYS,"description":"Day of the week the caller asked about. Ask which day if they did not say one."}` |
| WARN | (prompt) Rules section, every tenant | P1 | No instruction to ask for each value or to never fill one in. | Add Rules bullet: "When a tool needs the caller's name, callback number, address or reason, ask for each one and read numbers back. Never fill in a value the caller did not give." |
| INFO | book_appointment | preferred_day | P1 | Optional with no "omit if not said", so the model may supply today's weekday. | "Day the caller asked for, as they said it, e.g. Tuesday. Omit if they did not say one; do not ask." |
| INFO | transfer_call | target | W1 | Enum from cfg carries the meaning, but no description. | `"target": {...,"description":"Which line to connect, e.g. front_desk. Only after the caller agrees to be transferred."}` |
verdict: All four SWML variants are platform-valid, but every caller-supplied string is undescribed, no handler enforces `required`, and the emergency flag defaults unsafe when absent; fixing `TOOLS` and the four handlers once covers every tenant.

## 34-stock-quote-line
dump: ok (QuoteLineAgent; StockPlanAgent via `--agent-class`) ; validate_swml: ok (2/2)
tools: get_stock_quote, get_company_share_price (both registered by the recipe's own skill `skills/stock_quote/skill.py`)
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | (prompt) StockPlanAgent Role + skill section | ticker source | P1 | Nothing in the SWML tells the model the ticker is ACME; the model must invent the ticker from the company name. Works for the mock by coincidence and fails for any real `DESK_COMPANY`. | In `_get_prompt_sections`, when `self.watchlist`: append f" This line quotes only {', '.join(self.watchlist)}; always pass that ticker exactly, whatever the caller calls the company." |
| WARN | get_company_share_price | ticker | W2 | Handler enforces `watchlist=["ACME"]`, but the schema is a free string. | In `register_tools`: `if self.watchlist: params["ticker"]["enum"] = self.watchlist` |
| WARN | get_stock_quote, get_company_share_price | ticker | W1, W2 | "Ticker symbol, e.g. ACME" gives no shape (handler's `TICKER` regex rejects anything but 1-6 letters/dots) and does not say to ask or spell rather than guess. | `"ticker": {"type":"string","pattern":"^[A-Z][A-Z.]{0,5}$","description":"Stock ticker symbol in capital letters, 1 to 6 letters, as the caller said or spelled it, e.g. ACME. If they gave only a company name, ask them to spell the ticker; never guess it."}` |
| INFO | stock_quote skill params (`get_parameter_schema`) | watchlist | W3 | Skill-config schema declares `type: array` with no `items`; no platform impact. | add `"items":{"type":"string"}` |
verdict: Both dumps are platform-valid and the handler is defensive; the real gap is the stock-plan line, where neither prompt nor schema tells the model its only ticker.

TOTAL: E=2 W=11 I=3

## 35-bilingual-support-line
dump: ok ; validate_swml: 1 error (ai.SWAIG.internal_fillers.next_step, schema-owned, see INFO row)
tools: lookup_account, check_outage, get_balance
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | lookup_account | account_number | W1, W2 | "Six-digit account number" has no `pattern` and never tells the model to ask; handler digit-strips then exact-matches the key, so anything not exactly six digits silently returns `no_match`. | `"account_number": {"type": "string", "description": "The caller's six-digit account number, digits only, e.g. 100234. Ask the caller for it; never guess it.", "pattern": "^[0-9]{6}$"}` |
| WARN | lookup_account | zip | W1, W2 | No `pattern` and no ask; a spoken ZIP+4 becomes 9 digits and never matches. | `"zip": {"type": "string", "description": "Five-digit ZIP code of the service address, digits only, e.g. 74103 (no ZIP+4). Ask the caller for it; never guess it.", "pattern": "^[0-9]{5}$"}` |
| INFO | (ai.SWAIG.internal_fillers)* | next_step | E1 (schema-owned) | schema.json 3.7.5 `FunctionFillers` is a `oneOf` of single-language objects, so the two-language map `add_internal_filler` emits (and the SDK docstring example uses) can never validate; the SWML reference puts no such limit. | none in recipe (report upstream) |
verdict: Both lookup_account parameters need a digit pattern and an ask-first description; the lone validator error is a schema.json limitation on multi-language internal fillers.

## 36-voice-latency-lab
dump: ok (default plus four `--query-params '{"config": ...}'` variants; functions and step texts identical) ; validate_swml: 1 error in each (ai.prompt.model, schema-owned)
tools: check_hours
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | check_hours | day | W1, W2 | "Day of the week, e.g. monday" with no `enum`; handler accepts only the seven lowercase `DAYS` values; description neither gives the shape nor tells the model to ask. | `"day": {"type": "string", "description": "Day of the week the caller asked about, lowercase English name. Ask if not provided; never assume today.", "enum": DAYS}` |
| WARN | step answer | text | P1 | "For any day, call check_hours." never tells the model to ask when no day was given, so for "are you open?" the model fills `day` from the platform clock. `CALLER_SCRIPT` always names a day, so lab runs are unaffected; a human caller is not. | "Answer questions about opening hours. When the caller names a day, call check_hours with that day. If they do not name one, ask which day; never assume today." |
| INFO | (ai.prompt)* | model | E1 (schema-owned) | `set_prompt_llm_params(model=...)` writes `prompt.model`, which the SWML reference documents and the platform honored on the 2026-10-30 live calls, but schema.json 3.7.5 lacks it (only `params.ai_model`). | none in recipe (schema.json lags the platform) |
verdict: check_hours needs an enum and an ask-first description and the step must tell the model to ask for the day; the validator error is schema.json lagging the documented prompt.model.

## _template
dump: ok ; validate_swml: ok
tools: check_hours
| severity | tool | parameter/step | check | finding | proposed fix |
|---|---|---|---|---|---|
| WARN | check_hours | day | W1, W2 | "Day of the week, e.g. monday" with no `enum`; handler accepts only the seven lowercase `DAYS` values. This is the seed every recipe is cloned from, and recipe 36 inherited it verbatim. | `"day": {"type": "string", "description": "Day of the week the caller wants to visit, lowercase English name (monday to sunday). Ask if not provided; never assume today.", "enum": DAYS}` |
verdict: The template's only tool is sound except that its `day` parameter is the weak seed that propagates to clones; the `lookup` step already says "Ask which day".

TOTAL: E=0 W=5 I=2


## Fixes applied, 2026-11-03

Fourteen agents applied every ERROR and WARN row (and description-only INFO rows) to recipes
02 through 36 and `_template`, one agent per audit block, after recipe 01 was fixed by hand.
Rows that change runtime behaviour beyond the audit's ask (time zones, step structure) and
SDK-owned rows (the `native_vector_search` skill in 02, `prompt.model` placement, `gather_info`,
`initial_step`, `mcp_servers`, multi-language `internal_fillers`) were left alone and are listed
per recipe below. Recipes 21, 22 and 26 had nothing to fix.

Independent verification after all agents finished: every recipe suite passes (33 suites, 0
failures; 21, 22 and 26 have no tests or were untouched), `scripts/check_readme.py` and
`scripts/validate_manifests.py` pass for all 37 recipes, and every dump validates against the
platform schema except on the SDK-owned keys above. Diff: 82 files, +1460 / -239, uncommitted.
Two `app.py` files were already over the 220-line CI warning and grew: 16 (278 to 297) and
24 (226 to 235). Each recipe now has a gitignored `.venv`.

## 02-product-docs-hotline
changed: nothing
skipped: search_docs required-list ERROR is SDK-owned (native_vector_search skill); SEARCH_COUNT INFO is a handler change
tests: 15 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 80 lines

## 03-front-desk-receptionist
changed: app.py (+27/-4), config.py (+3/-1), tests/test_tools.py (+27/-2)
applied: billing Role now requires get_invoice, read the amount back, and an explicit yes before issue_refund; plan and service enums built from the data files; invoice_id pattern ^(INV-)?[0-9]{4}$ on both tools with ask descriptions; open_ticket.summary asks for the caller's own words; three governance tests including a parametrized missing-arg test over all five tools.
skipped: none (no ERROR rows)
tests: 26 passed ; validate_swml: fails only on the pre-existing SDK context shapes (enter_fillers map, context-level valid_contexts/pom); all function schemas clean ; readme: ok ; manifest: ok ; app.py: 188 lines

## 04-hiring-phone-screen
changed: README.md (+5/-3), config.py (+5/-1), tests/fixtures/global_data.json, tests/test_tools.py (+10)
applied: gather question earliest_start now carries a prompt pinning YYYY-MM-DD and asking which year if only a weekday or month/day is given; fixture updated; README notes the change and lists prompt among the QUESTIONS knobs; governance test added.
skipped: none
tests: 13 passed ; validate_swml: fails only on SDK-emitted gather_info (both variants) ; readme: ok ; manifest: ok ; app.py: 105 lines

## 05-package-tracking-line
changed: README.md, app.py, tests/golden/track_package.json, tests/test_tools.py (4 files, +33/-7)
applied: tracking_number description ("digits only ... Ask the caller if they don't provide it") and pattern ^[0-9]+$, set after to_swaig_function() in a new track_package_function() helper that the agent, golden test and simulator all use; golden file and README YAML block updated; governance test added.
skipped: none
tests: 13 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 62 lines

## 06-movie-showtimes-hotline
changed: showtimes.swml.yaml, tests/test_swml.py (+10/-2)
applied: Rules bullet now declines "any day other than today"; governance test added.
skipped: none
tests: 13 passed ; validate_swml: ok (on the YAML) ; readme: ok ; manifest: ok

## 07-trivia-hotline
changed: app.py, tests/test_tools.py (+18/-1)
applied: submit_answer.answer description: verbatim caller words, only after the caller has spoken, ask and wait if not, never supply an answer; governance test added.
skipped: none
tests: 25 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 151 lines

## 08-bank-balance-line
changed: app.py (+34/-11), tests/test_tools.py (+38)
applied: date_of_birth format: date with a convert-from-spoken description; account_number pattern ^[0-9]+$; transaction_id pattern ^T-[0-9]+$ pointing at list_transactions; open_dispute now refuses a blank reason and writes nothing; list_transactions.count default 3 with range built from config; account_menu step says list, ask which and why, then open_dispute; three tests added.
skipped: none
tests: 22 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 211 lines

## 09-insurance-claim-intake
changed: README.md (+3), app.py (+3), tests/test_answers.py, tests/test_tools.py (+16)
applied: promise_callback.preferred_time description asks for the caller's words (no example to echo); README notes the gather_info validator gap; governance test added.
skipped: check_* and submit_claim pass-through params (clean by design)
tests: 66 passed ; validate_swml: fails only on gather_info and prompt.model (SDK) ; readme: ok ; manifest: ok ; app.py: 198 lines

## 10-utility-bill-payment-line
changed: app.py (+10), tests/test_tools.py (+22)
applied: service_zip pattern ^[0-9]{5}$ and handler now strips to the first five digits (ZIP+4 and spoken digits verify); account_number pattern ^[0-9]{6}$; both ask; three tests added.
skipped: none
tests: 33 passed ; validate_swml: ok (plain and pay_ref variant) ; readme: ok ; manifest: ok ; app.py: 191 lines

## 11-collections-agent
changed: app.py (+29/-9), tests/test_tools.py (+18)
applied: propose_plan.months "never compute it from the balance", monthly_amount asks; postal_code pattern ^[0-9]{5}$; reference description states two letters + five digits; escalate.reason described; negotiate step asks one at a time and never works a value out from the balance; governance test added; policy-leak test still passes.
skipped: two INFO rows (handler short-circuit, hardship step text restructuring)
tests: 26 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 193 lines

## 12-medical-appointment-line
changed: README.md (1 line), app.py (+24/-5), tests/test_tools.py (+31/-1)
applied: find_slots.day enum derived from the slot file (Monday-Friday) with ask description; slot_id pattern ^S-[0-9]{4}$ on book_slot and hold_slot; _claim now refuses an empty slot_id with no actions; schedule_limited (and schedule) step text asks which day and forbids picking; record_consent.answer says ask; README example uses the enum casing; two tests added.
skipped: today's-weekday injection INFO (behaviour)
tests: 29 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 206 lines

## 13-lead-qualification-line
changed: app.py (+22/-10), tests/test_tools.py (+25)
applied: all four parameter descriptions now say "as stated by the caller ... Ask if not provided" (budget: send 0 only if the caller says no budget; months: encoding table built from config, never infer); qualify step: ask for four things one question at a time, call a tool only with a value the caller stated, never an inference from how they want to be marked; record_need refuses an empty need; two tests added.
skipped: prompt.model (SDK-owned)
tests: 36 passed ; validate_swml: fails only on prompt.model (SDK) ; readme: ok ; manifest: ok ; app.py: 135 lines

## 14-appointment-reminder-caller
changed: app.py (+11/-3), tests/test_tools.py (+17)
applied: new_start pattern YYYY-MM-DD HH:MM with ask-for-date-and-time, read back, never-assume-today description; manage step asks one at a time; configure() sets params.local_tz from the contact's timezone (every CSV row has one); governance test added.
skipped: none
tests: 26 passed ; validate_swml: ok (plain and appt variant) ; readme: ok ; manifest: ok ; app.py: 155 lines

## 15-support-line-with-callback
changed: app.py (+6/-3), tests/test_tools.py (+21/-2)
applied: ERROR fixed: request_human now requires both issue and summary (no store write, no connect, no step change when blank); preferred_time description asks and says own words; parametrized test plus governance test.
skipped: none
tests: 14 passed ; validate_swml: ok (all three variants) ; readme: ok ; manifest: ok ; app.py: 138 lines

## 16-travel-concierge
changed: README.md (1 line), app.py (+25/-8), tests/test_tools.py (+24)
applied: ERROR fixed: travelers int() wrapped in try/except so "two" gets the ask-how-many reply instead of a crashed call; destination enum from destinations.json on both tools; travelers "1 to 6, never assume one"; month enum of twelve months, never assume the current month; explore step asks one at a time and reads back; blank month now refused (same class, not in report); README example casing; four new handler cases plus governance test.
skipped: BookingDesk prompt.model (SDK-owned)
tests: 30 passed ; validate_swml: concierge ok; booking fails only on prompt.model (SDK) ; readme: ok ; manifest: ok ; app.py: 297 lines (was 278, over the 220 CI warn)

## 17-customer-survey-caller
changed: README.md, app.py (+73/-?), tests/test_tools.py (3 files, +110/-23)
applied: both ERRORs fixed: log_response now has a required list and a shared ANSWER_PARAMS schema; validate_response is overridden in SurveyCaller with the same schema and the recipe's normalize(), so both tools agree on spoken numbers; handler refuses missing question_id/response and writes nothing; question_id enum from config.QUESTIONS; response description says answer exactly as spoken, never fill in, ask if not answered; README updated; four tests.
skipped: none
tests: 38 passed ; validate_swml: ok (plain and customer variant) ; readme: ok ; manifest: ok ; app.py: 181 lines

## 18-drive-thru-order-taker
changed: README.md, app.py (+66/-?), tests/test_tools.py (3 files, +102/-20)
applied: MENU loaded at module level; enums for item, size, side, drink and modifiers built from it; add_item descriptions ask and never assume size/side/drink; modify_item gets its own CHANGE_PARAMS ("omit to keep the current"); accept_substitute.choice points at pending.options; take_order step asks before add_item and never fills in; README sentence on menu-derived enums; four governance tests.
skipped: none
tests: 27 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 218 lines

## 19-answering-service
changed: app.py (+14/-6), tests/test_tools.py (+22)
applied: callback_number pattern ^\+?[0-9]{7,15}$ plus "never assume it is the number they called from"; handler re-asks when fewer than 7 digits; name and message descriptions ask (message verbatim because the urgency check matches words); intake step asks one at a time and never fills in a value; two tests added.
skipped: none
tests: 18 passed ; validate_swml: ok (after-hours, office, default) ; readme: ok ; manifest: ok ; app.py: 140 lines

## 20-absence-reporting
changed: app.py (+7/-1), config.py (+13/-7), slots.py (+10/-1), tests/test_tools.py (+21)
applied: org_type enum ["school","work"] derived from the one_of validator's choices via a slot_schema helper; id description states the exact shape; start/end_date descriptions say pass the caller's exact words, never convert to YYYY-MM-DD, never assume today; parse_date accepts ISO dates from the model (verified with swaig-test --exec); name/reason descriptions ask; three tests added.
skipped: prompt.model (SDK-owned); id pattern (handler already enforces shape); TZ INFO and done-step INFO (behaviour)
tests: 38 passed ; validate_swml: fails only on ai.prompt.model (SDK) ; readme: ok ; manifest: ok ; app.py: 123 lines

## 23-sales-call-copilot
changed: app.py (+3/-1), tests/test_tools.py (+11)
applied: flag_objection.customer_quote description: most recent customer words, exactly as spoken, never paraphrased or the rep's; governance test pins it (no "ask" assertion: the sidecar cannot ask).
skipped: none
tests: 25 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 187 lines

## 24-support-copilot-that-acts
changed: app.py (+12/-3), config.py (+4/-2), tests/test_tools.py (+26)
applied: ERROR fixed: issue_credit refuses an empty reason (refused card, nothing written to the ledger) with tests for absent and whitespace reason; SIDECAR_PROMPT only allows issue_credit for a specific dollar amount the rep said and tells the rep to state one otherwise; amount description forbids computing/converting; shared order_id description says pass digits as heard and never guess; reason description text-only; governance test added.
skipped: none
tests: 26 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 235 lines (was already 226, over the 220 CI warn line)

## 25-win-loss-analyzer
changed: extraction.py (+3/-1), tests/test_tools.py (+15)
applied: POST_PROMPT last line now scopes null/[] to competitor/objections and says outcome is always one of the OUTCOMES ("no_decision" if undecided); count built from config. New governance test pins the post_prompt text against extraction.SCHEMA.
skipped: none
tests: 20 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 70 lines

## 26-compliance-call-monitor
changed: nothing (no findings)

## 27-sms-concierge
changed: concierge.py, tests/test_recipe.py (+48/-8)
applied: amenity enum from data/amenities.json at module level plus ask description; request_service.notes asks for the wake-up/late-checkout time; concierge step text says to get the time before logging; verify_guest.room pattern ^[0-9]{1,5}$ and ask; last_name and service descriptions say ask; two governance tests added.
skipped: none (no ERROR rows)
tests: 26 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 115 lines (concierge.py 145)

## 28-website-chat-agent
changed: concierge.py, tests/test_recipe.py (+48/-8), byte-identical to 27 (cmp confirmed)
applied: same as 27
tests: 21 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 85 lines

## 29-appointment-confirmation-sms
changed: app.py (+22/-6), tests/test_recipe.py (+46/-2)
applied: ERROR fixed: book_appointment refuses a blank name (no row, no SMS, no step change) with a parametrized test; reschedule step asks for new date then time and the handler refuses the current slot; SLOT.date format: date and SLOT.time HH:MM pattern with ask/never-assume-today descriptions; book step asks one at a time; two governance tests.
skipped: initial_step validator failure (SDK-owned)
tests: 21 passed ; validate_swml: default ok, booking variant fails only on initial_step (SDK) ; readme: ok ; manifest: ok ; app.py: 219 lines

## 30-calendar-assistant-over-mcp
changed: app.py (+8/-3), mcp_calendar.py (+19/-8), tests/test_tools.py (+30)
applied: Rules now ask the caller which day, never assume today, use get_today only to resolve relative days; book and move rules ask for the day, offer at most three slots, ask which one; "Ask what the visit is for before booking"; MCP server TOOLS: date format: date, start/new_start pattern YYYY-MM-DD HH:MM, shared attendee wording on book and lookup, meeting_id pattern, title asks; two governance tests (one reads tools/list from the reference server).
skipped: get_today TZ INFO (behaviour); mcp_servers validator failure (SDK-owned)
tests: 22 passed ; validate_swml: fails only on ai.SWAIG.mcp_servers (SDK) ; readme: ok ; manifest: ok ; app.py: 99 lines
notes: the "To move" rule got the same ask-for-the-day treatment as "To book" (not in the report's rows; same trap)

## 31-give-claude-a-phone-number
changed: app.py (+40/-8), tests/test_tools.py (+38/-1)
applied: book_callback.when pattern YYYY-MM-DD HH:MM with a 24-hour, ask-for-day-then-time, never-assume-today description; help step asks one at a time and states the callback window built from config; lookup_customer.phone pattern ^(\+?1)?\d{10}$ and "never use the caller ID"; account_id description points at lookup_customer; reason description asks; three governance tests including one proving /mcp serves the same schemas as voice.
skipped: none (no ERROR rows)
tests: 23 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 154 lines

## 32-order-status-line
changed: app.py (+25/-7), tests/test_tools.py (+32)
applied: request_refund.reason asks for the caller's own words and the handler now refuses a blank reason (nothing written to credits.jsonl); order_status step asks why before request_refund; postal_code pattern ^\d{5}$ and order_number pattern ^\d+$ with ask descriptions; verify step asks one at a time; three tests added; banned-words governance test still passes.
skipped: none
tests: 15 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 164 lines

## 33-agency-answering-service
changed: app.py (+68/-16), tests/test_tools.py (+54)
applied: both ERRORs fixed: emergency must be a real boolean or the handler asks (no routine ticket for a missing flag); an ask_for() helper enforces every required field on the four record-writing tools (nothing written when blank); dispatch_technician required is now ["emergency"] with address/issue guarded on the non-emergency branch; callback_number pattern plus "never assume it is the number they are calling from"; descriptions on every property; check_hours.day enum; Rules bullet in every tenant ("ask for each one and read numbers back. Never fill in a value the caller did not give"); INFO rows applied as text; governance test over all four tenant dumps.
skipped: none
tests: 47 passed ; validate_swml: ok (4/4 tenants) ; readme: ok ; manifest: ok ; app.py: 218 lines (2 under the CI warn line)

## 34-stock-quote-line
changed: skills/stock_quote/skill.py (+28/-3), tests/test_tools.py (+23/-1)
applied: stock-plan prompt now names its only ticker; ticker enum from the watchlist on that line; ticker pattern equals the handler's regex on both tools with ask descriptions (watchlist variant says pass it exactly, never guess another); skill-config watchlist gets items; governance test over both agent dumps.
skipped: none
tests: 18 passed ; validate_swml: ok (2/2) ; readme: ok ; manifest: ok ; app.py: 54 lines (skill.py 173)

## 35-bilingual-support-line
changed: app.py (+12/-2), tests/test_tools.py (+10)
applied: lookup_account.account_number pattern ^[0-9]{6}$ and zip pattern ^[0-9]{5}$, both with "Ask if not provided; never guess it" descriptions; governance test added. Handler unchanged (still digit-strips).
skipped: internal_fillers validator failure (schema-owned)
tests: 14 passed ; validate_swml: fails only on ai.SWAIG.internal_fillers (SDK) ; readme: ok ; manifest: ok ; app.py: 140 lines

## 36-voice-latency-lab
changed: app.py (+11/-2), tests/test_tools.py (+15)
applied: check_hours.day enum from DAYS plus ask/never-assume-today description; answer step text now asks which day when none is named; two governance tests; all-configs-identical test still passes.
skipped: prompt.model validator failure (schema-owned); live fixture recordings left untouched
tests: 26 passed ; validate_swml: fails only on ai.prompt.model in all 5 variants (SDK) ; readme: ok ; manifest: ok ; app.py: 94 lines

## _template
changed: app.py (+6/-1), tests/test_tools.py (+11/-1)
applied: check_hours.day enum from DAYS plus "Ask if not provided; never assume today" description; exemplary governance test for clones. new_recipe.sh unaffected.
skipped: none
tests: 6 passed ; validate_swml: ok ; readme: ok ; manifest: ok ; app.py: 76 lines

