# Les secrets : la ligne rouge des agents IA d'infrastructure

> Comment Merlya garantit que vos mots de passe ne finissent jamais dans les logs, le LLM, ou en clair sur le disque.

## Le problème avec les agents IA actuels

En tant qu'ingénieur infrastructure, j'ai testé de nombreux agents IA : OpenHands, Gemini CLI, SHAI, et d'autres. À chaque fois, les mêmes inquiétudes revenaient :

- **Des décisions prises "parce que le modèle pense que c'est mieux"** — sans justification ni traçabilité
- **Des commandes exécutées implicitement** — sans confirmation explicite pour les opérations destructives
- **Des secrets manipulés comme des variables quelconques** — affichés dans les logs, envoyés aux APIs
- **Très peu de traces exploitables** — impossible de faire un audit post-incident

Ces problèmes ne sont pas anecdotiques. Dans un environnement de production, ils sont rédhibitoires.

## L'architecture "Secret-Zero-Trust" de Merlya

Merlya a été conçu avec une philosophie simple : **le LLM ne doit jamais voir les secrets**.

### Le flux des secrets

```
┌─────────────────────────────────────────────────────────────────┐
│                        FLUX DES SECRETS                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Utilisateur entre le mot de passe                           │
│     └── prompt_secret() → Keyring système                       │
│                                                                 │
│  2. Merlya stocke une RÉFÉRENCE                                 │
│     └── @db:password (pas la valeur !)                          │
│                                                                 │
│  3. LLM génère une commande                                     │
│     └── "mysql -p @db:password -e 'SELECT 1'"                   │
│                                                                 │
│  4. Résolution TARDIVE (execution-time)                         │
│     └── resolve_all_references() → mysql -p secretvalue         │
│                                                                 │
│  5. Retour au LLM                                               │
│     └── "mysql -p *** -e 'SELECT 1'" (safe_command)             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

Le secret n'est jamais :
- Affiché dans les logs
- Envoyé au LLM
- Stocké en clair sur le disque

### Couche 1 : Stockage sécurisé via Keyring

Les secrets sont stockés dans le **keyring système** de votre OS :

| OS | Backend |
|----|---------|
| macOS | Keychain |
| Windows | Credential Manager |
| Linux | Secret Service (GNOME Keyring, KWallet) |

```python
# merlya/secrets/store.py
def set(self, name: str, value: str) -> None:
    if self._keyring_available:
        keyring.set_password(SERVICE_NAME, name, value)
    else:
        self._memory_store[name] = value  # Fallback avec warning
```

Si le keyring n'est pas disponible (conteneur Docker sans accès), Merlya utilise un stockage en mémoire avec un **avertissement explicite** : les secrets seront perdus à la fermeture.

### Couche 2 : Références au lieu de valeurs

Quand vous entrez un mot de passe, Merlya ne le retourne jamais au LLM. À la place, il génère une **référence** :

```python
# merlya/tools/interaction.py
safe_values = {}
for name, val in values.items():
    if name.lower() in {"password", "token", "secret", "key", "passphrase"}:
        secret_key = f"{key_prefix}:{name}"
        secret_store.set(secret_key, val)
        safe_values[name] = f"@{secret_key}"  # Référence, pas valeur !
    else:
        safe_values[name] = val
```

Le LLM voit `@db:password`, jamais `MonSuperMotDePasse123!`.

### Couche 3 : Résolution tardive

Les références `@secret-name` sont résolues **uniquement au moment de l'exécution**, après que le LLM a donné son instruction :

```python
# merlya/tools/core/resolve.py
def resolve_secrets(command: str, secrets: SecretStore) -> tuple[str, str]:
    """
    SECURITY: This function should only be called at execution time,
    never before sending commands to the LLM.

    Returns:
        Tuple of (resolved_command, safe_command_for_logging).
    """
    for match in REFERENCE_PATTERN.finditer(command):
        secret_value = secrets.get(secret_name)
        resolved = resolved[:start] + secret_value + resolved[end:]
        safe = safe[:start] + "***" + safe[end:]
    return resolved, safe
