# Configuration

Merlya utilise un système de configuration en couches avec des valeurs par défaut sensées.

## Fichiers de configuration

| Fichier | Objectif |
|---------|----------|
| `~/.merlya/config.yaml` | Configuration principale |
| `~/.merlya/merlya.db` | Inventaire des hôtes (SQLite) |
| `~/.merlya/history` | Historique des commandes |
| `~/.merlya/logs/` | Fichiers de logs |

## Fichier de configuration

La configuration est stockée dans `~/.merlya/config.yaml` :

```yaml
# ~/.merlya/config.yaml
general:
  language: fr          # Langue de l'interface (en, fr)
  log_level: info       # debug, info, warning, error

model:
  provider: openrouter  # openrouter, anthropic, openai, mistral, groq, ollama
  model: amazon/nova-2-lite-v1:free
  api_key_env: OPENROUTER_API_KEY

router:
  type: local           # local (pattern matching) ou llm
  llm_fallback: openrouter:google/gemini-2.0-flash-lite-001

ssh:
  connect_timeout: 30
  pool_timeout: 600
  command_timeout: 60
```

## Définir des valeurs

Utilisez la commande `config` pour gérer les paramètres :

```bash
# Définir une valeur
merlya config set model.provider anthropic

# Obtenir une valeur
merlya config get model.provider

# Afficher tous les paramètres
merlya config show
```

## Variables d'environnement

Les clés API et paramètres peuvent être définis via des variables d'environnement :

```bash
export OPENROUTER_API_KEY=or-xxx
export ANTHROPIC_API_KEY=sk-ant-xxx
export OPENAI_API_KEY=sk-xxx
export MISTRAL_API_KEY=xxx
export GROQ_API_KEY=gsk_xxx
export OLLAMA_API_KEY=xxx  # Pour Ollama cloud uniquement

# Remplacer les paramètres
export MERLYA_ROUTER_FALLBACK=openai:gpt-4o-mini
```

## Configuration LLM

### Paramètres du fournisseur

| Paramètre | Description | Défaut |
|-----------|-------------|--------|
| `model.provider` | Fournisseur LLM | `openrouter` |
| `model.model` | Nom/ID du modèle | `amazon/nova-2-lite-v1:free` |
| `model.api_key_env` | Nom de la variable d'env pour la clé API | auto |

**Fournisseurs supportés :**

| Fournisseur | Description |
|-------------|-------------|
| `openrouter` | 100+ modèles, tier gratuit disponible (défaut) |
| `anthropic` | Modèles Claude |
| `openai` | Modèles GPT |
| `mistral` | Modèles Mistral AI |
| `groq` | Inférence ultra-rapide |
| `ollama` | Modèles locaux ou cloud |

### Clés API

Les clés API sont stockées de manière sécurisée dans le keyring système (recommandé) ou fournies via des variables d'environnement :

- **macOS** : Keychain
- **Linux** : Secret Service (GNOME Keyring, KWallet)
- **Windows** : Credential Manager

```bash
# Dans le REPL, Merlya peut demander et stocker votre clé :
merlya
/model provider openai

# Ou dans les environnements non-interactifs (CI/CD) :
export OPENAI_API_KEY="..."

# Les clés ne sont jamais écrites dans les fichiers de config
cat ~/.merlya/config.yaml | grep api_key
# (pas de sortie - seulement la référence api_key_env, pas la vraie clé)
```

## Configuration SSH

| Paramètre | Description | Défaut |
|-----------|-------------|--------|
| `ssh.connect_timeout` | Timeout de connexion (secondes) | `30` |
| `ssh.pool_timeout` | Timeout du pool (secondes) | `600` |
| `ssh.command_timeout` | Timeout d'exécution de commande | `60` |

## Gestion des hôtes

Les hôtes sont stockés dans une base SQLite (`~/.merlya/merlya.db`) et gérés via des commandes slash :

```bash
# Ajouter un hôte interactivement
/hosts add web-01

# Importer depuis la config SSH
/hosts import ~/.ssh/config --format=ssh

# Importer depuis /etc/hosts
/hosts import /etc/hosts --format=etc_hosts

# Lister tous les hôtes
/hosts list

# Afficher les détails d'un hôte
/hosts show web-01
```

**Formats d'import supportés :**

| Format | Description |
|--------|-------------|
| `ssh` | Fichier config SSH (`~/.ssh/config`) |
| `etc_hosts` | Format Linux `/etc/hosts` |
| `json` | Tableau JSON d'objets hôtes |
| `yaml` | Configuration YAML des hôtes |
| `csv` | CSV avec colonnes : name, hostname, port, username |

## Journalisation

Merlya utilise [loguru](https://github.com/Delgan/loguru) pour la journalisation.

| Paramètre | Description | Défaut |
|-----------|-------------|--------|
| `general.log_level` | Niveau de log console | `info` |
| `logging.file_level` | Niveau de log fichier | `debug` |
| `logging.max_size_mb` | Taille max du fichier de log | `10` |

Les logs sont stockés dans `~/.merlya/logs/`.

## Étapes suivantes

- [Guide de gestion SSH](../guides/ssh-management.md)
- [Guide des fournisseurs LLM](../guides/llm-providers.md)
- [Guide d'automatisation](../guides/automation.md)
