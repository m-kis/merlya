# Lean Merlya - Architecture Decisions

> Document de suivi des choix architecturaux pour la nouvelle version de Merlya.
> Chaque décision est validée par l'utilisateur avant implémentation.

---

## 1. Framework Agent Core

**Décision** : PydanticAI

**Raisons** :
- Multi-provider LLM (OpenRouter, Anthropic, OpenAI, Ollama, LiteLLM, Groq)
- Type-safe avec validation Pydantic native
- MCP (Model Context Protocol) intégré nativement
- Human-in-the-loop pour approbation des actions critiques
- Durable execution (survit aux erreurs/restarts)
- Graph support via pydantic-graph pour workflows complexes
- Production stable (décembre 2025)
- "FastAPI feeling" - patterns familiers

**Alternatives considérées** :
- Claude Agent SDK : limité à Claude uniquement
- LangGraph : courbe d'apprentissage élevée
- CrewAI : moins flexible pour notre use case
- AutoGen : setup manuel complexe

**Date** : 2025-12-05

---

## 2. Système Providers LLM

**Décision** : Commande `/model` simplifiée, passthrough PydanticAI

**Sous-commandes conservées** :
| Commande | Description |
|----------|-------------|
| `/model provider <name>` | Changer de provider (openrouter, anthropic, openai, ollama, etc.) |
| `/model model <name>` | Changer de modèle |
| `/model show` | Afficher configuration actuelle |
| `/model test` | Tester la connexion/validité |

**Sous-commandes supprimées** :
- `/model temperature` - laissé aux defaults PydanticAI
- `/model max_tokens` - laissé aux defaults PydanticAI
- `/model list` - simplifié (pas de listing dynamique)

**Configuration Router (Intent Classifier)** :
| Commande | Description |
|----------|-------------|
| `/model router show` | Afficher config du router (local ou LLM) |
| `/model router local` | Forcer utilisation modèle embedding local |
| `/model router llm <model>` | Configurer LLM fallback pour routing |

**Principe** : Passthrough vers PydanticAI pour l'agent principal. Router configurable séparément.

**Date** : 2025-12-05

---

## 3. Interface Console (UI)

**Décision** : Rich avec rendu Markdown

**Exigences** :
- **Rich** pour le rendu console (panels, tables, syntax highlighting)
- **Rendu Markdown** natif pour les réponses LLM
- **Autocompletion** sur les commandes et arguments
- **Suggestion list** dynamique (comme V1)
- Support couleurs et styles

**Librairies** :
- `rich` - Rendu console enrichi
- `prompt_toolkit` - Autocompletion et input avancé

**Date** : 2025-12-05

---

## 4. Slash Commands REPL

### Commandes essentielles

| Commande | Décision | Notes |
|----------|----------|-------|
| `/help` | ✅ Garder | Aide contextuelle |
| `/exit` | ✅ Garder | Quitter proprement |
| `/new` | ✅ Garder | Nouvelle conversation |
| `/conv` | ✅ Garder | Gérer historique des conversations |
| `/reset` | ❌ Supprimer | Redondant avec `/new`. Si besoin d'un vrai reset, ce sera un reset complet (re-init config, clés, etc.) |

### Variables et Secrets

| Commande | Décision | Notes |
|----------|----------|-------|
| `/variable` | ✅ Garder (V1 style) | Mode env key-value, support `@varname` dans prompts |
| `/secret` | ✅ Garder (hybride) | Keyring pour persistence sécurisée, fallback in-memory si keyring indisponible |

**Secrets - Stratégie de persistence** :
1. Tenter keyring système (macOS Keychain, Windows Credential Manager, Linux Secret Service)
2. Si indisponible → fallback in-memory avec warning
3. Option future : fichier chiffré local

### Infrastructure

| Commande | Décision | Notes |
|----------|----------|-------|
| `/hosts` | ✅ Garder (simplifié) | CRUD basique : list, add, show, edit, delete, tags. Seule commande pour ajouter des hôtes. |
| `/ssh` | ✅ Garder (complet) | MFA/2FA, jump hosts (pivot), clés privées, passphrase. Lie un hôte à sa config SSH. |
| `/scan` | ✅ Garder (V2 style) | Scan local uniquement, auto-import intelligent, relations auto-détectées. Stockage en base. |
| `/context` | ❌ Supprimer | Pas utile pour l'utilisateur final. Info intégrée dans `/scan` si besoin. |
| `/enrich` | ❌ Supprimer | Intégré dans `/hosts` ou scan automatique à la connexion SSH. |

**SSH - Fonctionnalités requises** :
- Support MFA/2FA (TOTP, push, etc.)
- Jump hosts / Bastion (pivot via un hôte intermédiaire)
- Chargement clé privée avec gestion passphrase
- Suggestion d'hôtes via `@` (autocompletion)
- UX intuitive : `/ssh connect @web-01` ou `/ssh exec @web-01 "uptime"`
- Scan santé rapide à la connexion (avant actions)

**Hosts + SSH - Workflow** :
1. `/hosts add web-01` → Ajoute l'hôte (hostname, IP basique)
2. `/ssh config @web-01` → Configure SSH (clé, user, port, jump host)
3. `/ssh connect @web-01` → Connexion avec scan santé automatique

### Session et Stats

| Commande | Décision | Notes |
|----------|----------|-------|
| `/session` | ⚠️ Nice to have | save/load/export - Implémenter plus tard si besoin |
| `/stats` | ✅ Garder | Utiliser télémétrie native PydanticAI (logfire) |

### Commandes avancées (Agents modulaires)

| Commande | Décision | Notes |
|----------|----------|-------|
| `/cicd` | 🔌 Agent modulaire | Plugin ajouté au besoin (GitHub Actions, GitLab CI, etc.) |
| `/kube` | 🔌 Agent modulaire | Plugin Kubernetes |
| `/docker` | 🔌 Agent modulaire | Plugin Docker/containers |
| `/ansible` | 🔌 Agent modulaire | Plugin Ansible |
| `/terraform` | 🔌 Agent modulaire | Plugin Terraform |

**Architecture agents modulaires** : Système de plugins chargés dynamiquement. Non inclus dans le core.

### Configuration et Logs

| Commande | Décision | Notes |
|----------|----------|-------|
| `/mcp` | ✅ Garder | Compatibilité native PydanticAI |
| `/log` | ✅ Garder | Config verbosité, chemin, rotation |
| `/config` | ❌ Supprimer | Trop générique. Config via fichier ou commandes spécifiques. |
| `/language` | ✅ Garder | i18n fr/en, convention V2 (JSON locales) |

**Date** : 2025-12-05

---

## 5. Internationalisation (i18n)

**Décision** : Convention V2 avec fichiers JSON

**Structure** :
```
lean_merlya/
  i18n/
    locales/
      en.json
      fr.json
    loader.py
```

**Principes** :
- Fichiers JSON par langue
- Clés hiérarchiques (`commands.hosts.added`, `errors.ssh.connection_failed`)
- Fonction `t('key')` pour récupérer la traduction
- Langue par défaut : système ou config utilisateur
- Validation des clés manquantes au démarrage (mode dev)

**Date** : 2025-12-05

---

## 6. Logging

**Décision** : Système configurable avec conventions emojis

### Librairie

**loguru** - Simple, rotation intégrée, coloration native

### Options configurables

- Niveau de verbosité (debug, info, warn, error)
- Chemin du fichier log
- Rotation (taille max, nombre de fichiers)
- Format (console coloré vs fichier JSON)

### Convention Emojis (migré de V2)

