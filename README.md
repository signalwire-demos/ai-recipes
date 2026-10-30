# SignalWire AI Recipes

Small, complete, runnable SignalWire AI agents, one folder per recipe. Each recipe
shows one governance idea in code: a tool that only exists in one step, a handler that
moves the call, or data the model never sees. The model makes the conversation natural;
the code decides what happens.

Every recipe is self-contained: its own `requirements.txt` (pinned `signalwire-sdk==3.7.5`),
`.env.example`, tests, Dockerfile and a README with the same 7 sections. Third-party
systems are mocked under `data/`, so a clean clone runs with only a SignalWire Space.

## Recipes

The table is generated from each `recipe.yaml` by `python scripts/build_index.py`.
Don't edit it by hand.

<!-- recipes:start -->
| # | Recipe | Group | Size | Status | Channels | Primitives |
|---|---|---|---|---|---|---|
| 01 | [AI Restaurant Reservation Line](recipes/01-restaurant-reservation-line/) | A | S | ready | voice | contexts-steps, set_functions, valid_steps, swml_change_step, global_data, dynamic-config |
| 02 | [AI Product Docs Hotline](recipes/02-product-docs-hotline/) | A | S | ready | voice | native_vector_search, response_format_callback, sw-search, add_language |
| 03 | [AI Front Desk Receptionist](recipes/03-front-desk-receptionist/) | A | S | exists | voice | contexts-steps, isolated-contexts, valid_contexts, valid_steps, set_functions, add_language |
| 04 | [AI Hiring Phone Screen](recipes/04-hiring-phone-screen/) | A | S | ready | voice | contexts-steps, gather, set_functions, valid_steps, swml_change_step, global_data, dynamic-config, rest-dial |
| 05 | [AI Package Tracking Line](recipes/05-package-tracking-line/) | A | S | ready | voice | datamap, add_language |
| 06 | [AI Movie Showtimes Hotline](recipes/06-movie-showtimes-hotline/) | A | S | ready | voice | swml-script, ai-verb, datamap, datamap-foreach, datamap-expressions, fallback-output |
| 07 | [AI Trivia Hotline](recipes/07-trivia-hotline/) | A | S | ready | voice | contexts-steps, set_functions, valid_steps, swml_change_step, global_data, dynamic-config |
| 08 | [AI Bank Balance Line](recipes/08-bank-balance-line/) | B | M | ready | voice | contexts-steps, set_functions, valid_steps, swml_change_step, global_data, connect, progressive-trust |
| 09 | [AI Insurance Claim Intake](recipes/09-insurance-claim-intake/) | B | M | ready | voice | contexts-steps, gather, set_functions, valid_steps, global_data, hold, rpc_dial, execute_rpc, join_conference, swml_change_step |
| 10 | [AI Utility Bill Payment Line](recipes/10-utility-bill-payment-line/) | B | M | confirm | voice | contexts-steps, set_functions, valid_steps, swml_change_step, global_data, pay, record_call |
| 11 | [AI Collections Agent](recipes/11-collections-agent/) | B | M | ready | voice | contexts-steps, set_functions, valid_steps, swml_change_step, global_data, connect, authority-inversion |
| 12 | [AI Medical Appointment Line](recipes/12-medical-appointment-line/) | B | M | ready | voice | contexts-steps, set_functions, valid_steps, swml_change_step, global_data, record_call, post_prompt |
| 13 | [AI Lead Qualification Line](recipes/13-lead-qualification-line/) | B | M | ready | voice | contexts-steps, set_functions, valid_steps, swml_change_step, global_data, post_prompt |
| 14 | [AI Appointment Reminder Caller](recipes/14-appointment-reminder-caller/) | B | M | confirm | voice | contexts-steps, set_functions, valid_steps, swml_change_step, global_data, dynamic-config, rest-dial |
| 15 | [AI Support Line With Callback](recipes/15-support-line-with-callback/) | B | M | ready | voice | contexts-steps, set_functions, valid_steps, swml_change_step, global_data, connect, dynamic-config, rest-dial, agent-server |
| 16 | [AI Travel Concierge](recipes/16-travel-concierge/) | B | M | ready | voice | agent-server, swml_transfer, dynamic-config, contexts-steps, set_functions, valid_steps, swml_change_step, global_data |
| 17 | [AI Customer Survey Caller](recipes/17-customer-survey-caller/) | B | S | ready | voice | prefab, global_data, dynamic-config, rest-dial |
| 18 | [AI Drive-Thru Order Taker](recipes/18-drive-thru-order-taker/) | B | M | exists | voice | contexts-steps, set_functions, valid_steps, swml_change_step, global_data |
| 19 | [Answering Service](recipes/19-answering-service/) | B | M | proposed | voice, sms | dynamic-config, contexts-steps, set_functions, valid_steps, swml_change_step, connect, send_sms, global_data |
| 20 | [Absence Reporting Line](recipes/20-absence-reporting/) | B | S | proposed | voice | contexts-steps, set_functions, valid_steps, swml_change_step, global_data, add_language, grammar-filling |
| 21 | [AI Meeting Transcription Line](recipes/21-meeting-transcription-line/) | C | M | confirm | voice, web | swml-service, live_transcribe, live-events-webhook, transcript-consumer, sse |
| 22 | [AI Live Caption Display](recipes/22-live-caption-display/) | C | M | confirm | voice, web | swml-service, live_transcribe, live-events-webhook, transcript-consumer, sse, captions-page |
| 23 | [AI Sales Call Copilot](recipes/23-sales-call-copilot/) | C | L | blocked | voice, web | ai_sidecar, swml-service, swaig-functions, sidecar-callbacks, connect-verb, server-sent-events |
| 24 | [AI Support Copilot That Acts](recipes/24-support-copilot-that-acts/) | C | L | blocked | voice, web | ai_sidecar, swml-service, swaig-functions, handler-enforced-cap, sidecar-callbacks, connect-verb, server-sent-events |
| 25 | [AI Competitive Win/Loss Analyzer](recipes/25-win-loss-analyzer/) | C | M | ready | voice | contexts-steps, set_functions, valid_steps, post_prompt, on_summary, schema-validation |
| 26 | [AI Compliance Call Monitor](recipes/26-compliance-call-monitor/) | C | M | confirm | voice, sms | swml-service, live_transcribe, live-events-webhook, transcript-consumer, rule-engine, send_sms, alert-webhook |
| 27 | [AI SMS Concierge](recipes/27-sms-concierge/) | C | M | confirm | voice, sms | contexts-steps, set_functions, valid_steps, swml_change_step, global_data, ai-chat-client, laml-webhooks |
| 28 | [AI Website Chat Agent](recipes/28-website-chat-agent/) | C | M | confirm | voice, web | contexts-steps, set_functions, valid_steps, swml_change_step, global_data, ai-chat-gateway |
| 29 | [Appointment Confirmation SMS](recipes/29-appointment-confirmation-sms/) | C | M | proposed | voice, sms | contexts-steps, set_functions, valid_steps, swml_change_step, global_data, send_sms, dynamic-config, rest-dial, laml-webhooks |
| 30 | [AI Calendar Assistant Over MCP](recipes/30-calendar-assistant-over-mcp/) | D | M | ready | voice | mcp-client |
| 31 | [Give Claude a Phone Number](recipes/31-give-claude-a-phone-number/) | D | M | ready | voice, mcp | mcp-server, contexts-steps, set_functions, valid_steps, swml_change_step, global_data, connect |
| 32 | [AI Order Status Line](recipes/32-order-status-line/) | D | M | ready | voice | contexts-steps, set_functions, valid_steps, swml_change_step, global_data, connect, data-projection |
| 33 | [AI Answering Service for Agencies](recipes/33-agency-answering-service/) | D | L | ready | voice | dynamic-config, define_tool, add_swaig_query_params, global_data, connect, tenant-yaml |
| 34 | [AI Stock Quote Line](recipes/34-stock-quote-line/) | D | M | ready | voice | custom-skill, add_skill, add_skill_directory, agent-server |
| 35 | [AI Bilingual Support Line](recipes/35-bilingual-support-line/) | D | S | ready | voice | add_language, languages_enabled, internal-fillers, contexts-steps, set_functions, valid_steps, swml_change_step, global_data |
| 36 | [AI Voice Latency Lab](recipes/36-voice-latency-lab/) | D | L | confirm | voice | dynamic-config, set_prompt_llm_params, add_language, post_prompt, contexts-steps, set_functions, valid_steps, global_data |
| — | [Recipe Template (Office Hours Line)](recipes/_template/) | A | S | template | voice | contexts-steps, set_functions, valid_steps, swml_change_step, global_data |
<!-- recipes:end -->

