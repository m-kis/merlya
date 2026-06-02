> ## ⚠️ Projet archivé — non maintenu
>
> **Merlya n'est plus activement développé** (dernière version : `v0.8.5`, février 2026).
>
> **Pourquoi ?** La montée en puissance rapide des agents CLI génériques — **Claude Code**, Codex CLI, Gemini CLI et consorts — a largement absorbé la proposition de valeur de Merlya. Portés par les grands laboratoires d'IA, ces outils couvrent désormais l'essentiel de l'expérience « assistant CLI en langage naturel » avec des moyens sans commune mesure avec ceux d'un projet indépendant. Maintenir un concurrent sur ce terrain n'est plus pertinent **pour le moment**.
>
> Le code reste consultable, réutilisable et installable (`pip install merlya`) sous licence MIT + Commons Clause, **à des fins d'archive uniquement** : aucune nouvelle fonctionnalité, correction de bug ni mise à jour de sécurité n'est prévue. Comme l'outil manipule SSH, des secrets et de l'élévation de privilèges, évaluez ce risque avant tout usage en production.
>
> Merci à toutes celles et ceux qui ont testé et soutenu le projet. 🙏

<p align="center">
  <img src="https://merlya.m-kis.fr/assets/logo.png" alt="Merlya Logo" width="120">
</p>

<h1 align="center">Merlya</h1>

<p align="center">
  <strong>AI-powered infrastructure assistant for DevOps & SysAdmins</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/merlya/"><img src="https://img.shields.io/pypi/v/merlya?color=%2340C4E0" alt="PyPI"></a>
  <a href="https://pypi.org/project/merlya/"><img src="https://img.shields.io/pypi/pyversions/merlya" alt="Python"></a>
  <a href="https://pypi.org/project/merlya/"><img src="https://img.shields.io/pypi/dm/merlya" alt="Downloads"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT%20%2B%20Commons%20Clause-blue" alt="License"></a>
  <a href="https://merlya.m-kis.fr/"><img src="https://img.shields.io/badge/docs-merlya.m--kis.fr-40C4E0" alt="Documentation"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-archived-lightgrey" alt="Status: Archived">
  <img src="https://img.shields.io/badge/maintenance-no%20longer%20maintained-red" alt="Unmaintained">
  <img src="https://img.shields.io/badge/code%20style-ruff-000000" alt="Ruff">
  <img src="https://img.shields.io/badge/type%20checked-mypy-blue" alt="mypy">
</p>

<p align="center">
  <a href="https://github.com/m-kis/merlya/blob/main/README_EN.md">Read in English</a>
</p>

---

## Aperçu

Merlya est un assistant CLI autonome qui comprend le contexte de votre infrastructure, planifie des actions intelligentes et les exécute en toute sécurité. Il combine un **SmartExtractor** (LLM + regex hybride) pour extraire les hosts des requêtes en langage naturel, un pool SSH sécurisé, et une gestion d'inventaire simplifiée.

### Fonctionnalités clés