| Catégorie | Emoji | Usage |
|-----------|-------|-------|
| Succès | ✅ | Opération réussie |
| Erreur | ❌ | Opération échouée |
| Warning | ⚠️ | Inattendu mais récupérable |
| Info | ℹ️ | Information générale |
| Thinking | 🧠 | Traitement/raisonnement AI |
| Exécution | ⚡ | Exécution de commande |
| Sécurité | 🔒 | Messages liés à la sécurité |
| Question | ❓ | Input utilisateur requis |
| Host | 🖥️ | Hôte/serveur |
| Network | 🌐 | Opérations réseau |
| Database | 🗄️ | Opérations BDD |
| Timer | ⏱️ | Durée/timing |
| Critical | 🚨 | Alerte critique (P0/P1) |
| Scan | 🔍 | Scan/découverte |
| Config | ⚙️ | Configuration |
| File | 📁 | Opérations fichiers |
| Log | 📋 | Logs/historique |

### Utilisation dans le code

```python
from loguru import logger

# Messages utilisateur (avec emojis)
logger.info("✅ Connexion SSH établie")
logger.warning("⚠️ Timeout proche, rafraîchissement...")
logger.error("❌ Échec authentification MFA")
logger.debug("🔍 Scan réseau en cours...")

# Messages techniques (sans emojis, fichier log uniquement)
logger.debug("SSH handshake completed in 234ms")
logger.trace("Raw response: {}", raw_data)
```

### Configuration par défaut

```python
from loguru import logger
import sys

# Console : coloré avec emojis
logger.add(
    sys.stderr,
    format="<level>{message}</level>",
    level="INFO",
    colorize=True,
)

# Fichier : structured JSON (pas d'emojis)
logger.add(
    "~/.merlya/logs/merlya.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}",
    level="DEBUG",
    rotation="10 MB",
    retention="7 days",
    compression="gz",
)
```

**Date** : 2025-12-05

---

## 7. Documentation et Conventions de Développement

**Décision** : Créer CONTRIBUTING.md avec conventions migrées de V2

### Principes SOLID (adaptés Python)

#### Single Responsibility Principle (SRP)

```python
# Good: Classes dédiées
class RiskAssessor:
    """Évalue uniquement le risque."""
    pass

class AuditLogger:
    """Log uniquement les événements d'audit."""
    pass

# Bad: God classes
class ServerManager:
    """Gère, exécute, log, valide... tout en un."""
    pass
```

#### Dependency Inversion Principle (DIP)

```python
# Good: Injection de dépendances
from abc import ABC, abstractmethod

class LLMRouter(ABC):
    @abstractmethod
    async def chat(self, messages: list[Message]) -> Response:
        pass

class BaseAgent:
    def __init__(
        self,
        context: SharedContext,
        llm: LLMRouter | None = None,
        executor: ActionExecutor | None = None,
    ):
        self.context = context
        self.llm = llm or create_default_llm()
        self.executor = executor or create_default_executor()
```

### Design Patterns

#### Singleton avec reset pour tests

```python
class SSHPool:
    _instance: "SSHPool | None" = None

    def __new__(cls) -> "SSHPool":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset pour les tests."""
        cls._instance = None
```

#### Registry Pattern

```python
from typing import TypeVar, Generic

T = TypeVar("T")

class Registry(Generic[T]):
    def __init__(self):
        self._items: dict[str, type[T]] = {}

    def register(self, name: str, cls: type[T]) -> None:
        self._items[name] = cls

    def get(self, name: str, **kwargs) -> T:
        return self._items[name](**kwargs)
```

### Sécurité

```python
from pydantic import BaseModel, field_validator

class CommandInput(BaseModel):
    target: str
    command: str
    timeout: int = 60

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        if not v or ".." in v or v.startswith("/"):
            raise ValueError("Invalid target")
        return v

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if v < 1 or v > 3600:
            raise ValueError("Timeout must be 1-3600")
        return v
```

### Standards Qualité Code

| Métrique | Cible | Enforcement |
|----------|-------|-------------|
| Max lignes/fichier | 600 | Code review |
| Max lignes/fonction | 50 | Code review |
| Max params/fonction | 4 | Ruff + review |
| No `Any` type | Requis | mypy strict |
| No `print()` | Requis | Ruff (use logger) |
| Inputs validés | Requis | Pydantic |
| Couverture tests | > 80% | CI |

### Convention Commits

```text
<type>(<scope>): <description>

Types:
- feat: Nouvelle fonctionnalité
- fix: Correction bug
- docs: Documentation
- refactor: Refactoring
- test: Tests
- chore: Maintenance

Exemples:
feat(repl): add /export command
fix(ssh): handle timeout gracefully
docs(readme): update installation
```

### Tests

```python
import pytest
from lean_merlya.ssh import SSHPool

@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset tous les singletons entre les tests."""
    yield
    SSHPool.reset_instance()

async def test_ssh_execute_success(mock_ssh):
    pool = SSHPool()
    result = await pool.execute("host", "uptime")
    assert result.success
    assert result.exit_code == 0
```

**Date** : 2025-12-05

---

## 8. Intent Router (Classificateur)

**Décision** : Hybride local-first avec fallback LLM

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                       STARTUP                            │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              1. Capability Check                         │
│  - RAM disponible (min 512MB pour modèle)               │
│  - Fichiers modèle présents                             │
│  - Test de chargement                                   │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              2. Tools Availability Check                 │
│  - ddgs (DuckDuckGo Search)                             │
│  - LLM provider (API key valide)                        │
│  - SSH client disponible                                │
│  - Keyring accessible                                   │
└─────────────────────────────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
     [Machine capable]          [Machine limitée]
              │                         │
              ▼                         ▼
     Charger modèle local       Configurer LLM fallback
     (embedding ONNX)           (gpt-4o-mini ou autre)
              │                         │
              └────────────┬────────────┘
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    Intent Router                         │
│  Input → Classification → Mode + Tools actifs            │
└─────────────────────────────────────────────────────────┘
```

### Startup Health Checks

**Décision** : Vérification complète des capacités au démarrage

#### Catégories de checks

| Catégorie | Check | Critique | Fallback |
|-----------|-------|----------|----------|
| **Système** | RAM disponible | ❌ | Tier inférieur |
| **Système** | Espace disque (~500MB) | ❌ | Warning |
| **Recherche** | `duckduckgo-search` (ddgs) | ❌ | Désactiver web search |
| **LLM** | API key configurée | ✅ | Erreur startup |
| **LLM** | Provider accessible | ❌ | Warning + retry |
| **SSH** | Client SSH disponible | ❌ | Désactiver SSH tools |
| **Secrets** | Keyring accessible | ❌ | Fallback in-memory |
| **Router** | Modèle ONNX chargeable | ❌ | Fallback LLM |

#### Implémentation

```python
from dataclasses import dataclass, field
from enum import Enum
import shutil

