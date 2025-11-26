# Guide de Test

## Structure des Tests

```
tests/
├── conftest.py                    # Fixtures et configuration pytest
│
├── test_basic.py                  # [UNIT] Tests unitaires de base
├── test_triage.py                 # [UNIT] Tests du système de triage P0-P3
├── test_rollback.py               # [UNIT] Tests de rollback et recovery
│
├── test_provisioning.py           # [INTEGRATION] Tests provisioning
├── test_cloud.py                  # [INTEGRATION] Tests cloud providers
├── test_knowledge_integration.py  # [INTEGRATION] Tests knowledge graph
│
├── test_ollama_manual.py          # [MANUAL] Tests avec Ollama local
├── test_openrouter_manual.py      # [MANUAL] Tests avec OpenRouter API
├── test_pivoting_manual.py        # [MANUAL] Tests pivoting SSH multi-hop
├── test_security_manual.py        # [MANUAL] Tests de sécurité avec infra réelle
├── test_smart_list_manual.py      # [MANUAL] Tests smart list
├── test_persistence_manual.py     # [MANUAL] Tests persistence mémoire
└── test_model_override.py         # [MANUAL] Tests override modèle LLM
```

## Types de Tests

### Tests Unitaires (Unit)
- **Exécution** : Automatique en CI
- **Durée** : < 1 seconde chacun
- **Dépendances** : Aucune externe (mockées)
- **Fichiers** : `test_basic.py`, `test_triage.py`, `test_rollback.py`

```bash
poetry run pytest tests/test_basic.py tests/test_triage.py -v
```

### Tests d'Intégration (Integration)
- **Exécution** : Automatique en CI
- **Durée** : < 30 secondes chacun
- **Dépendances** : Mockées ou services locaux
- **Marker** : `@pytest.mark.integration`

```bash
poetry run pytest -m integration -v
```

### Tests Manuels (Manual)
- **Exécution** : Manuel uniquement
- **Durée** : Variable
- **Dépendances** : API keys, infrastructure réelle
- **Convention** : Fichiers `*_manual.py`

```bash
# Avec OpenRouter
OPENROUTER_API_KEY="sk-or-..." poetry run pytest tests/test_openrouter_manual.py -v

# Avec Ollama
OLLAMA_HOST="http://localhost:11434" poetry run pytest tests/test_ollama_manual.py -v
```

### Tests Smoke
- **Exécution** : Rapide, premier check
- **Durée** : < 5 secondes total
- **Marker** : `@pytest.mark.smoke`

```bash
poetry run pytest -m smoke -v
```

## Markers Pytest

| Marker | Description | CI |
|--------|-------------|-----|
| `@pytest.mark.manual` | Requiert API keys ou infra | ❌ Skip |
| `@pytest.mark.slow` | Test long (>30s) | ⏳ Option |
| `@pytest.mark.integration` | Test d'intégration | ✅ Auto |
| `@pytest.mark.smoke` | Sanity check rapide | ✅ Auto |

## Commandes Utiles

```bash
# Tous les tests auto (exclut manual)
poetry run pytest tests/ -v --ignore=tests/test_*_manual.py

# Avec coverage
poetry run pytest tests/ -v --cov=athena_ai --cov-report=html

# Tests par marker
poetry run pytest -m "not manual" -v
poetry run pytest -m "smoke" -v
poetry run pytest -m "integration" -v

# Test spécifique
poetry run pytest tests/test_triage.py::test_p0_detection -v

# Tests avec pattern
poetry run pytest -k "triage" -v

# Verbose avec output capture disabled
poetry run pytest -v -s

# Derniers tests échoués
poetry run pytest --lf -v
```

## Écrire un Nouveau Test

### Test Unitaire

```python
# tests/test_example.py
import pytest
from athena_ai.module import function_to_test


def test_basic_functionality():
    """Test basic case."""
    result = function_to_test("input")
    assert result == "expected"


def test_edge_case():
    """Test edge case."""
    with pytest.raises(ValueError):
        function_to_test(None)
```

### Test avec Fixture

```python
def test_with_context(mock_context):
    """Test using mock context fixture."""
    from athena_ai.context.manager import ContextManager

    # mock_context is provided by conftest.py
    assert "web-prod-1" in mock_context["inventory"]
```

### Test Manuel

```python
# tests/test_feature_manual.py
import os
import pytest


@pytest.mark.manual
@pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY"),
    reason="Requires OPENROUTER_API_KEY"
)
def test_real_api_call():
    """Test with real API - manual only."""
    # This test requires actual API key
    pass
```

### Test d'Intégration

```python
@pytest.mark.integration
def test_component_integration(mock_ssh_manager):
    """Test component integration with mocked SSH."""
    # mock_ssh_manager mocks actual SSH calls
    result = some_operation()
    assert result.success
```

## Coverage

```bash
# Générer rapport HTML
poetry run pytest tests/ --cov=athena_ai --cov-report=html

# Ouvrir le rapport
open htmlcov/index.html

# Coverage minimum requis
poetry run pytest tests/ --cov=athena_ai --cov-fail-under=50
```

## CI Integration

Les tests sont exécutés automatiquement dans GitHub Actions :

1. **Push/PR** → `ci.yml` lance `lint`, `test`, `typecheck`, `build`
2. **Tests manuels** : Exclus via `--ignore=tests/test_*_manual.py`
3. **Coverage** : Uploadé vers Codecov (branche main)

## Debugging

```bash
# Entrer dans le debugger sur échec
poetry run pytest tests/test_basic.py -v --pdb

# Voir les logs
poetry run pytest tests/ -v --log-cli-level=DEBUG

# Traceback complet
poetry run pytest tests/ -v --tb=long
```
