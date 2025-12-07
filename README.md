# Merlya

AI-powered infrastructure assistant.

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
