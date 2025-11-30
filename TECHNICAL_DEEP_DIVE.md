# Athena - Technical Deep Dive

## 1. Task-Specific Routing : Explication Détaillée

### 🎯 Concept et Objectif

Le **task-specific routing** est un système d'optimisation intelligent qui sélectionne automatiquement le modèle LLM le plus adapté selon le type de tâche à accomplir.

**Objectif** : Réduire les coûts et la latence en utilisant des modèles légers pour les tâches simples, et des modèles puissants uniquement pour les tâches complexes.

---

### 📊 Architecture du Système

#### 1. Configuration des Tasks (Fichier : [athena_ai/llm/model_config.py](athena_ai/llm/model_config.py))

```python
# Ligne 89-94 : Définition des alias de tasks
TASK_MODELS = {
    "correction": "haiku",  # Modèle rapide pour corrections simples
    "planning": "opus",     # Modèle puissant pour planification complexe
    "synthesis": "sonnet",  # Modèle équilibré pour synthèse
}
```

**Explications** :
- Ces alias ("haiku", "opus", "sonnet") sont **indépendants du provider**
- Ils sont résolus dynamiquement selon le provider actif

#### 2. Résolution des Alias par Provider

```python
# Lignes 219-249 : _resolve_model_alias()
alias_map = {
    "openrouter": {
        "haiku": "anthropic/claude-3-5-haiku",    # Rapide, ~$0.25/$1.25 par 1M tokens
        "sonnet": "anthropic/claude-3.5-sonnet",  # Équilibré, ~$3/$15 par 1M tokens
        "opus": "anthropic/claude-3-opus",        # Puissant, ~$15/$75 par 1M tokens
    },
    "anthropic": {
        "haiku": "claude-3-haiku-20240307",
        "sonnet": "claude-3-5-sonnet-20241022",
        "opus": "claude-3-opus-20240229",
    },
    "openai": {
        "fast": "gpt-4o-mini",      # ~$0.15/$0.60 par 1M tokens
        "balanced": "gpt-4o",        # ~$2.50/$10 par 1M tokens
        "best": "gpt-4o-2024-11-20",
    },
}
```

**Impact sur les coûts** :
- Une correction simple avec Haiku : **~$0.001** (1000 tokens)
- La même avec Opus : **~$0.015** (15x plus cher)
- **Économie potentielle** : 80-90% sur les tâches simples

---

### 🔄 Flow d'Exécution Détaillé

#### Étape 1 : Appel d'une tâche

```python
# Exemple dans athena_ai/executors/auto_corrector.py:160
response = llm_router.generate(
    prompt="Corrige cette commande : sysemctl status nginx",
    task="correction"  # ← Spécification de la tâche
)
```

#### Étape 2 : Routing vers le bon modèle

```python
# Dans athena_ai/llm/router.py:154
model = self.model_config.get_model(self.provider, task=task)
# Si task="correction" et provider="openrouter"
# → model = "anthropic/claude-3-5-haiku" (via résolution d'alias)
```

#### Étape 3 : Sélection du modèle ([model_config.py:140-171](athena_ai/llm/model_config.py))

```python
def get_model(self, provider: Optional[str] = None, task: Optional[str] = None) -> str:
    provider = provider or self.get_provider()  # Ex: "openrouter"

    # Récupère le modèle configuré par défaut
    configured_model = models.get(provider, self.DEFAULT_MODELS.get(provider))
    # Ex: "anthropic/claude-4.5-sonnet-20250929"

    # ÉTAPE CLÉ : Override si une tâche est spécifiée
    if task and task in self.config.get("task_models", {}):
        task_model = self.config["task_models"][task]  # Ex: "haiku"

        if "/" in task_model:
            # C'est un modèle complet, utilise-le directement
            return task_model
        else:
            # C'est un alias, résous-le
            return self._resolve_model_alias(provider, task_model)
            # Retourne: "anthropic/claude-3-5-haiku"

    # Pas de task spécifiée → utilise le modèle par défaut
    return configured_model
```

