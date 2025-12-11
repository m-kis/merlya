<p align="center">
  <img src="https://merlya.fr/static/media/logo.41177386c9cd7ecf8aaa.png" alt="Merlya Logo" width="120">
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
</p>

<p align="center">
  <img src="https://img.shields.io/badge/code%20style-ruff-000000" alt="Ruff">
  <img src="https://img.shields.io/badge/type%20checked-mypy-blue" alt="mypy">
</p>

<p align="center">
  <a href="[README_EN.md]">Read in English</a>
</p>

---

## Aperçu

Merlya est un assistant CLI autonome qui comprend le contexte de votre infrastructure, planifie des actions intelligentes et les exécute en toute sécurité. Il combine un router d’intentions local (ONNX) avec un fallback LLM via PydanticAI, un pool SSH sécurisé, et une gestion d’inventaire simplifiée.

### Fonctionnalités clés

- Commandes en langage naturel pour diagnostiquer et remédier vos environnements
- Pool SSH async avec MFA/2FA, jump hosts et SFTP
- Inventaire `/hosts` avec import intelligent (SSH config, /etc/hosts, Ansible)
- Router local-first (gte/EmbeddingGemma/e5) avec fallback LLM configurables
- Sécurité by design : secrets dans le keyring, validation Pydantic, logs cohérents
- Extensible (agents modulaires Docker/K8s/CI/CD) et i18n (fr/en)
- Intégration MCP pour consommer des tools externes (GitHub, Slack, custom) via `/mcp`

## Installation (utilisateurs finaux)

```bash
pip install merlya          # Installation standard
pip install merlya[router]  # Avec router ONNX local
pip install merlya[all]     # Tous les extras

# Lancer l’assistant
merlya
```

> ONNX n'a pas encore de roues Python 3.14 : utilisez Python ≤ 3.13 pour `[router]`.

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
> Check disk usage on @web-prod-01
> /hosts list
> /ssh exec @db-01 "uptime"
> /model router show
> /variable set region eu-west-1
> /mcp list
```

## Sécurité

### Secrets et références @secret

Les secrets (mots de passe, tokens, clés API) sont stockés dans le keyring système (macOS Keychain, Linux Secret Service) et référencés par `@nom-secret` dans les commandes :

```bash
> Connect to MongoDB with @db-password
# Merlya résout @db-password depuis le keyring avant exécution
# Les logs affichent @db-password, jamais la vraie valeur
```

### Élévation de privilèges

Merlya détecte automatiquement les capacités d'élévation (sudo, doas, su) et gère les mots de passe de manière sécurisée :

1. **sudo NOPASSWD** - Meilleur choix, pas de mot de passe
2. **doas** - Souvent sans mot de passe sur BSD
3. **sudo avec mot de passe** - Fallback standard
4. **su** - Dernier recours, nécessite le mot de passe root

Les mots de passe d'élévation sont stockés dans le keyring et référencés par `@elevation:hostname:password`.

### Détection de boucles

L'agent détecte les patterns répétitifs (même outil appelé 3+ fois, alternance A-B-A-B) et injecte un message pour rediriger vers une approche différente.

## Configuration

- Fichier utilisateur : `~/.merlya/config.yaml` (langue, modèle, timeouts SSH, UI).
- Clés API : stockées dans le keyring. Fallback en mémoire avec avertissement.
- Variables d'environnement utiles :

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Clé Anthropic |
| `OPENAI_API_KEY` | Clé OpenAI |
| `OPENROUTER_API_KEY` | Clé OpenRouter |
| `MERLYA_ROUTER_FALLBACK` | Modèle de fallback LLM |
| `MERLYA_LOG_LEVEL` | Niveau de log (debug, info, warning, error) |

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

- [docs/architecture.md](docs/architecture.md) : architecture et décisions
- [docs/commands.md](docs/commands.md) : commandes slash
- [docs/configuration.md](docs/configuration.md) : configuration complète
- [docs/tools.md](docs/tools.md) : tools et agents
- [docs/ssh.md](docs/ssh.md) : SSH, bastions, MFA
- [docs/extending.md](docs/extending.md) : extensions/agents

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
  Made with ❤️ by <a href="https://github.com/m-kis">M-KIS</a>
</p>
