# SWAIG functions

SWAIG (SignalWire AI Gateway) is how an AI agent calls your code. Each SWAIG function has a name, a description and a JSON Schema for its arguments. When the model decides to use a function, SignalWire sends an HTTP POST to the function's webhook with the arguments and information about the call.

Your webhook answers with JSON. The `response` field is text the model reads. The optional `action` list tells SignalWire to do something on the call, for example:

- change to another step or context,
- update `global_data`,
- send an SMS,
- connect the caller to a phone number,
- start or stop a recording,
- hang up.

Because actions come from your code, your code decides when the call moves forward. The model only decides when to call the function.

## Security

The Agents SDK marks functions as secure by default. Each call gets a token, and a request to the function without the right token is refused. Use basic authentication on the SWML URL as well.
