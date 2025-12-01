# CI/CD Pipeline

Documentation du pipeline CI/CD d'Merlya.

## Workflows GitHub Actions

### CI (`ci.yml`)

**Déclencheurs** : Push ou PR sur `main` / `dev`

| Job | Description | Python |
|-----|-------------|--------|
| `lint` | Vérification style avec ruff | 3.11 |
| `test` | Tests pytest avec coverage | 3.11, 3.12 |
| `typecheck` | Vérification types avec mypy | 3.11 |
| `build` | Build du package (dépend de lint+test) | 3.11 |

**Features** :
- Cache Poetry/pip pour builds rapides
- Matrix multi-Python (3.11, 3.12)
- Coverage reporting vers Codecov
- Exclusion des tests manuels

### Release (`release.yml`)

**Déclencheur** : Push d'un tag `v*`

| Job | Description |
|-----|-------------|
| `build` | Build wheel + sdist |
| `github-release` | Création automatique GitHub Release |
| `publish-pypi` | Publication PyPI (commenté, à activer) |

**Workflow de release** :
```bash
# 1. Merger dans main
git checkout main
git merge dev

# 2. Créer et pusher le tag
git tag v0.2.0
git push --tags

# 3. La release GitHub est créée automatiquement
```

### Dependabot (`dependabot.yml`)

- Mises à jour hebdomadaires des dépendances pip
- Mises à jour hebdomadaires des GitHub Actions
- Limite de 5 PRs ouvertes

## Configuration Locale

### Linting

```bash
# Installer ruff
pip install ruff

# Vérifier le code
ruff check merlya/

# Auto-fix les erreurs
ruff check merlya/ --fix
```

### Tests

```bash
# Installer les dépendances de dev
poetry install

# Lancer tous les tests auto
poetry run pytest tests/ -v --ignore=tests/test_*_manual.py

# Avec coverage
poetry run pytest tests/ -v --cov=merlya --cov-report=term

# Tests spécifiques
poetry run pytest tests/test_basic.py -v
poetry run pytest -k "test_triage" -v
```

### Type Checking

```bash
pip install mypy types-paramiko types-PyYAML types-requests
mypy merlya/ --ignore-missing-imports
```

## Structure des Tests

```
tests/
├── test_basic.py              # Tests unitaires de base
├── test_triage.py             # Tests du système de triage
├── test_rollback.py           # Tests de rollback
├── test_security.py           # Tests de sécurité
├── test_provisioning.py       # Tests de provisioning
│
├── test_ollama_manual.py      # [MANUAL] Tests Ollama
├── test_openrouter_manual.py  # [MANUAL] Tests OpenRouter
├── test_pivoting_manual.py    # [MANUAL] Tests pivoting SSH
└── test_model_override.py     # [MANUAL] Tests override modèle
```

### Types de Tests

| Type | Marker | CI | Description |
|------|--------|-----|-------------|
| Unit | - | ✅ Auto | Tests unitaires rapides |
| Integration | `@pytest.mark.integration` | ✅ Auto | Tests d'intégration mockés |
| Manual | `@pytest.mark.manual` | ❌ Exclus | Requièrent API keys ou infra |
| Slow | `@pytest.mark.slow` | ⏳ Option | Tests longs (>30s) |

### Exécuter les tests manuels

```bash
# Avec clé API OpenRouter
OPENROUTER_API_KEY="sk-or-..." poetry run pytest tests/test_openrouter_manual.py -v

# Avec Ollama local
OLLAMA_HOST="http://localhost:11434" poetry run pytest tests/test_ollama_manual.py -v
```

## Règles Ruff

Configuration dans `pyproject.toml` :

| Rule | Description | Status |
|------|-------------|--------|
| E | pycodestyle errors | ✅ Actif |
| W | pycodestyle warnings | ✅ Actif |
| F | Pyflakes | ✅ Actif |
| I | isort (imports) | ✅ Actif |
| B | flake8-bugbear | ✅ Actif |
| C4 | flake8-comprehensions | ✅ Actif |

**Ignorés temporairement** (tech debt) :
- E501 : Line too long
- E722 : Bare except
- E741 : Ambiguous variable name
- B007 : Loop variable unused
- B904 : raise from err

## Branch Protection (Recommandé)

### `main`
- ✅ Require PR before merging
- ✅ Require status checks: `lint`, `test`, `build`
- ✅ Require branches up to date
- ❌ Allow force pushes (désactivé)

### `dev`
- ✅ Require status checks: `lint`, `test`
- ✅ Allow force pushes (pour rebase)

## Badges

```markdown
[![CI](https://github.com/m-kis/merlya/actions/workflows/ci.yml/badge.svg)](https://github.com/m-kis/merlya/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/m-kis/merlya/branch/main/graph/badge.svg)](https://codecov.io/gh/m-kis/merlya)
```