- **Commandes en langage naturel** pour diagnostiquer et remédier vos environnements
- **Architecture spécialistes** : `MerlyaAgent` délègue aux spécialistes (diagnostic, exécution, sécurité) selon la demande
- **Pool SSH async** avec MFA/2FA, jump hosts et SFTP
- **Inventaire `/hosts`** avec import intelligent (SSH config, /etc/hosts, Ansible, TOML, CSV)
- **Modèles brain/fast** : brain pour le raisonnement complexe, fast pour les décisions rapides
- **Pipelines IaC** : Ansible, Terraform, Kubernetes, Bash avec HITL obligatoire
- **Élévation explicite** : configuration sudo/doas/su par host (pas d'auto-détection)
- **Sécurité by design** : secrets dans le keyring, validation Pydantic, détection de boucles
- **Observabilité** : métriques in-memory + circuit breaker / retry (`/metrics`)
- **i18n** : français et anglais
- **Intégration MCP** pour consommer des tools externes (GitHub, Slack, custom) via `/mcp`

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INPUT                                      │
│                    "Check disk on web-01 via bastion"                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SMART EXTRACTOR                                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │ Fast Model  │───▶│   Regex     │───▶│   Hosts     │                      │
│  │ (semantic)  │    │  Patterns   │    │  Inventory  │                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
│  Output: hosts=[web-01], via=bastion, context injected                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MERLYA AGENT                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  System prompt guides delegation decision (no separate classifier)  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│        │                    │                    │                    │      │
│        ▼                    ▼                    ▼                    ▼      │
│  ┌──────────┐        ┌──────────┐        ┌──────────┐        ┌──────────┐   │
│  │Diagnostic│        │Execution │        │Security  │        │ Query    │   │
│  │Specialist│        │Specialist│        │Specialist│        │Specialist│   │
│  │read-only │        │HITL+pipes│        │sec audits│        │inventory │   │
│  └──────────┘        └──────────┘        └──────────┘        └──────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SECURITY LAYER                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │  Keyring    │    │  Elevation  │    │    Loop     │                      │
│  │  Secrets    │    │  Explicit   │    │  Detection  │                      │
│  │ @secret-ref │    │ (per-host)  │    │ (5+ repeat) │                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            SSH POOL                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │ Connection  │    │  Jump Host  │    │    MFA      │                      │
│  │   Reuse     │    │   Support   │    │   Support   │                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PERSISTENCE                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  Hosts   │  │ Sessions │  │  Audit   │  │ Raw Logs │  │ Messages │       │
│  │ Inventory│  │ Context  │  │   Logs   │  │  (TTL)   │  │ History  │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│                         SQLite + Keyring                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Installation (utilisateurs finaux)

```bash
pip install merlya
merlya
```

### Installation Docker

```bash
# Copier et configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec vos clés API

# Lancer le conteneur
docker compose up -d

# Mode développement (code source monté)
docker compose --profile dev up -d
```

**Configuration SSH pour Docker :**

Le conteneur monte votre répertoire SSH local. Par défaut, il utilise `$HOME/.ssh`.

Dans les environnements CI/CD où `$HOME` peut ne pas être défini, vous devez explicitement définir `SSH_DIR` :

```bash
# Via variable d'environnement
SSH_DIR=/root/.ssh docker compose up -d

# Ou dans votre fichier .env
SSH_DIR=/home/jenkins/.ssh
```

**Permissions requises :**
- Répertoire SSH : `700` (rwx pour propriétaire uniquement)
- Clés privées : `600` (rw pour propriétaire uniquement)

Voir `.env.example` pour la documentation complète des variables.

### Premier démarrage

1. Sélection de la langue (fr/en)
2. Configuration du provider LLM (clé stockée dans le keyring)
3. Scan local et import d’hôtes (SSH config, /etc/hosts, inventaires Ansible)
4. Health checks (RAM, disque, LLM, SSH, keyring, web search)

## Exemples rapides

```bash
> Check disk usage on web-prod-01
> /hosts list
> /ssh exec db-01 "uptime"
> /model show
> /metrics
> /variable set region eu-west-1
> /mcp list
```

> **Syntaxe des targets** :
>
> - `@web-01` → lookup inventaire (hostname + username résolus depuis la base)
> - `ubuntu@192.168.1.5` → utilisateur SSH explicite + IP
> - `192.168.1.5` → IP directe (username depuis l'inventaire si connu)
> - `@db-password` → référence secret dans le keyring (résolu à l'exécution)

## Sécurité

### Secrets — jamais exposés au LLM

Les secrets (mots de passe, tokens, clés API) sont stockés dans le **keyring système** (macOS Keychain, Linux Secret Service) et référencés par `@nom-secret` :

```bash
> Connect to MongoDB with @db-password
# Le LLM voit "@db-password", jamais la valeur réelle
# Résolution uniquement au moment de l'exécution
# Logs : "mongo -p ***", jamais la vraie valeur
```

### HITL — confirmation obligatoire

Toute opération destructive (restart, écriture fichier, installation) requiert une **confirmation explicite** avant exécution. L'`ExecutionSpecialist` ne peut pas contourner ce mécanisme.

### Élévation de privilèges

L'élévation (sudo, doas, su) est **toujours explicite** — jamais auto-détectée. Elle se configure par host et les mots de passe sont stockés dans le keyring sous `elevation:hostname:password`.

### Détection de boucles

Le `ToolCallTracker` détecte les patterns répétitifs (même commande 3+ fois, alternance A-B-A-B) et stoppe l'exécution automatiquement.

## Configuration

- Fichier utilisateur : `~/.merlya/config.yaml` (langue, modèle, timeouts SSH, UI).
- Clés API : stockées dans le keyring. Fallback en mémoire avec avertissement.
- Variables d'environnement utiles :

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | Clé OpenRouter (provider par défaut) |
| `ANTHROPIC_API_KEY` | Clé Anthropic |
| `OPENAI_API_KEY` | Clé OpenAI |
| `MISTRAL_API_KEY` | Clé Mistral |
| `GROQ_API_KEY` | Clé Groq |
| `MERLYA_ROUTER_FALLBACK` | Modèle LLM de fallback pour le routage |

## Installation pour contributeurs

```bash
git clone https://github.com/m-kis/merlya.git
cd merlya
python -m venv .venv
source .venv/bin/activate  # ou .venv\\Scripts\\activate sous Windows
pip install -e ".[dev]"    # Dépendances de dev

merlya --version
pytest tests/ -v
```

## Qualité et scripts

| Vérification | Commande |
|--------------|----------|
| Lint | `ruff check merlya/` |
| Format (check) | `ruff format --check merlya/` |
| Type check | `mypy merlya/` |
| Tests + coverage | `pytest tests/ --cov=merlya --cov-report=term-missing` |
| Sécurité (code) | `bandit -r merlya/ -c pyproject.toml` |
| Sécurité (dépendances) | `pip-audit -r <(pip freeze)` |

Principes clés : DRY/KISS/YAGNI, SOLID, SoC, LoD, pas de fichiers > ~600 lignes, couverture ≥ 80%, commits conventionnels (cf. [CONTRIBUTING.md](CONTRIBUTING.md)).

## CI/CD

- `.github/workflows/ci.yml` : lint + format check + mypy + tests + sécurité (Bandit + pip-audit) sur runners GitHub pour chaque PR/push.
- `.github/workflows/release.yml` : build + release GitHub + publication PyPI via trusted publishing, déclenché sur tag `v*` ou `workflow_dispatch` par un mainteneur (pas de secrets sur les PR externes).
- Branche `main` protégée : merge via PR, CI requis, ≥1 review, squash merge recommandé.

## Documentation

📚 **Documentation complète** : [https://merlya.m-kis.fr/](https://merlya.m-kis.fr/)

Fichiers locaux :
- [docs/architecture.md](docs/architecture.md) : architecture et décisions
- [docs/commands.md](docs/commands.md) : commandes slash
- [docs/configuration.md](docs/configuration.md) : configuration complète
- [docs/tools.md](docs/tools.md) : tools et agents
- [docs/ssh.md](docs/ssh.md) : SSH, bastions, MFA
- [docs/extending.md](docs/extending.md) : extensions/agents
- [SECURITY.md](SECURITY.md) : modèle de sécurité et signalement de vulnérabilités

## Contribuer

- Lisez [CONTRIBUTING.md](CONTRIBUTING.md) pour les conventions (commits, branches, limites de taille de fichiers/fonctions).
- Respectez le [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- Les templates d’issues et de PR sont disponibles dans `.github/`.

## Sécurité

Consultez [SECURITY.md](SECURITY.md). Ne publiez pas de vulnérabilités en issue publique : écrivez à `security@merlya.fr`.

## Licence

[MIT avec Commons Clause](LICENSE). La Commons Clause interdit la vente du logiciel comme service hébergé tout en autorisant l’usage, la modification et la redistribution.

---

<p align="center">
  Made by <a href="https://github.com/m-kis">M-KIS</a>
</p>
