# The ai verb

The `ai` verb starts an AI agent on a call. The agent listens to the caller, thinks with a language model and answers with text to speech.

The main parameters are:

- `prompt`: the instructions the agent follows. It can be plain text or a structured prompt with sections.
- `post_prompt`: instructions for a summary produced when the call ends. Use `post_prompt_url` to have SignalWire send that summary to your server.
- `languages`: the language, the voice and the fillers the agent uses. For example, English with the voice `rime.spore`.
- `params`: tuning options, such as how long to wait for the caller to stop talking.
- `SWAIG`: the functions (tools) the agent is allowed to call.
- `global_data`: data that the prompt and functions can read as `${global_data.key}`.

The agent can only take actions through its functions. If a function is not listed in `SWAIG`, the model cannot call it.

## Steps

A prompt can define contexts and steps. Each step has its own instructions and its own list of allowed functions, so the agent can be given different tools at different points in the call.