## Run any recipe

```bash
git clone https://github.com/signalwire-demos/ai-recipes
cd ai-recipes/recipes/<nn-slug>
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt     # pins signalwire-sdk
cp .env.example .env                # fill in values
python app.py                       # serves SWML on :3000
ngrok http 3000                     # or: docker compose up
```

Then in the SignalWire Dashboard, point a phone number's call handler at
`https://USER:PASS@<tunnel>/`, where USER/PASS are `SWML_BASIC_AUTH_USER` and
`SWML_BASIC_AUTH_PASSWORD` from your `.env`.

Test without a phone:

```bash
pytest -q
swaig-test app.py --list-tools
swaig-test app.py --dump-swml --raw | jq '.sections.main[-1].ai.prompt.contexts'
```

## Repository layout

| Path | What it is |
|---|---|
| `recipes/<nn-slug>/` | One recipe. Start from `recipes/_template/` with `scripts/new_recipe.sh <nn-slug>` |
| `patterns/` | Snippets of 20 lines or fewer that recipes reuse (address, phone, date, slots, state machine) |
| `README-TEMPLATE.md` | The 7-section README every recipe follows |
| `recipe.schema.yaml` | JSON Schema for `recipe.yaml`; checked by `scripts/validate_manifests.py` |
| `docs/sdk-notes.md` | Verified SDK names and signatures for signalwire-sdk 3.7.5 |
| `docs/track-c-research.md` | What is documented today for live transcription, copilots, chat mode and `pay` |
| `NUMBERS.md` | The demo phone-number pool and which recipes use which number |
| `scripts/` | Tooling: new recipe, manifest/README checks, index builder, live-call slot and smoke call |

## Contributing

One recipe per pull request, on a branch named `recipe/<nn-slug>`. CI runs, for every
changed recipe: pytest, a `swaig-test` SWML dump, manifest and README checks, a line-count
warning above 220 lines of app code, and a secret scan. See `README-TEMPLATE.md` for the
definition of done.

Tooling scripts run from a root venv:

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
.venv/bin/python scripts/validate_manifests.py
.venv/bin/python scripts/build_index.py
```

## License

MIT