class CheckStatus(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    DISABLED = "disabled"

@dataclass
class HealthCheck:
    name: str
    status: CheckStatus
    message: str
    critical: bool = False

@dataclass
class StartupHealth:
    checks: list[HealthCheck] = field(default_factory=list)
    capabilities: dict[str, bool] = field(default_factory=dict)

    @property
    def can_start(self) -> bool:
        """Vérifie si les checks critiques passent."""
        return not any(c.critical and c.status == CheckStatus.ERROR for c in self.checks)

async def run_startup_checks() -> StartupHealth:
    """Exécute tous les checks au démarrage."""
    health = StartupHealth()

    # 1. Check RAM
    health.checks.append(check_ram())

    # 2. Check recherche web (ddgs)
    health.checks.append(check_web_search())
    health.capabilities["web_search"] = health.checks[-1].status == CheckStatus.OK

    # 3. Check LLM provider
    health.checks.append(await check_llm_provider())

    # 4. Check SSH
    health.checks.append(check_ssh_available())
    health.capabilities["ssh"] = health.checks[-1].status == CheckStatus.OK

    # 5. Check Keyring
    health.checks.append(check_keyring())
    health.capabilities["keyring"] = health.checks[-1].status == CheckStatus.OK

    # 6. Check espace disque
    health.checks.append(check_disk_space())

    return health

def check_web_search() -> HealthCheck:
    """Vérifie que duckduckgo-search est disponible."""
    try:
        from duckduckgo_search import DDGS
        # Test rapide
        with DDGS() as ddgs:
            # Juste vérifier que ça s'initialise
            pass
        return HealthCheck(
            name="web_search",
            status=CheckStatus.OK,
            message="✅ DuckDuckGo Search disponible",
        )
    except ImportError:
        return HealthCheck(
            name="web_search",
            status=CheckStatus.DISABLED,
            message="⚠️ duckduckgo-search non installé - recherche web désactivée",
        )
    except Exception as e:
        return HealthCheck(
            name="web_search",
            status=CheckStatus.WARNING,
            message=f"⚠️ DuckDuckGo indisponible: {e}",
        )

def check_ssh_available() -> HealthCheck:
    """Vérifie que SSH est disponible."""
    try:
        import asyncssh
        # Vérifier que le client SSH système existe aussi
        if shutil.which("ssh"):
            return HealthCheck(
                name="ssh",
                status=CheckStatus.OK,
                message="✅ SSH disponible (asyncssh + client système)",
            )
        return HealthCheck(
            name="ssh",
            status=CheckStatus.WARNING,
            message="⚠️ asyncssh OK mais client SSH système absent",
        )
    except ImportError:
        return HealthCheck(
            name="ssh",
            status=CheckStatus.DISABLED,
            message="⚠️ asyncssh non installé - SSH tools désactivés",
        )

def check_keyring() -> HealthCheck:
    """Vérifie que le keyring est accessible."""
    try:
        import keyring
        # Test d'écriture/lecture
        keyring.set_password("merlya_test", "test", "test_value")
        value = keyring.get_password("merlya_test", "test")
        keyring.delete_password("merlya_test", "test")

        if value == "test_value":
            return HealthCheck(
                name="keyring",
                status=CheckStatus.OK,
                message="✅ Keyring accessible",
            )
        return HealthCheck(
            name="keyring",
            status=CheckStatus.WARNING,
            message="⚠️ Keyring ne retourne pas les bonnes valeurs",
        )
    except Exception as e:
        return HealthCheck(
            name="keyring",
            status=CheckStatus.WARNING,
            message=f"⚠️ Keyring indisponible ({e}) - fallback in-memory",
        )

async def check_llm_provider() -> HealthCheck:
    """Vérifie que le provider LLM est configuré et accessible."""
    config = load_config()

    if not config.model.api_key:
        return HealthCheck(
            name="llm_provider",
            status=CheckStatus.ERROR,
            message="❌ Aucune API key configurée",
            critical=True,
        )

    try:
        # Test ping rapide au provider
        # (implémentation dépend du provider)
        return HealthCheck(
            name="llm_provider",
            status=CheckStatus.OK,
            message=f"✅ {config.model.provider} accessible",
        )
    except Exception as e:
        return HealthCheck(
            name="llm_provider",
            status=CheckStatus.WARNING,
            message=f"⚠️ Provider inaccessible: {e} (retry au premier appel)",
        )

def check_disk_space() -> HealthCheck:
    """Vérifie l'espace disque disponible."""
    import shutil
    from pathlib import Path

    merlya_dir = Path.home() / ".merlya"
    merlya_dir.mkdir(parents=True, exist_ok=True)

    total, used, free = shutil.disk_usage(merlya_dir)
    free_mb = free // (1024 * 1024)

    if free_mb >= 500:
        return HealthCheck(
            name="disk_space",
            status=CheckStatus.OK,
            message=f"✅ Espace disque OK ({free_mb}MB libres)",
        )
    elif free_mb >= 100:
        return HealthCheck(
            name="disk_space",
            status=CheckStatus.WARNING,
            message=f"⚠️ Espace disque limité ({free_mb}MB libres)",
        )
    else:
        return HealthCheck(
            name="disk_space",
            status=CheckStatus.ERROR,
            message=f"❌ Espace disque insuffisant ({free_mb}MB libres)",
        )
```

#### Affichage au démarrage

```
🚀 Démarrage Merlya v0.1.0

📋 Health Checks:
  ✅ RAM: 8.2GB disponibles (tier: performance)
  ✅ LLM: anthropic/claude-3-5-sonnet accessible
  ✅ SSH: asyncssh + client système
  ✅ Keyring: macOS Keychain
  ✅ Web Search: DuckDuckGo
  ✅ Disk: 45GB libres

🧠 Router: gte-multilingual-base (768 dims)
⚡ Prêt en 1.2s

>
```

#### Commande `/health`

```bash
/health
# 📋 Health Status:
#   ✅ RAM: 8.2GB disponibles
#   ✅ LLM: anthropic accessible (latence: 234ms)
#   ✅ SSH: disponible
#   ✅ Keyring: macOS Keychain
#   ✅ Web Search: DuckDuckGo
#   ✅ Router: gte-multilingual-base (loaded)
#
# 🔧 Capabilities:
#   web_search: enabled
#   ssh: enabled
#   keyring: native
#   router: local (performance tier)
```

### First-Run Setup (Premier Démarrage)

**Décision** : Wizard de configuration interactif + scan local automatique

#### Workflow complet du premier démarrage

```
┌─────────────────────────────────────────────────────────┐
│                 PREMIER DÉMARRAGE                        │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│           1. Configuration LLM Provider                  │
│  - Sélection provider (OpenRouter, Anthropic, OpenAI...) │
│  - Saisie API key (stockée dans keyring)                │
│  - Choix du modèle par défaut                           │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│           2. Health Checks                               │
│  - RAM, Disk, SSH, Keyring, Web Search                  │
│  - Sélection tier embedding automatique                 │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│           3. Scan Local Sources                          │
│  - /etc/hosts                                           │
│  - ~/.ssh/config + ~/.ssh/known_hosts                   │
│  - Inventaires Ansible détectés                         │
│  - Fichiers custom (demandé à l'utilisateur)            │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│           4. Import Hosts via Brain (LLM)                │
│  - Parsing intelligent des fichiers                     │
│  - Extraction hostname, IP, user, port, metadata        │
│  - Affichage erreurs (lignes non parsées)               │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│           5. Persistance                                 │
│  - config.yaml (settings)                               │
│  - merlya.db (hosts, variables)                         │
│  - keyring (API keys, secrets)                          │
└─────────────────────────────────────────────────────────┘
```

#### Wizard de configuration LLM

```python
async def run_llm_setup_wizard(ui: ConsoleUI) -> LLMConfig:
    """Wizard interactif pour configurer le provider LLM."""
    ui.panel("""
    🔧 Configuration du Provider LLM

    Providers disponibles:
      1. OpenRouter (recommandé - multi-modèles)
      2. Anthropic (Claude direct)
      3. OpenAI (GPT models)
      4. Ollama (modèles locaux)
      5. LiteLLM (proxy universel)
    """, "⚙️ Setup")

    choice = await ui.prompt_choice(
        "Sélectionnez un provider",
        choices=["1", "2", "3", "4", "5"],
        default="1"
    )

    provider_map = {
        "1": ("openrouter", "OPENROUTER_API_KEY"),
        "2": ("anthropic", "ANTHROPIC_API_KEY"),
        "3": ("openai", "OPENAI_API_KEY"),
        "4": ("ollama", None),
        "5": ("litellm", "LITELLM_API_KEY"),
    }

    provider, env_key = provider_map[choice]

    # Demander API key si nécessaire
    if env_key:
        api_key = await ui.prompt_secret(f"🔑 Entrez votre {env_key}")
        secrets.set(env_key, api_key)

    # Sélection modèle par défaut
    default_models = {
        "openrouter": "anthropic/claude-3.5-sonnet",
        "anthropic": "claude-3-5-sonnet-20241022",
        "openai": "gpt-4o",
        "ollama": "llama3.2",
        "litellm": "gpt-4o",
    }

    model = await ui.prompt(
        "Modèle par défaut",
        default=default_models[provider]
    )

    return LLMConfig(provider=provider, model=model)
```

#### Scan local et détection des sources

```python
@dataclass
class InventorySource:
    name: str
    path: Path | None
    source_type: str  # "etc_hosts", "ssh_config", "ansible", "custom"
    host_count: int
    detected: bool

def detect_inventory_sources() -> list[InventorySource]:
    """Détecte les sources d'inventaire disponibles."""
    sources = []

    # 1. /etc/hosts
    etc_hosts = Path("/etc/hosts")
    if etc_hosts.exists():
        count = count_etc_hosts_entries(etc_hosts)
        sources.append(InventorySource(
            name="/etc/hosts",
            path=etc_hosts,
            source_type="etc_hosts",
            host_count=count,
            detected=True,
        ))

    # 2. SSH Config
    ssh_config = Path.home() / ".ssh" / "config"
    if ssh_config.exists():
        count = count_ssh_hosts(ssh_config)
        sources.append(InventorySource(
            name="SSH Config",
            path=ssh_config,
            source_type="ssh_config",
            host_count=count,
            detected=True,
        ))

    # 3. SSH Known Hosts
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    if known_hosts.exists():
        count = count_known_hosts(known_hosts)
        sources.append(InventorySource(
            name="Known Hosts",
            path=known_hosts,
            source_type="known_hosts",
            host_count=count,
            detected=True,
        ))

    # 4. Ansible inventories
    ansible_paths = [
        Path.home() / "inventory",
        Path.home() / "ansible" / "hosts",
        Path("/etc/ansible/hosts"),
        Path.cwd() / "inventory",
    ]
    for path in ansible_paths:
        if path.exists():
            count = count_ansible_hosts(path)
            if count > 0:
                sources.append(InventorySource(
                    name=f"Ansible ({path.name})",
                    path=path,
                    source_type="ansible",
                    host_count=count,
                    detected=True,
                ))

    return sources
```

#### Import intelligent via Brain (LLM)

Le Brain parse les fichiers non-standards et extrait les infos hosts :

```python
@dataclass
class ParsedHost:
    name: str
    hostname: str | None
    ip: str | None
    port: int | None
    username: str | None
    metadata: dict
    source_line: str  # Ligne originale pour debug

@dataclass
class ImportResult:
    imported: list[ParsedHost]
    failed: list[tuple[int, str, str]]  # (line_num, line, error)

async def import_hosts_with_brain(
    file_path: Path,
    file_format: str | None = None,
    brain: IntentRouter | None = None,
) -> ImportResult:
    """
    Import hosts depuis un fichier avec parsing intelligent.

    Si le format est inconnu, le Brain (LLM) analyse le contenu
    et extrait les informations host.
    """
    content = file_path.read_text()
    imported = []
    failed = []

    # Détection automatique du format
    if file_format is None:
        file_format = detect_file_format(file_path, content)

    # Formats connus : parsing direct
    if file_format in ["csv", "json", "yaml", "ansible_ini", "ssh_config"]:
        return parse_known_format(content, file_format)

    # Format inconnu : demander au Brain
    if brain:
        prompt = f"""
Analyse ce fichier d'inventaire et extrait les hosts.
Pour chaque ligne contenant un host, retourne:
- name: nom du host
- hostname: hostname ou IP
- ip: adresse IP si disponible
- port: port SSH si spécifié
- username: utilisateur si spécifié

Format de réponse JSON:
{{"hosts": [{{"name": "...", "hostname": "...", ...}}], "errors": [{{"line": 1, "content": "...", "reason": "..."}}]}}

Contenu du fichier:
```
{content}
```
"""
        response = await brain.llm.chat([{"role": "user", "content": prompt}])
        result = json.loads(response.content)

        for host_data in result.get("hosts", []):
            imported.append(ParsedHost(**host_data, source_line=""))

        for error in result.get("errors", []):
            failed.append((error["line"], error["content"], error["reason"]))

    return ImportResult(imported=imported, failed=failed)
```

#### Commande `/hosts import`

```bash
# Import CSV
/hosts import inventory.csv
# 📥 Import de inventory.csv...
# 🧠 Détection format: CSV
# ✅ 45 hosts importés
# ⚠️ 3 lignes ignorées (voir /hosts import --errors)

# Import avec format explicite
/hosts import servers.txt --format=custom
# 📥 Import de servers.txt...
# 🧠 Analyse par Brain (format custom)...
# ✅ 12 hosts importés
# ❌ 2 lignes non parsées:
#    L5: "serveur-test ???" - Hostname invalide
#    L8: "# commentaire" - Ligne ignorée

# Import JSON/YAML
/hosts import infra.yaml
/hosts import hosts.json

# Formats supportés
/hosts import --formats
# Formats supportés:
#   - csv      (hostname,ip,port,user,tags)
#   - json     ([{name, hostname, ...}])
#   - yaml     (même structure que JSON)
#   - ansible  (format INI Ansible)
#   - ssh      (format ~/.ssh/config)
#   - custom   (parsing par Brain/LLM)
```

#### Affichage des erreurs d'import

```python
def display_import_errors(result: ImportResult, ui: ConsoleUI) -> None:
    """Affiche les erreurs d'import de manière claire."""
    if not result.failed:
        return

    ui.warning(f"⚠️ {len(result.failed)} ligne(s) non importée(s):")
    ui.newline()

    for line_num, line_content, error in result.failed[:10]:
        ui.error(f"  L{line_num}: {line_content[:50]}...")
        ui.info(f"       └─ {error}")

    if len(result.failed) > 10:
        ui.info(f"  ... et {len(result.failed) - 10} autres erreurs")
        ui.info("  💡 Utilisez /hosts import --errors pour voir tout")
```

### Host Resolution Strategy

**Décision** : Résolution locale en priorité, puis DNS standard

#### Ordre de résolution

```
┌─────────────────────────────────────────────────────────┐
│              HOST RESOLUTION ORDER                       │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  1. Inventaire Merlya (SQLite)                          │
│     hosts.get_by_name("web-01") → IP connue             │
└─────────────────────────────────────────────────────────┘
                           │
                     [Non trouvé]
                           ▼
┌─────────────────────────────────────────────────────────┐
│  2. Résolution système locale                           │
│     /etc/hosts, mDNS, NetBIOS                           │
│     socket.gethostbyname() avec timeout                 │
└─────────────────────────────────────────────────────────┘
                           │
                     [Non trouvé]
                           ▼
┌─────────────────────────────────────────────────────────┐
│  3. DNS standard                                        │
│     Résolveur système → serveurs DNS configurés         │
└─────────────────────────────────────────────────────────┘
                           │
                     [Non trouvé]
                           ▼
┌─────────────────────────────────────────────────────────┐
│  4. Erreur                                              │
│     "Host 'xxx' non résolu. Voulez-vous l'ajouter ?"    │
└─────────────────────────────────────────────────────────┘
```

#### Implémentation

```python
import socket
from dataclasses import dataclass

@dataclass
class ResolvedHost:
    query: str           # Ce qui a été demandé
    hostname: str        # Hostname résolu
    ip: str              # IP résolue
    source: str          # "inventory", "local", "dns"
    host_id: str | None  # ID dans l'inventaire si trouvé

class HostResolver:
    """Résolution de hosts avec priorité locale."""

    def __init__(
        self,
        host_repo: HostRepository,
        local_timeout: float = 2.0,
        dns_timeout: float = 5.0,
    ):
        self.host_repo = host_repo
        self.local_timeout = local_timeout
        self.dns_timeout = dns_timeout

    async def resolve(self, query: str) -> ResolvedHost:
        """
        Résout un host dans l'ordre:
        1. Inventaire Merlya
        2. Résolution locale (/etc/hosts, mDNS)
        3. DNS standard
        """
        # 1. Check inventaire
        host = self.host_repo.get_by_name(query)
        if host:
            return ResolvedHost(
                query=query,
                hostname=host.hostname,
                ip=host.ip or await self._resolve_dns(host.hostname),
                source="inventory",
                host_id=host.id,
            )

        # 2. Résolution locale (timeout court)
        try:
            ip = await asyncio.wait_for(
                asyncio.to_thread(socket.gethostbyname, query),
                timeout=self.local_timeout,
            )
            return ResolvedHost(
                query=query,
                hostname=query,
                ip=ip,
                source="local",
                host_id=None,
            )
        except (socket.gaierror, asyncio.TimeoutError):
            pass

        # 3. DNS standard (timeout plus long)
        try:
            ip = await asyncio.wait_for(
                self._resolve_dns(query),
                timeout=self.dns_timeout,
            )
            return ResolvedHost(
                query=query,
                hostname=query,
                ip=ip,
                source="dns",
                host_id=None,
            )
        except (socket.gaierror, asyncio.TimeoutError):
            pass

        # 4. Non résolu
        raise HostNotFoundError(
            f"Host '{query}' non résolu",
            suggestions=self._find_similar_hosts(query),
        )

    async def _resolve_dns(self, hostname: str) -> str:
        """Résolution DNS async."""
        loop = asyncio.get_event_loop()
        result = await loop.getaddrinfo(
            hostname, None,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
        return result[0][4][0]

    def _find_similar_hosts(self, query: str) -> list[str]:
        """Trouve des hosts similaires pour suggestion."""
        all_hosts = self.host_repo.get_all()
        similar = []

        for host in all_hosts:
            # Levenshtein distance ou simple contains
            if query.lower() in host.name.lower():
                similar.append(host.name)
            elif host.name.lower() in query.lower():
                similar.append(host.name)

        return similar[:5]
```

#### Comportement en cas d'échec

```python
async def connect_to_host(query: str, resolver: HostResolver, ui: ConsoleUI):
    """Connexion avec gestion d'erreur et suggestion."""
    try:
        resolved = await resolver.resolve(query)
        ui.info(f"🌐 Résolu: {resolved.hostname} → {resolved.ip} ({resolved.source})")
        return await ssh_pool.connect(resolved.ip)

    except HostNotFoundError as e:
        ui.error(f"❌ {e.message}")

        if e.suggestions:
            ui.info("💡 Hosts similaires:")
            for s in e.suggestions:
                ui.info(f"   - {s}")

        # Proposer d'ajouter
        add = await ui.prompt_confirm(f"Ajouter '{query}' à l'inventaire ?")
        if add:
            ip = await ui.prompt("IP ou hostname")
            host_repo.create(name=query, hostname=ip)
            ui.success(f"✅ Host '{query}' ajouté")
            # Retry
            return await connect_to_host(query, resolver, ui)

        raise
```

### Modèle local

**Stratégie** : Auto-détection au premier démarrage + persistance du choix

#### Tiers de modèles (du plus au moins performant)

| Tier | RAM requise | Modèle | Taille | Dims | Latence | Classification |
|------|-------------|--------|--------|------|---------|----------------|
| 🥇 **Performance** | ≥4GB libre | `gte-multilingual-base` | 305MB | 768 | <50ms | SOTA |
| 🥈 **Balanced** | ≥2GB libre | `EmbeddingGemma` | 308MB | 256* | <25ms | Excellent |
| 🥉 **Lightweight** | ≥512MB libre | `multilingual-e5-small` | 118MB | 384 | <30ms | Bon |

*\* EmbeddingGemma avec Matryoshka truncation à 256 dims*

#### Workflow premier démarrage

```
┌─────────────────────────────────────────────────────────┐
│                 PREMIER DÉMARRAGE                        │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              1. Détection RAM disponible                 │
│                 psutil.virtual_memory().available        │
└─────────────────────────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
    [≥4GB libre]     [≥2GB libre]     [≥512MB libre]
         │                 │                 │
         ▼                 ▼                 ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ 🥇 gte-     │   │ 🥈 Embedding│   │ 🥉 e5-small │
│ multilingual│   │ Gemma       │   │             │
└─────────────┘   └─────────────┘   └─────────────┘
         │                 │                 │
         └─────────────────┼─────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────┐
│           2. Téléchargement modèle ONNX                  │
│              (avec progress bar)                         │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│           3. Test de chargement                          │
│              Si échec → downgrade au tier inférieur      │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│           4. Persistance dans config.yaml                │
│              router.model: "gte-multilingual-base"       │
│              router.tier: "performance"                  │
└─────────────────────────────────────────────────────────┘
```

#### Implémentation

```python
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import psutil

class ModelTier(Enum):
    PERFORMANCE = "performance"   # gte-multilingual-base
    BALANCED = "balanced"         # EmbeddingGemma
    LIGHTWEIGHT = "lightweight"   # multilingual-e5-small

@dataclass
class EmbeddingModelConfig:
    tier: ModelTier
    model_id: str
    onnx_file: str
    dimensions: int
    min_ram_mb: int

EMBEDDING_MODELS = {
    ModelTier.PERFORMANCE: EmbeddingModelConfig(
        tier=ModelTier.PERFORMANCE,
        model_id="Alibaba-NLP/gte-multilingual-base",
        onnx_file="model.onnx",
        dimensions=768,
        min_ram_mb=4096,
    ),
    ModelTier.BALANCED: EmbeddingModelConfig(
        tier=ModelTier.BALANCED,
        model_id="google/embeddinggemma-300m",
        onnx_file="model_quantized.onnx",
        dimensions=256,  # Matryoshka truncation
        min_ram_mb=2048,
    ),
    ModelTier.LIGHTWEIGHT: EmbeddingModelConfig(
        tier=ModelTier.LIGHTWEIGHT,
        model_id="intfloat/multilingual-e5-small",
        onnx_file="model.onnx",
        dimensions=384,
        min_ram_mb=512,
    ),
}

def detect_optimal_tier() -> ModelTier:
    """Détecte le tier optimal selon la RAM disponible."""
    available_mb = psutil.virtual_memory().available // (1024 * 1024)

    if available_mb >= 4096:
        return ModelTier.PERFORMANCE
    elif available_mb >= 2048:
        return ModelTier.BALANCED
    else:
        return ModelTier.LIGHTWEIGHT

async def initialize_router() -> "IntentRouter":
    """Initialise le router au premier démarrage."""
    config = load_config()

    # Si déjà configuré, utiliser le modèle persisté
    if config.router.model:
        return await load_router(config.router.model)

    # Premier démarrage : auto-détection
    tier = detect_optimal_tier()
    model_config = EMBEDDING_MODELS[tier]

    logger.info(f"🧠 Détection automatique : tier {tier.value}")
    logger.info(f"📥 Téléchargement du modèle {model_config.model_id}...")

    # Télécharger avec fallback
    success = await download_model(model_config)

    if not success:
        # Downgrade au tier inférieur
        tier = downgrade_tier(tier)
        model_config = EMBEDDING_MODELS[tier]
        logger.warning(f"⚠️ Fallback vers tier {tier.value}")
        await download_model(model_config)

    # Persister le choix
    config.router.model = model_config.model_id
    config.router.tier = tier.value
    config.save()

    logger.info(f"✅ Router initialisé avec {model_config.model_id}")
    return await load_router(model_config)

def downgrade_tier(current: ModelTier) -> ModelTier:
    """Downgrade au tier inférieur."""
    if current == ModelTier.PERFORMANCE:
        return ModelTier.BALANCED
    elif current == ModelTier.BALANCED:
        return ModelTier.LIGHTWEIGHT
    else:
        raise RuntimeError("Impossible de charger le modèle minimal")
```

#### Commande `/model router`

```bash
# Voir le tier actuel
/model router show
# 🧠 Router: gte-multilingual-base (tier: performance)
# 📊 RAM utilisée: ~600MB
# ⚡ Latence moyenne: 45ms

# Forcer un tier différent
/model router tier balanced
# ⚠️ Changement de tier vers 'balanced'
# 📥 Téléchargement EmbeddingGemma...
# ✅ Router mis à jour

# Recalculer le tier optimal
/model router auto
# 🔍 Détection RAM: 8.2GB disponible
# 🥇 Tier optimal: performance
# ✅ Aucun changement nécessaire
```

**Librairies** :
- `onnxruntime` - Inference ONNX (léger, pas de PyTorch)
- `tokenizers` - Tokenization rapide
- `huggingface_hub` - Téléchargement modèles

### Fallback LLM

Si modèle local indisponible → utiliser LLM rapide configurable :

```python
# Config par défaut
router_llm_config = {
    "provider": "openai",
    "model": "gpt-4o-mini",  # Rapide et économique
}

# Configurable via /model router llm
```

### Output du Router

```python
@dataclass
class RouterResult:
    mode: Literal["diagnostic", "remediation", "query", "chat"]
    tools: list[str]  # ["core", "system", "files", ...]
    entities: dict    # {"hosts": ["web-01"], "variables": ["db_pass"]}
    confidence: float
```

**Date** : 2025-12-05

---

## 9. Architecture des Tools

**Décision** : Mono-agent avec tools chargés dynamiquement selon le contexte

### Modes de l'agent

| Mode | Description | Comportement |
|------|-------------|--------------|
| `diagnostic` | Analyse, collecte d'infos | Pas d'actions destructives, observation only |
| `remediation` | Actions correctives | Demande confirmation avant actions critiques |
| `query` | Questions sur l'infrastructure | Réponses informatives, lecture seule |
| `chat` | Conversation générale | Pas de tools infrastructure |

### Catégories de Tools

**Core (toujours actifs)** :
| Tool | Description |
|------|-------------|
| `list_hosts` | Lister hôtes avec filtres |
| `get_host` | Détails + contexte enrichi d'un hôte |
| `ssh_execute` | Exécuter commande SSH |
| `ask_user` | Demander input (supporte `@host`, `@variable`, ajout secrets) |
| `request_confirmation` | Confirmation avant action critique |

**Système (activés si hôte ciblé)** :
| Tool | Description |
|------|-------------|
| `get_system_info` | OS, CPU, RAM, uptime |
| `check_disk_usage` | Espace disque |
| `check_memory` | Utilisation mémoire |
| `check_cpu` | Charge CPU |
| `list_processes` | Processus en cours |
| `check_service_status` | État d'un service |
| `analyze_logs` | Analyser fichiers logs |

**Fichiers (activés si opérations fichiers détectées)** :
| Tool | Description |
|------|-------------|
| `read_file_content` | Lire fichier distant |
| `write_file_content` | Écrire fichier distant |
| `list_directory` | Lister répertoire |
| `search_files` | Rechercher fichiers |
| `ssh_copy_file` | Upload SFTP |
| `ssh_get_file` | Download SFTP |

**Sécurité (activés si contexte sécurité)** :
| Tool | Description |
|------|-------------|
| `check_open_ports` | Ports ouverts |
| `audit_ssh_keys` | Audit clés SSH |
| `check_security_config` | Config sécurité |

**Plugins (chargés à la demande, non core)** :
- Docker : `docker_ps`, `docker_logs`, `docker_exec`
- Kubernetes : `k8s_get_pods`, `k8s_describe`, `k8s_logs`
- IaC : `terraform_plan`, `ansible_run`
- CI/CD : `github_actions_status`, `trigger_workflow`

### Chargement dynamique

```python
def get_active_tools(router_result: RouterResult) -> list[Tool]:
    """Retourne les tools à activer selon le contexte."""
    tools = CORE_TOOLS.copy()

    if "system" in router_result.tools:
        tools.extend(SYSTEM_TOOLS)
    if "files" in router_result.tools:
        tools.extend(FILE_TOOLS)
    if "security" in router_result.tools:
        tools.extend(SECURITY_TOOLS)

    # Plugins si installés et demandés
    for plugin in router_result.tools:
        if plugin in INSTALLED_PLUGINS:
            tools.extend(INSTALLED_PLUGINS[plugin].tools)

    return tools
```

**Date** : 2025-12-05

---

## 10. Executor SSH

**Décision** : `asyncssh` avec connection pool

### Librairie

**asyncssh** - Full async, moderne, bien maintenu
- Support natif async (cohérent avec PydanticAI)
- Clés : Ed25519, RSA, ECDSA
- 2FA/MFA : keyboard-interactive, TOTP
- Jump hosts : ProxyJump natif
- SFTP intégré
- Agent forwarding

### Connection Pool

```python
class SSHConnectionPool:
    """Pool de connexions SSH avec réutilisation."""

    # Timeout par défaut : 10 minutes
    DEFAULT_TIMEOUT = 600  # secondes

    async def get_connection(self, host: str) -> SSHConnection:
        """Récupère ou crée une connexion."""
        if host in self._connections:
            conn = self._connections[host]
            if conn.is_alive():
                conn.refresh_timeout()
                return conn

        # Nouvelle connexion (demandera MFA si nécessaire)
        return await self._create_connection(host)

    async def disconnect(self, host: str) -> None:
        """Déconnexion explicite."""
        if host in self._connections:
            await self._connections[host].close()
            del self._connections[host]

    async def disconnect_all(self) -> None:
        """Déconnecte toutes les connexions."""
        for conn in self._connections.values():
            await conn.close()
        self._connections.clear()
```

### Configuration

| Paramètre | Valeur par défaut | Description |
|-----------|-------------------|-------------|
| `pool_timeout` | 10 minutes | Durée avant déconnexion auto |
| `connect_timeout` | 30 secondes | Timeout connexion initiale |
| `command_timeout` | 60 secondes | Timeout exécution commande |

### MFA/2FA Handling

**Politique** : Demander à chaque nouvelle connexion

```python
async def handle_mfa(self, prompt: str) -> str:
    """Demande le code MFA à l'utilisateur."""
    # Affiche le prompt MFA dans la console
    code = await ui.prompt_secret(f"🔐 {prompt}")
    return code
```

**Pourquoi pas de cache MFA ?**
- Sécurité : les codes TOTP expirent
- Simplicité : pas de gestion de tokens
- Pool : la connexion reste ouverte 10min, donc MFA rare

### Jump Hosts (Bastion)

```python
# Configuration par hôte
host_config = {
    "name": "db-prod-01",
    "hostname": "10.0.1.50",
    "jump_host": "bastion.example.com",  # Pivot via bastion
    "jump_user": "admin",
}

# asyncssh gère le tunnel automatiquement
async with asyncssh.connect(
    host_config["hostname"],
    tunnel=await asyncssh.connect(host_config["jump_host"])
) as conn:
    result = await conn.run("uptime")
```

### SFTP

```python
async def upload_file(self, host: str, local: Path, remote: str) -> None:
    """Upload fichier via SFTP."""
    conn = await self.pool.get_connection(host)
    async with conn.start_sftp_client() as sftp:
        await sftp.put(local, remote)

async def download_file(self, host: str, remote: str, local: Path) -> None:
    """Download fichier via SFTP."""
    conn = await self.pool.get_connection(host)
    async with conn.start_sftp_client() as sftp:
        await sftp.get(remote, local)
```

**Date** : 2025-12-05

---

## 11. Inventaire (Hosts)

**Décision** : `/hosts` = inventaire simplifié

### Clarification

- V1 avait `/inventory` avec beaucoup de complexité (groups, relations, bulk)
- Lean Merlya : **`/hosts` remplace `/inventory`** avec une approche simplifiée

### Modèle de données Host

```python
@dataclass
class Host:
    id: str                          # UUID auto-généré
    name: str                        # Nom unique (ex: "web-01")
    hostname: str                    # Hostname ou IP
    port: int = 22                   # Port SSH
    username: str | None = None      # User SSH (défaut: current user)

    # SSH config
    private_key: str | None = None   # Chemin clé privée
    jump_host: str | None = None     # Host bastion pour pivot

    # Métadonnées
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    # Enrichissement (rempli au scan/connexion)
    os_info: OSInfo | None = None
    last_seen: datetime | None = None
    health_status: str | None = None  # "healthy", "degraded", "unreachable"

    created_at: datetime
    updated_at: datetime
```

### Commandes `/hosts`

| Commande | Description |
|----------|-------------|
| `/hosts list` | Lister tous les hôtes (avec filtres: tags, status) |
| `/hosts add <name>` | Ajouter un hôte (wizard interactif) |
| `/hosts show <name>` | Détails complets + enrichissement |
| `/hosts edit <name>` | Modifier un hôte |
| `/hosts delete <name>` | Supprimer un hôte |
| `/hosts tag <name> <tag>` | Ajouter un tag |
| `/hosts untag <name> <tag>` | Retirer un tag |
| `/hosts scan <name>` | Scanner/enrichir un hôte |
| `/hosts import <file>` | Import bulk (JSON/YAML) |
| `/hosts export <file>` | Export bulk |

### Enrichissement automatique

À la première connexion SSH ou via `/hosts scan` :

```python
async def enrich_host(host: Host) -> Host:
    """Enrichit un hôte avec ses infos système."""
    conn = await ssh_pool.get_connection(host.name)

    # Collecter infos
    os_info = await collect_os_info(conn)
    resources = await collect_resources(conn)
    services = await detect_services(conn)

    # Mettre à jour
    host.os_info = os_info
    host.metadata["resources"] = resources
    host.metadata["services"] = services
    host.last_seen = datetime.now()
    host.health_status = "healthy"

    return host
```

### Relations entre hôtes

Simplifié par rapport à V1 - basé sur les tags et jump_host :

```python
# Groupement par tags
web_servers = hosts.filter(tags=["web", "prod"])
databases = hosts.filter(tags=["db", "prod"])

# Relations via jump_host
# db-prod-01.jump_host = "bastion-01" → relation implicite
```

**Date** : 2025-12-05

---

## 12. Persistence/Store

**Décision** : SQLite + Keyring + Config YAML

### Structure fichiers

```
~/.merlya/
├── merlya.db           # SQLite principal
├── config.yaml         # Config lisible/éditable
├── logs/
│   └── merlya.log      # Logs rotatifs
└── models/
    └── router.onnx     # Modèle embedding (si téléchargé)
```

### SQLite - Tables

```sql
-- Hosts (inventaire)
CREATE TABLE hosts (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    hostname TEXT NOT NULL,
    port INTEGER DEFAULT 22,
    username TEXT,
    private_key TEXT,
    jump_host TEXT,
    tags TEXT,              -- JSON array
    metadata TEXT,          -- JSON object
    os_info TEXT,           -- JSON object
    health_status TEXT,
    last_seen TIMESTAMP,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Variables
CREATE TABLE variables (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    is_env BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP
);

-- Config
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Conversations (historique)
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    title TEXT,             -- Titre auto-généré ou manuel
    messages TEXT,          -- JSON array
    summary TEXT,           -- Résumé auto (optionnel)
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Scan cache
CREATE TABLE scan_cache (
    host_id TEXT,
    scan_type TEXT,
    data TEXT,
    expires_at TIMESTAMP,
    PRIMARY KEY (host_id, scan_type)
);
```

### Secrets - Keyring

Les secrets NE VONT PAS dans SQLite :

```python
import keyring

SERVICE_NAME = "merlya"

def set_secret(name: str, value: str) -> None:
    keyring.set_password(SERVICE_NAME, name, value)

def get_secret(name: str) -> str | None:
    return keyring.get_password(SERVICE_NAME, name)

def delete_secret(name: str) -> None:
    try:
        keyring.delete_password(SERVICE_NAME, name)
    except keyring.errors.PasswordDeleteError:
        pass
```

**Fallback si keyring indisponible** : in-memory avec warning

### Commande `/conv`

| Sous-commande | Description |
|---------------|-------------|
| `/conv list` | Lister les conversations (titre, date, résumé) |
| `/conv show <id>` | Afficher une conversation |
| `/conv load <id>` | Charger/reprendre une conversation |
| `/conv delete <id>` | Supprimer une conversation |
| `/conv rename <id> <titre>` | Renommer une conversation |
| `/conv export <id> <fichier>` | Exporter (JSON/Markdown) |
| `/conv search <terme>` | Rechercher dans l'historique |

### Config YAML

Fichier éditable manuellement pour les préférences :

```yaml
# ~/.merlya/config.yaml
general:
  language: fr
  log_level: info

model:
  provider: anthropic
  model: claude-3-5-sonnet
  router:
    type: local  # ou "llm"
    llm_fallback: openai:gpt-4o-mini

ssh:
  pool_timeout: 600
  connect_timeout: 30
  command_timeout: 60

ui:
  theme: auto  # auto, light, dark
  markdown: true
```

**Date** : 2025-12-05

---

## 13. Système d'Agents Spécialisés

**Décision** : Plugins = Agents spécialisés avec leurs propres tools, MCP, docs et prompts

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                 Socle Commun (Shared)                    │
│  - Intent Router (brain)                                │
│  - SSH Pool                                             │
│  - Hosts Repository                                     │
│  - Variables/Secrets                                    │
│  - UI Console                                           │
└─────────────────────────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  Main Agent     │ │  Docker Agent   │ │  K8s Agent      │
│  (Merlya)       │ │                 │ │                 │
│                 │ │ - Tools docker  │ │ - Tools k8s     │
│ - Tools core    │ │ - MCP docker    │ │ - MCP kubectl   │
│ - Tools system  │ │ - Docs docker   │ │ - Docs k8s      │
│ - Tools files   │ │ - Prompt expert │ │ - Prompt expert │
│ - Tools security│ │                 │ │                 │
└─────────────────┘ └─────────────────┘ └─────────────────┘
         │                 ▲                 ▲
         │                 │                 │
         └─────── handoff ─┴─────────────────┘
```

### Socle commun partagé

Tous les agents (principal + spécialisés) partagent :

```python
class SharedContext:
    """Contexte partagé entre tous les agents."""
    router: IntentRouter          # Brain pour classification
    ssh_pool: SSHConnectionPool   # Connexions SSH réutilisées
    hosts: HostRepository         # Accès à l'inventaire
    variables: VariableStore      # Variables @name
    secrets: SecretStore          # Secrets
    ui: ConsoleUI                 # Interface utilisateur
    config: Config                # Configuration globale
```

### Structure d'un Agent Spécialisé

```python
# ~/.merlya/agents/docker/agent.py
from pydantic_ai import Agent
from merlya.agents import SpecializedAgent, SharedContext

class DockerAgent(SpecializedAgent):
    name = "docker"
    description = "Expert Docker et containers"
    version = "1.0.0"

    # Prompt système spécialisé
    system_prompt = """
    Tu es un expert Docker et containerisation.

    Tu maîtrises :
    - Gestion des containers et images
    - Docker Compose et orchestration
    - Optimisation des Dockerfiles
    - Sécurité des containers
    - Debugging et logs

    Tu as accès au contexte Merlya :
    - Hosts de l'infrastructure via shared.hosts
    - Connexions SSH via shared.ssh_pool
    - Variables utilisateur via shared.variables
    """

    # Tools spécifiques Docker
    @tool
    async def docker_ps(self, host: str) -> list[Container]:
        """Liste les containers sur un host."""
        conn = await self.shared.ssh_pool.get_connection(host)
        result = await conn.run("docker ps --format json")
        return parse_containers(result.stdout)

    @tool
    async def docker_logs(self, host: str, container: str, tail: int = 100) -> str:
        """Récupère les logs d'un container."""
        ...

    @tool
    async def docker_exec(self, host: str, container: str, command: str) -> str:
        """Exécute une commande dans un container."""
        ...

    # MCP servers (optionnel)
    mcp_servers = [
        {"name": "docker-mcp", "command": "npx", "args": ["-y", "docker-mcp-server"]},
    ]

    # Documentation contextuelle
    docs_path = Path(__file__).parent / "docs"

    def __init__(self, shared: SharedContext):
        super().__init__(shared)
        # L'agent utilise le même router pour classifier les sous-requêtes
        self.router = shared.router
```

### Router avec délégation

```python
@dataclass
class RouterResult:
    mode: Literal["diagnostic", "remediation", "query", "chat"]
    tools: list[str]
    entities: dict
    confidence: float
    delegate_to: str | None  # "docker", "kubernetes", "cicd", None

# Le router décide aussi si un agent spécialisé est nécessaire
async def route_request(user_input: str, available_agents: list[str]) -> RouterResult:
    result = await classify_intent(user_input)

    # Détecter si un agent spécialisé est pertinent
    if "docker" in user_input.lower() or "container" in user_input.lower():
        if "docker" in available_agents:
            result.delegate_to = "docker"

    return result
```

### Handoff et communication

```python
class MainAgent:
    async def run(self, user_input: str) -> str:
        # 1. Router classifie la requête
        route = await self.router.route(user_input, self.available_agents)

        # 2. Déléguer si nécessaire
        if route.delegate_to:
            agent = self.agents[route.delegate_to]
            # L'agent spécialisé a accès au contexte partagé
            result = await agent.run(user_input)
            # Optionnel : enrichir la réponse avec le contexte principal
            return result

        # 3. Sinon, traiter avec l'agent principal
        return await self._process(user_input, route)
```

### Commande `/agent`

| Sous-commande | Description |
|---------------|-------------|
| `/agent list` | Lister agents disponibles (installés + actifs) |
| `/agent info <name>` | Détails d'un agent (tools, MCP, docs) |
| `/agent enable <name>` | Activer un agent |
| `/agent disable <name>` | Désactiver un agent |
| `/agent install <name>` | Installer depuis registry/pip |
| `/agent create <name>` | Créer un nouvel agent (scaffold) |
| `/agent update <name>` | Mettre à jour un agent |

### Structure fichiers agents

```
~/.merlya/
├── agents/
│   ├── docker/
│   │   ├── agent.py          # Définition de l'agent
│   │   ├── tools.py          # Tools spécifiques
│   │   ├── manifest.yaml     # Métadonnées
│   │   └── docs/
│   │       ├── best-practices.md
│   │       └── troubleshooting.md
│   ├── kubernetes/
│   │   └── ...
│   └── cicd/
│       └── ...
```

### Manifest agent

```yaml
# manifest.yaml
name: docker
version: 1.0.0
description: Expert Docker et containers
author: merlya-community

# Dépendances
requires:
  cli:
    - docker
  python:
    - docker>=6.0

# Tools exposés
tools:
  - docker_ps
  - docker_logs
  - docker_exec
  - docker_build
  - docker_compose_up

# MCP servers
mcp:
  - name: docker-mcp
    command: npx
    args: ["-y", "docker-mcp-server"]

# Mots-clés pour le router
keywords:
  - docker
  - container
  - image
  - dockerfile
  - compose
```

**Date** : 2025-12-05

---

## Récapitulatif des décisions

| # | Composant | Décision |
|---|-----------|----------|
| 1 | Framework Agent | PydanticAI |
| 2 | Providers LLM | Passthrough PydanticAI, `/model` simplifié |
| 3 | UI Console | Rich + Markdown + prompt_toolkit (autocompletion) |
| 4 | Slash Commands | 15 commandes core (voir section 4) |
| 5 | i18n | JSON locales (fr/en), convention V2 |
| 6 | Logging | loguru, configurable (niveau, rotation, chemin) |
| 7 | Documentation | CONTRIBUTING.md adapté au projet |
| 8 | Intent Router | Local-first (ONNX) + fallback LLM configurable |
| 9 | Tools | Mono-agent, chargement dynamique par contexte |
| 10 | SSH Executor | asyncssh, pool 10min, MFA à chaque connexion |
| 11 | Inventaire | `/hosts` = inventaire simplifié, enrichissement auto |
| 12 | Persistence | SQLite + Keyring + config.yaml |
| 13 | Agents | Spécialisés (Docker, K8s, CI/CD...) avec socle partagé |
| 14 | Credentials & Elevation | Brain-driven, tools interactifs, PermissionManager assisté |

---

## 14. Gestion des Credentials et Élévation (brain-driven)

**Décision** : la collecte de credentials (tokens, mots de passe, passphrases, JSON, paires user/mdp) et l'élévation de privilèges est pilotée par le brain (router/agent), pas par heuristique silencieuse côté exécution.

**Principes** :
- Le router/LLM détecte `credentials_required` et `elevation_required` (erreurs auth/permission, instructions explicites). Le classif local ONNX reste minimal ; en cas d'ambiguïté, fallback LLM tranche.
- Tools interactifs :
  - `request_credentials(service, host?, fields?, format?)` : collecte sécurisée (prompts secrets), support multi-format (token, password, passphrase, JSON, clé), option de stockage keyring (ou session-only), renvoie un bundle structuré.
  - `request_elevation(command, host?)` : demande explicite, s'appuie sur PermissionManager pour choisir sudo/su/doas et gère le mot de passe si requis.
- PermissionManager détecte sudo/doas/su et applique le préfixe uniquement sur instruction du brain/tool (plus d'automatisme heuristique côté ssh_execute).
- Sécurité : aucun log de secret, stockage via keyring (fallback mémoire), prompts masqués, consentement pour le stockage.

**Implémentation** :
- Router : enrichir RouterResult avec des signaux `credentials_required`/`elevation_required` issus du fallback LLM.
- Tools : ajouter `request_credentials` (multi-type) et réviser `request_elevation` pour utiliser PermissionManager et l'UI sécurisée.
- Agent : sur signal ou erreur auth/permission, appel des tools puis retry de la commande avec secrets/élévation.
- SSH/exec : PermissionManager n'applique l'élévation que sur demande (prefix/sudo -S/su/doas + stdin sécurisé).

**Tests** : couvrir demande credentials (avec/sans stockage) et élévation (sudo nopasswd, sudo avec mot de passe, su/doas), vérifier absence de secrets dans les logs, et propagation des signaux du router.

**Date** : 2025-12-06

## Prochaines étapes

1. [ ] Créer la structure de projet dans `/Users/cedric/lean-merlya`
2. [ ] Initialiser pyproject.toml avec dépendances
3. [ ] Implémenter le socle commun (SharedContext)
4. [ ] Implémenter l'agent principal
5. [ ] Implémenter les slash commands
6. [ ] Créer CONTRIBUTING.md
7. [ ] Ajouter tests unitaires
