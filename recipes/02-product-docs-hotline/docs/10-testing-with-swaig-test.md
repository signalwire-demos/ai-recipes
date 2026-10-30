# Testing agents with swaig-test

The SDK installs a command line tool called `swaig-test`. It loads your agent file and lets you test it without making a phone call.

- `swaig-test app.py --list-tools` lists the tools and their parameters.
- `swaig-test app.py --dump-swml` prints the SWML the agent returns for a call. Add `--raw` for plain JSON you can pipe into `jq`.
- `swaig-test app.py --exec check_hours --day friday` runs one tool with the given arguments and prints the result.

Put every option before `--exec`, because the options after it are read as the tool's arguments.

You can also pass test data. `--custom-data` sets values such as `global_data`, and `--query-params` sets the query string, which is useful for agents that change per request.

A good test suite calls each handler directly with sample arguments and checks the actions it returns. Then it dumps the SWML and checks which tools exist in which step.
