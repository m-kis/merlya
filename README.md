# Athena CLI

**AI-powered infrastructure orchestration tool** - Un DevOps IA qui agit avec tes droits SSH.

## 🎯 Philosophie

Athena utilise la **puissance des LLMs** pour comprendre et agir sur ton infrastructure. Pas d'agents spécialisés rigides - juste une IA intelligente qui :

- ✅ Lit le contexte pour les queries simples (pas de commandes inutiles)
- ✅ SSH sur tes machines quand nécessaire (avec tes clés SSH)
- ✅ Utilise `~/.ssh/config` et `ssh-agent` comme toi
- ✅ Comprend tes inventaires et se souvient de ton infra

## 🚀 Installation

```bash
# Clone le repo
cd athena

# Install dependencies
pip install -r requirements.txt
# ou avec poetry
poetry install

# Configure ton LLM provider
export ANTHROPIC_API_KEY="sk-..."
# ou OPENAI_API_KEY, OPENROUTER_API_KEY, etc.

# Init l'environnement
python3 -m athena_ai.cli init
```

## 📖 Usage

### 1. Scanner l'infrastructure

```bash
# Scan initial : détecte /etc/hosts + SSH sur les machines
python3 -m athena_ai.cli init

# Re-scan si besoin
python3 -m athena_ai.cli scan
```

### 2. Poser des questions

#### Questions sur l'inventaire (lecture contexte)

```bash
# Liste des IPs
python3 -m athena_ai.cli ask "give me the list of the ip of mongo preprod"

# Résultat :
# Preprod MongoDB IPs:

```

#### Questions nécessitant SSH (état live)

```bash
# Check service status
python3 -m athena_ai.cli ask "check if mongodb is running on mongo-preprod-1"

# Dry-run pour voir le plan
python3 -m athena_ai.cli ask "check mongodb status on all preprod hosts" --dry-run

# Actions critiques (restart, etc.)
python3 -m athena_ai.cli ask "restart nginx on web-prod-001" --confirm
```

### 3. Flags utiles

```bash
--dry-run      # Simule les actions sans exécuter
--confirm      # Auto-confirme les actions critiques
--verbose      # Mode debug
--env dev      # Change l'environnement (dev/staging/prod)
--model gpt-4  # Override le modèle AI
```

## 🏗️ Architecture

```
User Query
    ↓
Orchestrator (cerveau)
    ↓
LLM Router (multi-provider)
    ↓
Context Manager ← Discovery (scan SSH)
    ↓
AI Decision:
  - Réponse directe (si info dans contexte)
  - Actions SSH (si besoin état live)
    ↓
ActionExecutor → SSHManager (avec tes clés)
```

## 🔑 SSH & Credentials

Athena utilise **tes credentials existantes** :

1. **ssh-agent** (si disponible)
2. **~/.ssh/config** (user et clés par host)
3. **~/.ssh/id_ed25519**, **id_rsa**, etc.

Exemple `~/.ssh/config` :
```ssh
Host mongo-preprod-*
    User mongodb-admin
    IdentityFile ~/.ssh/id_mongo_preprod

Host *.prod
    User root
    IdentityFile ~/.ssh/id_prod
```

Athena respectera ces configs automatiquement.

## 🧠 Comment l'IA Décide

L'IA reçoit un **système prompt expert** avec :

```
INFRASTRUCTURE CONTEXT:
INVENTORY (hostname -> IP):
  - mongo-preprod-1: 203.0.113.10
  - mongo-preprod-2: 198.51.100.20
  ...

REMOTE HOSTS (detailed info from SSH scan):
mongo-preprod-1 (203.0.113.10):
  - OS: Linux
  - Kernel: 5.15.0-89-generic
  - Running services: mongod.service, nginx.service, datadog-agent.service

IMPORTANT RULES:
- NEVER use 'echo' commands - extract info from context
- Only SSH when you need LIVE state (CPU, status, logs)
- Be smart: "list IPs" = context, "check status" = SSH
```

L'IA comprend :
- **Query informationelle** → Lit le contexte, répond directement
- **Query diagnostique** → Génère commandes SSH intelligentes

## 📊 Exemples Concrets

### ✅ Bon Comportement (Après Fix)

```bash
$ python3 -m athena_ai.cli ask "list mongo preprod IPs"



# 0 commandes exécutées ✅
```

### ❌ Ancien Comportement (Avant Fix)

```bash
$ athena ask "list mongo preprod IPs"

# Générait 7 commandes echo inutiles
# Temps: 15s, erreurs "requires confirmation"
```

## 🛠️ Configuration

### LLM Providers

```bash
# Anthropic (Claude)
export ANTHROPIC_API_KEY="sk-ant-..."

# OpenAI
export OPENAI_API_KEY="sk-..."

# OpenRouter (multi-models)
export OPENROUTER_API_KEY="sk-or-..."
export OPENROUTER_MODEL="anthropic/claude-3-opus"

# Ollama (local)
export OLLAMA_MODEL="llama3"
```

### Environnements

Par défaut : `~/.athena/{env}/`
- `dev/` (default)
- `staging/`
- `prod/`

Chaque env a son propre contexte, mémoire, logs.

## 🔒 Sécurité

### Risk Assessment

Toutes les commandes sont évaluées :
- **Low** : read-only (ps, cat, grep) → Exécution automatique
- **Moderate** : reload, chmod → Demande confirmation
- **Critical** : restart, stop, rm, reboot → **Requiert --confirm**

### Audit Trail

Toutes les actions sont loguées dans `athena_ai.log`.

## 📈 Roadmap

- [x] SSH avec credentials user
- [x] Prompts intelligents (contexte vs SSH)
- [x] Discovery automatique via SSH
- [ ] Memory persistante (snapshots, rollback)
- [ ] Ansible/Terraform integration
- [ ] Multi-cloud (AWS, GCP, K8s)
- [ ] REPL interactif

## 🤝 Contributing

Athena coding style :
- Python 3.11+
- Type hints partout
- Logs avec loguru
- Tests avec pytest

## 📝 License

MIT

---

**Made with ❤️ by Athena Contributors**
