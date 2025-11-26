# Plan de Refactoring Athena

> Objectif : Aligner le codebase sur les standards Python modernes et les principes SOLID, DRY, KISS, DDD, SoC, YAGNI

## Progression

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Éliminer les Redondances (DRY) | ✅ Terminé |
| Phase 2 | Découper les Blobs (SRP, SoC) | ✅ Terminé |
| Phase 3 | Interfaces et Protocols (LSP, DIP) | ✅ Terminé |
| Phase 4 | Migration autogen-agentchat 0.7+ API | ✅ Terminé |
| Phase 5 | Production Polish (lint, tests, model_info) | ✅ Terminé |

### Fichiers créés/modifiés

**Phase 1:**
- `core/protocols.py` - Interfaces Agent, Tool, Store, Orchestrator
- `core/exceptions.py` - Hiérarchie d'erreurs unifiée
- `agents/orchestrator.py` - Orchestrateur unifié (BASIC/ENHANCED)
- `agents/planner.py` - Planner unifié (PATTERN/LLM/AUTO)
- `memory/conversation.py` - ConversationManager unifié (SQLite/JSON stores)

**Phase 2:**
- `tools/base.py` - ToolContext, validation, hooks
- `tools/commands.py` - execute_command, add_route
- `tools/hosts.py` - list_hosts, scan_host, check_permissions
- `tools/security.py` - audit_host, analyze_security_logs
- `tools/files.py` - read/write files, grep, find, tail
- `tools/system.py` - disk_info, memory_info, network, processes, services
- `tools/containers.py` - docker_exec, kubectl_exec
- `tools/web.py` - web_search, web_fetch
- `tools/interaction.py` - ask_user, remember_skill, recall_skill

**Phase 3:**
- `core/registry.py` - AgentRegistry (OCP pattern)
- `agents/coordinator.py` - Refactoré pour utiliser registry

---

## Diagnostic Résumé

| Problème | Impact | Principe Violé |
|----------|--------|----------------|
| 3 orchestrateurs quasi-identiques | 1500 lignes dupliquées | DRY |
| 3 planners redondants | 1300 lignes dupliquées | DRY |
| `autogen_tools.py` = 1576 lignes, 30 fonctions | Impossible à maintenir | SRP, SoC |
| `SessionManager` = 6 responsabilités | Couplage fort | SRP |
| `AgentCoordinator` avec if/elif | Non extensible | OCP |
| Agents sans interface commune | Pas de polymorphisme | LSP, DIP |
| `memory/` ↔ `context/` bidirectionnel | Dépendances circulaires | LoD, SoC |
| Variables globales dans tools | Non testable | DIP |

---

## Architecture Cible

```
athena_ai/
├── core/                    # Noyau stable (interfaces, types, exceptions)
│   ├── protocols.py         # Agent, Tool, Store, Orchestrator protocols
│   ├── types.py             # TypedDict, Enums, ValueObjects
│   ├── exceptions.py        # Hiérarchie d'erreurs Athena
│   └── config.py            # Configuration centralisée
│
├── agents/                  # Agents spécialisés (SRP)
│   ├── base.py              # BaseAgent avec Protocol
│   ├── orchestrator.py      # UN seul orchestrateur configurable
│   ├── planner.py           # UN seul planner avec strategies
│   ├── sentinel.py          # Monitoring (inchangé)
│   ├── remediation.py       # Self-healing (inchangé)
│   └── registry.py          # AgentRegistry (OCP)
│
├── tools/                   # Outils découpés par domaine (SoC)
│   ├── base.py              # Tool Protocol
│   ├── system.py            # disk_info, memory_info, process_list
│   ├── network.py           # network_connections, web_search, web_fetch
│   ├── containers.py        # docker_exec, kubectl_exec
│   ├── files.py             # read_remote_file, write_remote_file, glob, grep
│   ├── commands.py          # execute_command, service_control
│   └── registry.py          # ToolRegistry avec DI
│
├── infrastructure/          # Couche infrastructure (DDD)
│   ├── executors/           # SSH, Ansible, Terraform, K8s
│   ├── repositories/        # SessionRepository, HostRepository
│   ├── connectors/          # PostgreSQL, MySQL, MongoDB, API
│   └── cache.py             # SmartCache
│
├── domain/                  # Logique métier pure (DDD)
│   ├── context/             # Gestion du contexte infra
│   │   ├── manager.py
│   │   ├── discovery.py
│   │   └── inventory.py
│   ├── knowledge/           # Knowledge graph (optionnel)
│   ├── triage/              # Classification P0-P3
│   └── security/            # Audit, permissions, risk
│
├── application/             # Cas d'usage / Services (DDD)
│   ├── orchestration.py     # RequestProcessor, PlanManager
│   ├── analysis.py          # AnalysisService
│   ├── synthesis.py         # SynthesisService
│   └── session.py           # SessionService (facade)
│
└── interfaces/              # Points d'entrée
    ├── cli.py               # Click CLI
    └── repl/                # REPL interactif
```