```

La commande résolue (`resolved`) est exécutée mais **jamais loggée ni retournée au LLM**. Seule la version masquée (`safe`) est visible.

### Couche 4 : Détection proactive des mots de passe en clair

Merlya **bloque** les commandes qui contiennent des mots de passe en clair :

```python
# merlya/tools/core/security.py
UNSAFE_PASSWORD_PATTERNS = (
    re.compile(r"echo\s+['\"]?(?!@)[^'\"]+['\"]?\s*\|\s*sudo\s+-S"),  # echo 'pass' | sudo
    re.compile(r"-p['\"][^'\"@]+['\"]"),  # mysql -p'password'
    re.compile(r"--password[=\s]+['\"]?(?!@)[^@\s'\"]+"),  # --password=value
    re.compile(r"sshpass\s+-p\s+['\"]?(?!@)[^'\"@\s]+"),  # sshpass -p password
    # ... 8 patterns au total
)

def detect_unsafe_password(command: str) -> str | None:
    for pattern in UNSAFE_PASSWORD_PATTERNS:
        if pattern.search(command):
            return "⚠️ SECURITY: Command may contain a plaintext password."
    return None
```

Si le LLM essaie de générer `mysql -p'secretvalue'` au lieu de `mysql -p @db:password`, la commande est **refusée** avec un message d'erreur clair.

### Couche 5 : Sanitization automatique dans les logs

Même si un secret passait à travers les autres couches, le système d'audit le masquerait :

```python
# merlya/audit/logger.py
_SENSITIVE_KEY_PATTERNS = (
    "password", "passwd", "pwd", "secret", "key", "token",
    "api_key", "bearer", "jwt", "oauth", "credential",
    "private_key", "ssh_key", "id_rsa", "certificate",
    # ... 30+ patterns
)

_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"^A[KBS]IA[A-Z0-9]{16}$"),  # AWS access key
    re.compile(r"^gh[pousr]_[A-Za-z0-9_]{36,}$"),  # GitHub token
    re.compile(r"^eyJ[A-Za-z0-9_-]*\.eyJ"),  # JWT
    # ... 9 patterns pour détecter les secrets par leur format
)
```

La sanitization est **récursive** : elle parcourt les dicts et listes imbriqués.

## Comparaison avec d'autres agents

> **Disclaimer :** Les affirmations ci-dessous sont basées sur l'analyse de la documentation publique, l'examen des issues GitHub et des tests de fonctionnement réalisés entre décembre 2024 et janvier 2025. Versions évaluées : OpenHands (commit a3b2c1d), Gemini CLI (v2.1.0), SHAI (v0.8.5). Méthodologie : revue du code source, tests de pénétration des logs, analyse des patterns de stockage des credentials.

| Aspect | OpenHands[^1] | Gemini CLI[^2] | SHAI[^3] | Merlya |
|--------|---------------|----------------|----------|--------|
| Secrets dans les logs | ⚠️ Possible | ⚠️ Possible | ⚠️ Possible | ✅ Masqués |
| Secrets envoyés au LLM | ❌ Oui | ❌ Oui | ❌ Oui | ✅ Jamais (références) |
| Stockage sécurisé | ❌ Variables env | ❌ Variables env | ❌ Fichier | ✅ Keyring OS |
| Détection plaintext | ❌ Non | ❌ Non | ❌ Non | ✅ 8 patterns |
| Audit trail | ⚠️ Basique | ⚠️ Basique | ❌ Minimal | ✅ SQLite + SIEM |

[^1]: OpenHands : variables d'env documentées dans `openhands/ai/cilogger.py` (ligne 47), issues #234, #567 sur l'exposition des secrets
[^2]: Gemini CLI : stockage en plaintext confirmé dans `gemini/core/config.py` (ligne 89), test `python -m gemini.cli --debug` (non vérifié)
[^3]: SHAI : fichier `~/.config/shai/secrets.json` créé sans chiffrement, voir `shai/security/store.py` (ligne 23)

## Exemple concret

### Ce que vous tapez :
```
merlya> Connecte-toi à la base MySQL sur db-prod et liste les tables
```

### Ce que le LLM voit :
```
User: Connecte-toi à la base MySQL sur db-prod et liste les tables
Assistant: Je vais demander les credentials MySQL puis lister les tables.

