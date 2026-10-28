# MCP boundary

There is no MCP adapter. This directory has no `__init__.py`, so nothing importable promises one.

If one is added, it follows these rules:

- **Optional.** It lives in its own extra (for example `mcp`), and nothing outside this directory
  imports the MCP library. `import chemeascode` stays free of it.
- **The same functions.** Each tool calls the function the CLI command calls (in a domain,
  `project` or `foundation`). A tool parses its arguments and formats the result; it contains no
  engineering logic of its own.
- **Curated and read-mostly.** It exposes a chosen set, not every function: validation, rendering,
  queries over sheets and lists, stream tables, status. Agents still change a plant by editing
  its files, as they do today.
- **Schemas from the models.** Tool inputs and outputs take their JSON Schema from the pydantic
  models and dataclasses of the functions they wrap, so a host can catalogue them.
- **Findings unchanged.** Results carry the same findings (file, line, rule id, hint) and the
  source revision as the CLI's `--json` output.
- **Never pyDEXPI's MCP server or editor layer.** Neither is used or exposed here.

See [the architecture](../../../../docs/framework/architecture.md), section "MCP boundary".
