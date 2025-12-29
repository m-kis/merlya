# CLI Reference

Reference for the `merlya` command-line interface.

## `merlya` (interactive REPL)

Start the interactive REPL (default mode).

```bash
merlya [--verbose] [-v|--version]
```

Options:

- `--verbose`: enable debug logging
- `-v`, `--version`: show version and exit

## `merlya run` (non-interactive / batch)

Execute a single command or a list of commands from a file.

```bash
merlya run [OPTIONS] [COMMAND]
```

Options:

- `-f`, `--file FILE`: load tasks from a YAML (`.yml/.yaml`) or text file
- `-y`, `--yes`: auto-confirm prompts (unsafe in production unless you trust inputs)
- `--format text|json`: output format (default: `text`)
- `-q`, `--quiet`: minimal output

Verbose logging:

```bash
merlya --verbose run "Check disk usage on web-01"
```

Exit codes:

- `0`: all tasks succeeded
- `1`: one or more tasks failed

See [Non-Interactive Mode](non-interactive.md) for allowed/blocked slash commands and task-file formats.

## `merlya config`

Manage configuration values stored in `~/.merlya/config.yaml`.

```bash
merlya config show
merlya config get <section.key>
merlya config set <section.key> <value>
```

Notes:

- Keys use the format `section.key` (exactly 2 segments), e.g. `model.provider` or `logging.console_level`.
- `llm.*` is accepted as an alias for `model.*` (legacy).
- `merlya config` does not store secret values; API keys are sourced from environment variables or the system keyring.

Examples:

```bash
merlya config set model.provider openrouter
merlya config set model.model amazon/nova-2-lite-v1:free
merlya config get model.provider
```

## REPL slash commands

Once inside the REPL, use slash commands like `/hosts`, `/ssh`, `/model`, `/mcp`, etc.
The full reference is in [Slash Commands (REPL)](../commands.md).

