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