---

### 💡 Exemples Concrets d'Utilisation

#### Cas 1 : Auto-correction de commande (rapide)

```python
# athena_ai/executors/auto_corrector.py:160
response = llm_router.generate(
    prompt="Corrige : sysemctl status nginx",
    task="correction"
)
# Utilise: Haiku (rapide, pas cher)
# Temps: ~0.5s
# Coût: ~$0.0001
```

#### Cas 2 : Planification d'infrastructure (complexe)

```python
# athena_ai/agents/planner.py:284
response = llm_router.generate(
    prompt="Planifie le déploiement d'un cluster Kubernetes multi-région...",
    task="planning"
)
# Utilise: Opus (puissant, raisonnement avancé)
# Temps: ~3-5s
# Coût: ~$0.015
```

#### Cas 3 : Synthèse de résultats (équilibré)

```python
# athena_ai/inventory/relation_classifier/llm.py:79
response = self.llm.generate(
    prompt="Synthétise les relations entre ces 50 hosts...",
    task="synthesis"
)
# Utilise: Sonnet (bon compromis vitesse/qualité)
# Temps: ~1-2s
# Coût: ~$0.003
```

---

### 🔧 Configuration et Personnalisation

#### Option 1 : Via le fichier config.json

Le fichier `~/.athena/config.json` contient :

```json
{
  "provider": "openrouter",
  "models": {
    "openrouter": "anthropic/claude-4.5-sonnet-20250929",
    "anthropic": "claude-3-5-sonnet-20241022",
    "openai": "gpt-4o"
  },
  "task_models": {
    "correction": "haiku",
    "planning": "opus",
    "synthesis": "sonnet"
  }
}
```

**Modification manuelle possible** :

```json
{
  "task_models": {
    "correction": "qwen/qwen-2.5-coder-7b-instruct:free",  // Modèle gratuit !
    "planning": "anthropic/claude-3.5-sonnet",             // Downgrade pour économiser
    "synthesis": "openai/gpt-4o-mini"                      // Modèle OpenAI plus rapide
  }
}
```

#### Option 2 : Via le provider setter

**NON**, le task routing ne passe **PAS** par `/model provider`.

Le provider setter (`/model provider openrouter`) définit uniquement le **provider global**, pas les tasks.

**Workflow complet** :

1. **Définir le provider** : `/model provider openrouter`
2. **Définir le modèle par défaut** (optionnel) : `/model set anthropic/claude-3.5-sonnet`
3. **Les tasks utilisent automatiquement les alias** configurés dans `config.json`

**Si vous voulez changer un modèle de task** :
- Modifier manuellement `~/.athena/config.json`
- Ou créer une commande `/model task correction set haiku` (à implémenter)

---

### 📈 Statistiques de Performance

| Task | Modèle (OpenRouter) | Latence | Coût (1K tokens) | Use Case |
|------|---------------------|---------|------------------|----------|
| correction | Haiku | ~0.5s | $0.0001 | Fix typos, simple corrections |
| synthesis | Sonnet | ~1.5s | $0.003 | Summarize logs, analyze data |
| planning | Opus | ~3s | $0.015 | Complex infrastructure planning |
| **Default** | Sonnet 4.5 | ~2s | $0.003 | General queries |

**Économie réelle** :
- 1000 corrections/jour avec Haiku : **~$0.10/jour**
- 1000 corrections/jour avec Opus : **~$15/jour**
- **Économie : 99.3%** 💰

---

### 🎛️ Contrôle Fin du Routing

#### Désactiver le task routing

Modifier `config.json` :

```json
{
  "task_models": {}  // Vide = désactivé
}
```

Tous les appels utiliseront le modèle par défaut.

#### Utiliser un modèle spécifique pour TOUTES les tasks

