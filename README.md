<p align="center">
  <img src="https://raw.githubusercontent.com/m-kis/merlya/main/assets/logo.png" alt="Merlya Logo" width="120">
</p>

<h1 align="center">Merlya</h1>

<p align="center">
  <strong>AI-powered infrastructure assistant</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/merlya/"><img src="https://img.shields.io/pypi/v/merlya?color=%2340C4E0" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
  <a href="https://github.com/m-kis/merlya/actions"><img src="https://img.shields.io/github/actions/workflow/status/m-kis/merlya/ci.yml?branch=main" alt="CI"></a>
</p>

## Features

- Natural language infrastructure management
- SSH connection pooling with security hardening
- Host inventory management
- Health checks and monitoring
- Multi-language support (EN, FR)

## Installation

```bash
pip install -e ".[dev]"
```

### Optional extras

- Local intent router (ONNX): `pip install -e ".[router]"` (requires Python ≤ 3.13 while onnxruntime wheels land for 3.14).

## Usage

```bash
merlya
```

## Configuration notes

- API keys & keyring: Merlya stores provider keys in the system keyring (fallback in-memory if unavailable). Ensure `keyring` (and its backend on Linux) is installed in the same Python env.
- Router fallback model: default fallback is `openrouter:google/gemini-2.0-flash-lite-001`. Override with `MERLYA_ROUTER_FALLBACK=<provider:model>` or via the setup wizard.
- Local intent router (ONNX): if the ONNX model/tokenizer are missing, Merlya downloads them at first use. Without onnxruntime/tokenizers the router falls back to pattern matching and LLM routing.

## Development

```bash
# Run tests
pytest tests/ -v

# Lint
ruff check merlya/

# Type check
mypy merlya/
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## Issues & Feedback

Report bugs and request features on [GitHub Issues](https://github.com/m-kis/merlya/issues).

## License

[MIT](LICENSE)
