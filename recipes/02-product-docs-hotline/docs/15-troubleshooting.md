# Troubleshooting calls to your agent

## The call is answered and then drops right away

Check the call logs in the Dashboard. A 401 error means SignalWire could not authenticate to your SWML URL. Make sure the user name and password in the number's call handler URL match `SWML_BASIC_AUTH_USER` and `SWML_BASIC_AUTH_PASSWORD`. If those variables are not set, the SDK generates a new random password every time it starts.

## The agent never calls my function

The function must be listed in the `SWAIG` section of the SWML and, if you use steps, in the current step's functions. Dump the SWML with `swaig-test app.py --dump-swml` and check. Also check that the description tells the model when to use the function.

## My function is called but the webhook fails

Secure functions need the per-call token that the SDK puts in the SWML. A plain request to the function URL without it is refused, so test functions with `swaig-test --exec` instead.

## The webhook URLs point at localhost

Set `SWML_PROXY_URL_BASE` to your public URL, such as your ngrok address, so the SDK builds public webhook URLs.
