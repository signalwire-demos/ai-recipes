# Spaces, projects and API credentials

A SignalWire Space is your own subdomain of SignalWire, such as `example.signalwire.com`. Everything you build lives in a Space: phone numbers, SWML scripts, AI agents, logs and billing.

Each Space has at least one project. A project has a Project ID and one or more API tokens. To find them, sign in to the Dashboard and open the API page. Copy the Project ID, the Space URL and an API token.

Treat the API token like a password. Keep it in an environment variable or a `.env` file that is never committed to version control. If a token leaks, delete it in the Dashboard and create a new one.

The SDKs and the REST API read three values:

- `SIGNALWIRE_PROJECT_ID`: the Project ID
- `SIGNALWIRE_API_TOKEN`: the API token
- `SIGNALWIRE_SPACE`: the Space URL, for example `example.signalwire.com`

REST requests use HTTP basic authentication, with the Project ID as the user name and the API token as the password.
