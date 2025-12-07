<p align="center">
  <img src="assets/logo.png" alt="Merlya Logo" width="120">
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

## Usage

```bash
merlya
```

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
