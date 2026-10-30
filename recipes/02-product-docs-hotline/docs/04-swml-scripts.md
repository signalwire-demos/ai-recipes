# Hosting SWML scripts in your Space

You do not need your own server to run SWML. A SWML script is a SWML document stored in your Space.

To create one in the Dashboard, open Resources, then SWML Scripts, and create a new script. Paste the YAML or JSON, give the script a name and save it. Then open a phone number and choose the script as the number's call handler.

You can also create SWML scripts with the REST API. Send the script name and its contents to the Fabric SWML scripts endpoint, authenticated with your Project ID and API token. This is useful when your setup is scripted or runs in CI.

A hosted script can still call your systems. The `ai` verb's DataMap functions make HTTP requests from SignalWire, so a script with no server can look up data from any public JSON API.

When to choose a hosted script instead of an SDK app: choose a script when the logic is fixed and fits in one document. Choose an SDK app when you need code, such as database lookups, per-call configuration or test coverage of your handlers.