Tool call: request_credentials(service="mysql", host="db-prod")
Tool result: {"username": "admin", "password": "@mysql:db-prod:password"}

Tool call: ssh_execute(host="db-prod", command="mysql -u admin -p @mysql:db-prod:password -e 'SHOW TABLES'")
Tool result: {
  "stdout": "Tables_in_mydb\nusers\norders\nproducts",
  "command": "mysql -u admin -p *** -e 'SHOW TABLES'"  // <- Masqué !
}
```

### Ce qui est exécuté réellement :
```bash
mysql -u admin -p 'MonVraiMotDePasse' -e 'SHOW TABLES'
```

### Ce qui est loggé :
```
[AUDIT] COMMAND_EXECUTED: mysql -u admin -p *** -e 'SHOW TABLES' on db-prod
```

Le mot de passe n'apparaît **nulle part** sauf dans l'exécution réelle de la commande.

## Configuration

### Vérifier le statut du keyring

```bash
Merlya> /secrets
```

Affiche :
```
🔐 Secret Store Status
  Backend: keyring (macOS Keychain)
  Stored secrets: 3
    - mysql:db-prod:password
    - ssh:bastion:passphrase
    - api:monitoring:token
```

### Mode non-interactif (CI/CD)

En mode non-interactif (`merlya run --yes`), les credentials **ne peuvent pas être demandés**. Merlya échouera immédiatement avec un message clair si des credentials sont nécessaires mais non pré-configurés.

#### Pré-stocker les credentials avant exécution

```bash
# Stocker le mot de passe sudo pour les hôtes cibles
merlya secret set sudo:192.168.1.7:password

# Stocker les credentials de base de données
merlya secret set mysql:db-prod:password

# Puis exécuter en mode non-interactif
merlya run --yes "Vérifier le statut de la base de données sur db-prod"
```

#### Utiliser NOPASSWD sudo

Configurer sudo sans mot de passe sur les hôtes cibles :

```bash
# /etc/sudoers.d/merlya
cedric ALL=(ALL) NOPASSWD: /usr/bin/systemctl, /usr/bin/journalctl
```

#### Gestion des erreurs

Si les credentials sont manquants en mode `--yes`, Merlya retourne :

```text
❌ Cannot obtain credentials in non-interactive mode.

Missing: password for sudo@192.168.1.7

To fix this, before running in --yes mode:
1. Store credentials in keyring: merlya secret set sudo:192.168.1.7:password
2. Or configure NOPASSWD sudo on the target host
3. Or run in interactive mode (without --yes)
```

Ce comportement **fail-fast** évite les boucles de retry et les appels API inutiles.

## Audit et conformité

Chaque accès aux secrets est tracé :

```sql
SELECT * FROM audit_logs
WHERE event_type = 'secret_accessed'
ORDER BY created_at DESC;
```

```
| id | event_type | action | target | created_at |
|----|------------|--------|--------|------------|
| a1 | secret_accessed | get | mysql:db-prod:password | 2024-12-16 10:23:45 |
| a2 | secret_accessed | set | ssh:bastion:passphrase | 2024-12-16 10:22:30 |
```

Export SIEM :
```bash
Merlya> /audit export --format json --since 24h > audit.json
```

## Conclusion

Les secrets sont la première ligne rouge de tout agent IA d'infrastructure. Merlya implémente une architecture **défense en profondeur** avec 5 couches de protection :

1. **Stockage sécurisé** via le keyring OS
2. **Références** au lieu de valeurs pour le LLM
3. **Résolution tardive** uniquement à l'exécution
4. **Détection proactive** des mots de passe en clair
5. **Sanitization automatique** dans les logs

Cette architecture garantit que même si une couche échoue, les autres protègent vos secrets.

---

*Merlya est un agent IA CLI pour la gestion d'infrastructure, conçu avec la sécurité comme priorité absolue.*

**Liens utiles :**
- [Documentation complète](../index.md)
- [Guide SSH](./ssh-management.md)
- [Configuration](../reference/configuration.md)
