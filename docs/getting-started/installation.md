# Installation

## Requirements

- Python 3.11 or higher
- pip (Python package manager)
- An LLM provider API key (OpenAI, Anthropic, or local Ollama)

## Install from PyPI

The recommended way to install Merlya is via pip:

```bash
pip install merlya
```

## Install from Source

For the latest development version:

```bash
git clone https://github.com/m-kis/merlya.git
cd merlya
pip install -e ".[dev]"
```

## Verify Installation

```bash
merlya --version
```

You should see output like:

```
merlya 0.6.0
```

## Shell Completion

=== "Bash"

    ```bash
    # Add to ~/.bashrc
    eval "$(_MERLYA_COMPLETE=bash_source merlya)"
    ```

=== "Zsh"

    ```bash
    # Add to ~/.zshrc
    eval "$(_MERLYA_COMPLETE=zsh_source merlya)"
    ```

=== "Fish"

    ```fish
    # Add to ~/.config/fish/completions/merlya.fish
    _MERLYA_COMPLETE=fish_source merlya | source
    ```

## Next Steps

- [Quick Start Guide](quickstart.md) - Get up and running in 5 minutes
- [Configuration](configuration.md) - Configure your LLM provider and settings