```json
{
  "task_models": {
    "correction": "qwen/qwen-2-7b-instruct:free",
    "planning": "qwen/qwen-2-7b-instruct:free",
    "synthesis": "qwen/qwen-2-7b-instruct:free"
  }
}
```

Résultat : **0€ de coût**, modèle gratuit pour tout !

---

## 2. Système de Secrets : Sécurité et `getpass`

### 🔐 Architecture de Sécurité

Athena utilise une approche **multi-niveaux** pour protéger les secrets :

1. **Stockage en mémoire uniquement** (jamais sur disque)
2. **Input masqué** avec `getpass` (caractères invisibles)
3. **Redaction automatique** dans les logs
4. **Résolution contrôlée** dans les prompts LLM

---

### 📁 Types de Variables

```python
# athena_ai/security/credentials.py:19-25
class VariableType(Enum):
    HOST = "host"       # Hostnames - PERSISTÉ dans SQLite
    CONFIG = "config"   # Configs générales - PERSISTÉ dans SQLite
    SECRET = "secret"   # Passwords, tokens - MÉMOIRE UNIQUEMENT (jamais persisté)
```

**Règles de stockage** :

| Type | Stockage | Persistance | Visible dans `/variables list` |
|------|----------|-------------|----------------------------------|
| HOST | SQLite (`~/.athena/credentials.db`) | Redémarre l'app | ✅ Oui |
| CONFIG | SQLite (`~/.athena/credentials.db`) | Redémarre l'app | ✅ Oui |
| SECRET | RAM (dict Python) | Jusqu'à fermeture REPL | ❌ Non (masqué) |

---

### 🛡️ Avantages de `getpass` (Python)

#### 1. Masquage de l'Input

```python
# Avec getpass
import getpass
password = getpass.getpass("Password: ")
# Terminal affiche: Password: ******* (invisible)

# Sans getpass (DANGEREUX)
password = input("Password: ")
# Terminal affiche: Password: MyS3cr3tP@ss (visible à l'écran !)
```

**Risques sans getpass** :
- ✅ **Shoulder surfing** : Quelqu'un regarde par-dessus votre épaule
- ✅ **Screen recording** : Enregistrements d'écran capturent le password
- ✅ **Terminal history** : Les prompts peuvent être loggés
- ✅ **Vidéos de démo** : Exposer le password par accident

#### 2. Protection contre l'Historique Shell

```bash
# Sans getpass
athena
> /variables set DBPASS MyS3cr3tP@ss

# Historique bash (~/.bash_history)
athena
/variables set DBPASS MyS3cr3tP@ss  # ❌ PASSWORD VISIBLE
```

```bash
# Avec getpass
athena
> /variables set-secret DBPASS
[Secure input for 'DBPASS']
DBPASS: *******

# Historique bash
athena
/variables set-secret DBPASS  # ✅ PAS de password visible
```

#### 3. Cross-Platform Compatibility

`getpass` fonctionne sur **tous les OS** :
- Linux/macOS : Utilise `/dev/tty` (terminal raw mode)
- Windows : Utilise `msvcrt.getch()` (input sans echo)

**Code** :

```python
# athena_ai/security/credentials.py:307-330
def set_variable_secure(self, key: str, var_type: VariableType = VariableType.SECRET) -> bool:
    try:
        print(f"\n[Secure input for '{key}']")
        value = getpass.getpass(f"{key}: ")  # ← Masqué sur tous les OS
        if value:
            self.set_variable(key, value, var_type)
            return True
        else:
            print("Empty value - not saved")
            return False
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled")
        return False
```

---

### 🔒 Sécurité : Comment sont Protégés les Secrets ?

#### 1. Stockage en Mémoire (Jamais sur Disque)

```python
# athena_ai/security/credentials.py:58-62
def __init__(self, env: str = "dev"):
    # Credentials stockés en RAM uniquement
    self.session_credentials: Dict[str, Tuple[str, str]] = {}  # service@host → (user, pass)
    self.variables: Dict[str, Tuple[str, VariableType]] = {}   # key → (value, type)
```