---

## Phase 1 : Éliminer les Redondances (DRY) ✅ TERMINÉ

### 1.1 Fusionner les Orchestrateurs

**Avant :** 3 fichiers (1485 lignes)
- `ag2_orchestrator.py` (488 lignes)
- `enhanced_ag2_orchestrator.py` (585 lignes)
- `cot_orchestrator_example.py` (412 lignes)

**Après :** 1 fichier (~400 lignes)

```python
# agents/orchestrator.py
from enum import Enum
from typing import Protocol

class OrchestratorStrategy(Enum):
    BASIC = "basic"
    ENHANCED = "enhanced"  # avec knowledge graph
    COT = "chain_of_thought"

class Orchestrator:
    """Orchestrateur unifié avec stratégies configurables."""

    def __init__(
        self,
        strategy: OrchestratorStrategy = OrchestratorStrategy.BASIC,
        env: str = "dev",
    ):
        self.strategy = strategy
        self._init_agents()

    def process(self, request: str) -> OrchestratorResult:
        match self.strategy:
            case OrchestratorStrategy.COT:
                return self._process_with_cot(request)
            case OrchestratorStrategy.ENHANCED:
                return self._process_with_knowledge(request)
            case _:
                return self._process_basic(request)
```

**Action :**
- [x] Créer `agents/orchestrator.py` avec Strategy pattern
- [x] Migrer le code commun depuis les 3 fichiers
- [x] Supprimer `enhanced_ag2_orchestrator.py`
- [x] Déplacer `cot_orchestrator_example.py` → `tests/examples/`

---

### 1.2 Fusionner les Planners

**Avant :** 3 fichiers (1302 lignes)
- `planner.py` (467 lignes) - Pattern matching
- `adaptive_planner.py` (387 lignes) - LLM-based
- `chain_of_thought.py` (448 lignes) - CoT

**Après :** 1 fichier avec Strategy (~350 lignes)

```python
# agents/planner.py
class PlanningStrategy(Protocol):
    def create_plan(self, request: str, context: Context) -> Plan: ...

class PatternPlanner(PlanningStrategy):
    """Planification rapide par pattern matching."""
    pass

class LLMPlanner(PlanningStrategy):
    """Planification intelligente via LLM."""
    pass

class Planner:
    def __init__(self, strategy: PlanningStrategy | None = None):
        self.strategy = strategy or PatternPlanner()

    def plan(self, request: str) -> Plan:
        return self.strategy.create_plan(request, self.context)
```

**Action :**
- [x] Créer interface `PlanningStrategy`
- [x] Refactorer `planner.py` pour utiliser Strategy
- [x] Fusionner `adaptive_planner.py` comme `LLMPlanner`
- [x] Supprimer `chain_of_thought.py` (intégré dans Planner avec mode AUTO)

---

### 1.3 Fusionner les Conversation Managers

**Avant :** 2 fichiers (1097 lignes)
- `conversation_manager.py` (480 lignes)
- `conversation_manager_sqlite.py` (617 lignes)

**Après :** Interface + 2 implémentations légères

```python
# core/protocols.py
class ConversationStore(Protocol):
    def save(self, conversation: Conversation) -> None: ...
    def load(self, session_id: str) -> Conversation | None: ...
    def list_sessions(self) -> list[str]: ...

# infrastructure/repositories/conversation.py
class MemoryConversationStore(ConversationStore):
    """Store en mémoire pour dev/tests."""
    pass

class SQLiteConversationStore(ConversationStore):
    """Store SQLite pour production."""
    pass
```

