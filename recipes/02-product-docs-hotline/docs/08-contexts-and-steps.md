# Contexts and steps

Contexts and steps turn an AI agent into a state machine that you define.

A step has instructions, a list of functions it may use, and a list of steps it may move to. A context groups steps. An agent with one context must name it `default`.

## Scoping tools to a step

`set_functions` lists the tools the model can call in a step. In the Python SDK, a step that does not call `set_functions` keeps the tools of the previous step. To give a step no tools at all, call `set_functions([])`.

## Who moves the call

`set_valid_steps` lists the steps the model may move to on its own. With an empty list, the model has no way to leave the step. Only a function handler can then move the call, by returning a change step action. This is how you make sure, for example, that a caller is verified before they reach the account menu.

## Ending the flow

`set_end(True)` marks a step as the last step of the flow. It does not hang up the call. To hang up, return a hangup action from a function.

## Isolated contexts

A context can be isolated, so the conversation history from other contexts is not carried in. Isolated contexts are useful for separate personas, such as sales and billing.