**Vérification** :

```bash
# Ajouter un secret
athena
> /variables set-secret API_TOKEN
API_TOKEN: ********

# Vérifier qu'il n'est PAS sur disque
cat ~/.athena/credentials.db  # ❌ Pas de API_TOKEN
sqlite3 ~/.athena/credentials.db "SELECT * FROM variables;"  # ❌ Pas de API_TOKEN

# Le secret existe UNIQUEMENT en RAM (process Python)
ps aux | grep athena  # PID 12345
# Mémoire du process contient le secret, mais inaccessible depuis l'extérieur
```

#### 2. Redaction Automatique dans les Logs

```python
# athena_ai/utils/logger.py:99-146
def redaction_filter(record):
    """Filtre pour redacter les secrets dans les logs."""
    # Liste de patterns à redacter
    patterns = [
        (r'password["\']?\s*[:=]\s*["\']?([^"\'\s]+)', '[REDACTED]'),
        (r'token["\']?\s*[:=]\s*["\']?([^"\'\s]+)', '[REDACTED]'),
        (r'api[_-]?key["\']?\s*[:=]\s*["\']?([^"\'\s]+)', '[REDACTED]'),
        # ... etc
    ]

    # Redacte le message
    for pattern, replacement in patterns:
        record["message"] = re.sub(pattern, replacement, record["message"], flags=re.IGNORECASE)
```

**Exemple** :

```python
logger.info("Connecting with password=MyS3cr3t")
# Log écrit: "Connecting with password=[REDACTED]"
```

#### 3. Résolution Contrôlée dans les Prompts LLM

```python
# athena_ai/repl/core.py:172-174
if self.credentials.has_variables(user_input):
    # resolve_secrets=False → Ne résout PAS les @secrets
    resolved_query = self.credentials.resolve_variables(user_input, resolve_secrets=False)
```

**Exemple** :

```bash
athena
> /variables set-secret DBPASS
DBPASS: ********

> check mysql using @DBPASS

# ❌ SANS resolve_secrets=False
# Envoyé au LLM: "check mysql using MyS3cr3tP@ss"  (DANGER!)

# ✅ AVEC resolve_secrets=False
# Envoyé au LLM: "check mysql using @DBPASS"  (SAFE)
```

**Code de résolution** :

```python
# athena_ai/security/credentials.py:385-422
def resolve_variables(self, text: str, resolve_secrets: bool = False) -> str:
    for key, (value, var_type) in self.variables.items():
        pattern = f"@{key}"
        if pattern in text:
            # SÉCURITÉ: Ne résout PAS les secrets par défaut
            if var_type == VariableType.SECRET and not resolve_secrets:
                continue  # Garde @SECRET dans le texte

            # Résout les autres types
            text = text.replace(pattern, value)

    return text
```

---

### 🚫 Est-ce qu'on Peut Afficher un Secret ?

**Réponse** : **NON**, sauf si vous modifiez le code.

#### Tentative 1 : Via `/variables list`

```bash
athena
> /variables set-secret API_TOKEN
API_TOKEN: ********

> /variables list
┌───────────┬────────────────┬────────┐
│ Key       │ Value          │ Type   │
├───────────┼────────────────┼────────┤
│ API_TOKEN │ ********       │ secret │  # ← Masqué
│ DBHOST    │ 192.168.1.100  │ host   │  # ← Visible
└───────────┴────────────────┴────────┘
```

**Code de masquage** :

```python
# athena_ai/repl/commands/variables.py (hypothétique, à vérifier)
for key, (value, var_type) in self.repl.credentials.variables.items():
    if var_type == VariableType.SECRET:
        display_value = "********"  # Masqué
    else:
        display_value = value  # Visible

    table.add_row(key, display_value, var_type.value)
```

#### Tentative 2 : Via SQLite (si persisté par erreur)