**Action :**
- [x] Extraire `ConversationStore` Protocol → `memory/conversation.py`
- [x] Refactorer les 2 managers en implémentations légères (SQLiteStore, JsonStore)
- [x] Utiliser Factory pour sélection automatique

---

## Phase 2 : Découper les Blobs (SRP, SoC) ✅ TERMINÉ

### 2.1 Découper `autogen_tools.py` (1576 → 5 × ~200 lignes)

**Avant :** 30 fonctions dans 1 fichier

**Après :**

```
tools/
├── base.py          # Tool Protocol + ToolContext (DI)
├── system.py        # disk_info, memory_info, process_list, service_control
├── network.py       # network_connections, web_search, web_fetch, check_permissions
├── containers.py    # docker_exec, kubectl_exec
├── files.py         # read_remote_file, write_remote_file, glob_files, grep_files
├── commands.py      # execute_command, scan_host, audit_host
└── registry.py      # ToolRegistry avec injection de dépendances
```

```python
# tools/base.py
from dataclasses import dataclass
from typing import Protocol, Any

@dataclass
class ToolContext:
    """Contexte injecté (DIP) - remplace les variables globales."""
    executor: "ActionExecutor"
    host_registry: "HostRegistry"
    permissions: "PermissionManager"
    hooks: "HookManager"

class Tool(Protocol):
    name: str
    description: str

    def execute(self, ctx: ToolContext, **params) -> ToolResult: ...

# tools/registry.py
class ToolRegistry:
    def __init__(self, context: ToolContext):
        self.context = context
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def execute(self, name: str, **params) -> ToolResult:
        return self._tools[name].execute(self.context, **params)
```

**Action :**
- [x] Créer `tools/base.py` avec `ToolContext` et `Tool` Protocol
- [x] Créer 9 modules thématiques: base, commands, hosts, security, files, system, containers, web, interaction
- [x] Migrer fonctions vers les modules thématiques (1576 → 9 × ~100 lignes)
- [x] Remplacer variables globales par `ToolContext` (DIP)
- [x] `autogen_tools.py` réduit à 108 lignes (re-exports pour compatibilité)

---

### 2.2 Découper `SessionManager` (1058 → 4 × ~150 lignes)

**Avant :** 6 responsabilités mélangées

**Après :**

```python
# infrastructure/repositories/session.py
class SessionRepository:
    """Accès DB uniquement (SRP)."""
    def save(self, session: Session) -> None: ...
    def load(self, session_id: str) -> Session: ...
    def delete(self, session_id: str) -> None: ...

# domain/session/logger.py
class SessionLogger:
    """Logging des queries et actions."""
    def log_query(self, query: Query) -> None: ...
    def log_action(self, action: Action) -> None: ...

# application/session.py
class SessionService:
    """Facade qui orchestre les composants."""
    def __init__(
        self,
        repository: SessionRepository,
        logger: SessionLogger,
    ):
        self.repository = repository
        self.logger = logger
```

---

## Phase 3 : Interfaces et Protocols (LSP, DIP) ✅ TERMINÉ

### 3.1 Créer les Protocols Core

```python
# core/protocols.py
from typing import Protocol, TypedDict, Any

class AgentResult(TypedDict):
    success: bool
    data: Any
    error: str | None

class Agent(Protocol):
    """Interface commune pour tous les agents."""
    name: str

    def run(self, task: str, **kwargs) -> AgentResult: ...

class Orchestrator(Protocol):
    """Interface pour orchestrateurs."""
    def process(self, request: str) -> OrchestratorResult: ...

class Tool(Protocol):
    """Interface pour outils."""
    name: str
    description: str

    def execute(self, ctx: ToolContext, **params) -> ToolResult: ...

class Store(Protocol[T]):
    """Interface générique pour stores."""
    def save(self, entity: T) -> None: ...
    def load(self, id: str) -> T | None: ...
    def delete(self, id: str) -> None: ...
```

---

### 3.2 Refactorer AgentCoordinator (OCP)

**Avant :** if/elif chain

```python
# MAUVAIS - Violation OCP
if agent_name == "DiagnosticAgent":
    result = self.diagnostic_agent.run(...)
elif agent_name == "RemediationAgent":
    result = self.remediation_agent.run(...)
```

