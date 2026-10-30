# SWML basics

SWML (SignalWire Markup Language) describes what happens on a call. A SWML document is YAML or JSON. It has a `version` and a `sections` map. Execution starts in the `main` section and runs its verbs from top to bottom.

```yaml
version: 1.0.0
sections:
  main:
    - answer: {}
    - play:
        url: "say:Thanks for calling. Goodbye."
    - hangup: {}
```

## Common verbs

- `answer` answers the call.
- `play` plays audio files or text to speech. A `say:` URL speaks the text.
- `prompt` plays a prompt and collects digits or speech.
- `record_call` starts recording in the background.
- `connect` dials a phone number or SIP address and bridges the caller to it.
- `transfer` and `execute` move execution to another section or another SWML document.
- `ai` starts an AI agent on the call.
- `hangup` ends the call.

Variables use the `${...}` syntax. For example, `${call.from}` is the caller's number.

The SWML JSON schema describes every verb and parameter. Editors that support JSON Schema can use it to autocomplete and check SWML files.