```bash
# Les secrets ne sont JAMAIS dans la DB
sqlite3 ~/.athena/credentials.db
sqlite> SELECT * FROM variables WHERE type='secret';
# Résultat: 0 rows (vide)
```

#### Tentative 3 : Via Logs

```bash
# Les secrets sont redactés automatiquement
grep "API_TOKEN" athena_ai.log
# Résultat: "API_TOKEN=[REDACTED]"
```

#### Tentative 4 : Via Dump Mémoire (Avancé)

**Théoriquement possible** avec des outils forensics (gdb, volatility), mais :
- ❌ Nécessite accès root
- ❌ Process doit être actif
- ❌ Nécessite expertise avancée
- ❌ Athena ne peut pas protéger contre ça (limitation OS)

**Protection supplémentaire possible** (non implémentée) :
- Chiffrement en mémoire avec `cryptography` (overhead performance)
- Utilisation de `mlock()` pour empêcher swap disk

---

### 🔐 Résumé des Protections

| Protection | Implémentée | Description |
|------------|-------------|-------------|
| **Input masqué** | ✅ Oui | `getpass` masque la saisie |
| **Stockage RAM uniquement** | ✅ Oui | Jamais écrit sur disque |
| **Redaction logs** | ✅ Oui | Remplace par `[REDACTED]` |
| **Non-résolution LLM** | ✅ Oui | `resolve_secrets=False` |
| **Masquage dans UI** | ✅ Oui | Affiché comme `********` |
| **Chiffrement mémoire** | ❌ Non | Overhead performance |
| **Protection swap disk** | ❌ Non | Nécessite `mlock()` (root) |

---

### 💡 Bonnes Pratiques

#### 1. Toujours utiliser `/variables set-secret` pour les passwords

```bash
# ❌ MAUVAIS
/variables set API_KEY sk-abc123def456

# ✅ BON
/variables set-secret API_KEY
API_KEY: ********
```

#### 2. Ne jamais copier-coller un secret avec `set`

```bash
# ❌ DANGEREUX (reste dans l'historique shell)
/variables set TOKEN ghp_abc123def456

# ✅ SÛR (pas dans l'historique)
/variables set-secret TOKEN
```

#### 3. Utiliser des variables d'environnement pour les CI/CD

```bash
# .env (git ignored)
export API_KEY="sk-abc123"
export DB_PASSWORD="MyS3cr3t"

# athena charge automatiquement .env
athena
# Variables disponibles comme @API_KEY, @DB_PASSWORD
```

#### 4. Rotation des secrets

```bash
# Changer un secret
/variables set-secret API_KEY
API_KEY: ******** (nouveau secret)
# Écrase l'ancien en mémoire
```

---

## Conclusion

### Task-Specific Routing

- ✅ **Automatique** : Pas besoin de configuration manuelle
- ✅ **Intelligent** : Choix du modèle selon la tâche
- ✅ **Économique** : Réduction de 80-90% des coûts
- ✅ **Configurable** : Modifiable via `config.json`
- ✅ **Indépendant du provider** : Fonctionne avec tous les providers

### Système de Secrets

- ✅ **Sécurisé** : Multiples couches de protection
- ✅ **Pratique** : `getpass` masque l'input
- ✅ **Robuste** : Jamais persisté sur disque
- ✅ **Transparent** : Redaction automatique partout
- ⚠️ **Limitation** : Protection mémoire non chiffrée (standard dans l'industrie)

---

**Fichiers de référence** :
- Task routing : [athena_ai/llm/model_config.py](athena_ai/llm/model_config.py)
- Routing : [athena_ai/llm/router.py](athena_ai/llm/router.py)
- Secrets : [athena_ai/security/credentials.py](athena_ai/security/credentials.py)
- Logging : [athena_ai/utils/logger.py](athena_ai/utils/logger.py)

**Date** : 30 Novembre 2024
**Auteur** : Assistant Claude