**Après :** Registry pattern

```python
# agents/registry.py
class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent:
        if name not in self._agents:
            raise AgentNotFoundError(name)
        return self._agents[name]

# agents/coordinator.py
class AgentCoordinator:
    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def execute_step(self, step: PlanStep) -> AgentResult:
        agent = self.registry.get(step.agent_name)
        return agent.run(step.task, **step.params)  # Polymorphisme!
```

---

### 3.3 Hiérarchie d'Exceptions

```python
# core/exceptions.py
class AthenaError(Exception):
    """Base pour toutes les erreurs Athena."""
    pass

class ValidationError(AthenaError):
    """Erreur de validation (input, host, etc.)."""
    pass

class ExecutionError(AthenaError):
    """Erreur d'exécution de commande."""
    pass

class ConnectionError(AthenaError):
    """Erreur de connexion (SSH, DB, API)."""
    pass

class PlanError(AthenaError):
    """Erreur de planification."""
    pass

class AgentError(AthenaError):
    """Erreur d'agent."""
    pass
```

---

## Phase 4 : Clarifier les Boundaries (DDD, SoC)

### 4.1 Séparer `memory/` et `context/`

**Règle :**
- `domain/context/` = Contexte infrastructure (hosts, inventory)
- `infrastructure/repositories/` = Persistence (sessions, conversations)

```
# AVANT (confus)
memory/
├── session.py           # Mix DB + logic
├── conversation_manager.py
├── context_memory.py    # Overlap avec context/
└── storage.py

context/
├── manager.py           # Utilise memory.storage
├── host_registry.py
└── discovery.py

# APRÈS (clair)
domain/context/
├── manager.py           # Logique pure
├── discovery.py
└── inventory.py

infrastructure/repositories/
├── session.py           # SessionRepository
├── conversation.py      # ConversationStore
└── host.py              # HostRepository
```

---

### 4.2 Déplacer `sources/connectors/` vers Infrastructure

```
# AVANT
domains/sources/connectors/  # Mauvais placement DDD

# APRÈS
infrastructure/connectors/
├── base.py
├── postgres.py
├── mysql.py
├── mongodb.py
└── api.py
```

---

## Phase 5 : Nettoyage (YAGNI, KISS)

### 5.1 Supprimer le Code Mort

- [ ] `cot_orchestrator_example.py` → déplacer vers `tests/examples/`
- [ ] Fonctions non utilisées dans les planners fusionnés
- [ ] Imports inutilisés (ruff les détecte)

### 5.2 Simplifier les Nommages

| Avant | Après |
|-------|-------|
| `Ag2Orchestrator` | `AutoGenOrchestrator` |
| `EnhancedAg2Orchestrator` | (supprimé, fusionné) |
| `SQLiteConversationManager` | `SQLiteConversationStore` |

---

## Checklist Pre-Commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.13.0
    hooks:
      - id: mypy
        additional_dependencies: [types-all]
```

---

## Ordre d'Exécution Recommandé

| Phase | Durée | Priorité |
|-------|-------|----------|
| 1.1 Fusionner orchestrateurs | 2h | 🔴 Critique |
| 1.2 Fusionner planners | 2h | 🔴 Critique |
| 1.3 Fusionner conversation managers | 1h | 🟠 Haute |
| 2.1 Découper autogen_tools.py | 3h | 🔴 Critique |
| 2.2 Découper SessionManager | 2h | 🟠 Haute |
| 3.1 Créer Protocols | 1h | 🟠 Haute |
| 3.2 Refactorer AgentCoordinator | 1h | 🟠 Haute |
| 3.3 Hiérarchie exceptions | 30min | 🟡 Moyenne |
| 4.1 Séparer memory/context | 2h | 🟡 Moyenne |
| 4.2 Déplacer connectors | 1h | 🟡 Moyenne |
| 5.x Nettoyage | 1h | 🟢 Basse |

**Total estimé : ~16h de travail**

---

## Métriques de Succès

| Métrique | Avant | Cible |
|----------|-------|-------|
| Fichiers > 500 lignes | 6 | 0 |
| Code dupliqué | ~3000 lignes | < 200 lignes |
| Protocols définis | 0 | 5+ |
| Variables globales | 8 | 0 |
| Test coverage | ~60% | 80%+ |
