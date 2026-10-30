# DataMap functions

A DataMap function is a SWAIG function that runs on SignalWire instead of on your server. You describe an HTTP request and how to turn the reply into words, and SignalWire makes the request during the call.

A DataMap function has:

- `webhooks`: one or more HTTP requests. The URL can include the function's arguments, such as `${args.city}`.
- `output`: the response to give the model when the request succeeds. It can use fields from the reply, such as `${response.temperature}`.
- `expressions`: optional pattern matches on the arguments, for answers that need no HTTP request at all.
- `foreach`: optional, to turn an array in the reply into one string.

If every webhook fails, the `fallback_output` is used instead, so the caller still hears a sensible answer.

Use DataMap for simple lookups against public JSON APIs. It needs no server, so it works inside a hosted SWML script. Use a webhook function when you need real code, such as a database query or a calculation.
