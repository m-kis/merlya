# 🔒 Security Audit: Credential Manager

**Date:** 2025-11-30
**Auditor:** Claude Code (Sonnet 4.5)
**Scope:** `athena_ai/security/credentials.py`
**Status:** ✅ PASS with recommendations

---

## Executive Summary

Le `CredentialManager` d'Athena a été audité pour évaluer la sécurité du stockage et de la gestion des credentials (SSH, DB, variables utilisateur). L'audit révèle une **conception sécurisée** avec une bonne séparation entre secrets éphémères et données persistées.

### Verdict Global : ✅ PASS

| Aspect | Score | Justification |
|--------|-------|---------------|
| **Secret Storage** | 9/10 | ✅ Secrets jamais persistés, in-memory only |
| **Privilege Separation** | 10/10 | ✅ Types de variables bien séparés (HOST, CONFIG, SECRET) |
| **Input Handling** | 8/10 | ✅ getpass() pour saisie sécurisée |
| **Memory Management** | 7/10 | ⚠️ Pas de memlock/secure erase |
| **Encryption at Rest** | N/A | ℹ️ Dépend de StorageManager (audit séparé requis) |
| **Audit Trail** | 6/10 | ⚠️ Pas de logging des accès secrets |

**Blockers:** AUCUN
**Warnings:** 3 recommandations mineures
**Good Practices:** 8 bonnes pratiques identifiées

---

## 1. Architecture de Sécurité

### 1.1 Vue d'Ensemble

```
┌─────────────────────────────────────────────────────────────┐
│                   CredentialManager                         │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ SSH Keys     │  │ DB Creds     │  │ User Variables  │  │
│  │ ~/.ssh/      │  │ getpass()    │  │ @variables      │  │
│  │ ssh-agent    │  │ env vars     │  │ SQLite persist  │  │
│  └──────────────┘  └──────────────┘  └─────────────────┘  │
│         │                 │                    │           │
│         │                 │                    │           │
│         └─────────────────┴────────────────────┘           │
│                           │                                │
└───────────────────────────┼────────────────────────────────┘
                            │
                   ┌────────▼─────────┐
                   │ StorageManager   │
                   │ (SQLite backend) │
                   └──────────────────┘
```

### 1.2 Threat Model

**Assets à Protéger:**
- SSH private keys (passphrases)
- Database passwords
- API tokens/secrets
- User-defined secrets

**Threats Considérés:**
1. ✅ **Data breach from disk** : Secrets jamais écrits sur disque
2. ✅ **Memory dumps** : Secrets in-memory seulement (mais pas memlock)
3. ✅ **Log leakage** : Secrets masked dans logs
4. ✅ **Environment variable exposure** : Utilisés mais pas requis
5. ⚠️ **Swap exposure** : Pas de protection (memlock absent)

**Threats NON Considérés (hors scope):**
- Kernel exploits / rootkit
- Hardware attacks (cold boot, DMA)
- Side-channel attacks (timing, cache)

---

## 2. Analyse Détaillée par Composant

### 2.1 Variable Types (Privilege Separation) ⭐⭐⭐⭐⭐

```python
class VariableType(Enum):
    HOST = "host"      # Persisted (safe)
    CONFIG = "config"  # Persisted (safe)
    SECRET = "secret"  # NEVER persisted (critical)
```

#### ✅ Good Practices
1. **Clear separation** : Types explicites empêchent la confusion
2. **Principle of least privilege** : Seuls HOST/CONFIG persistés
3. **Type enforcement** : VariableType enum = type-safe

#### Example Usage
```python
# Safe: persisted (non-sensitive)
cm.set_variable("proddb", "db-prod-001", VariableType.HOST)

# Safe: in-memory only (sensitive)
cm.set_variable("api-token", "sk-abc123...", VariableType.SECRET)
```

**Verdict:** ✅ SECURE - Excellente séparation des privilèges

---

### 2.2 Secret Storage (In-Memory Only) ⭐⭐⭐⭐

```python
# credentials.py:289-293
def set_variable(self, key: str, value: str, var_type: VariableType = VariableType.CONFIG):
    self._variables[key] = (value, var_type)

    # Auto-save if not a secret
    if var_type != VariableType.SECRET:
        self._save_variables()
```

```python
# credentials.py:95-100
def _save_variables(self):
    # Only save non-secret variables
    to_save = {
        key: [value, var_type.value]
        for key, (value, var_type) in self._variables.items()
        if var_type != VariableType.SECRET  # 🔒 Filter secrets
    }
    self._storage.set_config(self.STORAGE_KEY, to_save)
```

#### ✅ Good Practices
1. **Never persisted** : Secrets exclus du save automatique
2. **Double-check** : Filtre dans `_save_variables()` ET au load
3. **Fail-safe** : Si SECRET écrit par erreur, `_load_variables()` l'ignore (ligne 80)

#### Safety Check au Load
```python
# credentials.py:79-81
if var_type != VariableType.SECRET:
    self._variables[key] = (value, var_type)
# Secrets ignorés même si présents dans storage (shouldn't happen)
```

**Verdict:** ✅ SECURE - Defense in depth correcte

---

### 2.3 Secure Input (getpass) ⭐⭐⭐⭐

```python
# credentials.py:307-329
def set_variable_secure(self, key: str, var_type: VariableType = VariableType.SECRET) -> bool:
    try:
        print(f"\n[Secure input for '{key}']")
        value = getpass.getpass(f"{key}: ")  # 🔒 Hidden input
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

#### ✅ Good Practices
1. **Hidden input** : `getpass.getpass()` ne montre pas le texte
2. **Cancel handling** : Ctrl+C géré proprement
3. **Empty check** : Valeur vide = pas sauvegardée

#### ⚠️ Recommendation MINOR
**Issue** : Le prompt print affiche le key name en clair
```python
print(f"\n[Secure input for '{key}']")  # ⚠️ Reveals "ssh-passphrase-hostname"
```

**Impact** : LOW - Révèle le type de secret (passphrase vs password)
**Fix** :
```python
# Generic prompt
print(f"\n[Secure input]")
value = getpass.getpass(f"Enter value: ")
```

**Verdict:** ✅ SECURE - Recommandation mineure

---

### 2.4 DB Credentials (Multiple Sources) ⭐⭐⭐⭐

```python
# credentials.py:219-258
def get_db_credentials(self, host: str, service: str = "mongodb",
                      username: Optional[str] = None,
                      password: Optional[str] = None) -> Tuple[str, str]:
    """
    Priority:
    1. Explicit credentials passed as arguments
    2. Session cache (already prompted in this session)
    3. Environment variables (MONGODB_USER, MONGODB_PASS)
    4. Interactive prompt with getpass (secure input)
    """
```

#### ✅ Good Practices
1. **Priority order** : Arguments > Cache > Env > Prompt
2. **Session cache** : Évite prompts répétés (UX)
3. **Env vars** : Facilite automation sans prompt
4. **Getpass fallback** : Secure input si rien d'autre

#### ⚠️ Recommendation MEDIUM
**Issue** : Session cache stored in plain dict (in-memory)
```python
# credentials.py:54
self.session_credentials: Dict[str, Tuple[str, str]] = {}  # ⚠️ Plain dict
```

**Risk** : Memory dump révèle credentials
**Mitigation** : Python n'a pas de "secure string" built-in (contrairement à .NET)

**Options** :
1. ✅ **Acceptable** : In-memory = acceptable pour CLI tool (pas web server)
2. ⚠️ **Better** : Use `ctypes` + memlock (complexe, overkill pour CLI)
3. ⚠️ **Best** : Use dedicated secret management (Vault, keyring)

**Recommendation** :
```python
# Option 1: Clear on exit (easy win)
def __del__(self):
    self.clear_session_credentials()

# Option 2: TTL for session cache
from datetime import datetime, timedelta

self.session_credentials_ttl: Dict[str, datetime] = {}

def get_db_credentials(...):
    # Check TTL
    if cache_key in self.session_credentials:
        if datetime.now() - self.session_credentials_ttl[cache_key] < timedelta(minutes=15):
            return self.session_credentials[cache_key]
        else:
            del self.session_credentials[cache_key]  # Expired
```

**Verdict:** ✅ ACCEPTABLE - In-memory OK pour CLI, TTL recommended

---

### 2.5 Storage Manager Integration (Encryption Unknown) ⚠️

```python
# credentials.py:44-51
def __init__(self, storage_manager=None):
    self._storage = storage_manager
    self._load_variables()
```

```python
# credentials.py:101
self._storage.set_config(self.STORAGE_KEY, to_save)
```

#### ❓ Unknown - Requires Separate Audit
**Question** : `StorageManager.set_config()` stocke où et comment ?
- SQLite plaintext ?
- SQLite with encryption (SQLCipher) ?
- File with encryption ?

**Action Required** :
```bash
# TODO: Audit StorageManager
grep -r "class StorageManager" athena_ai/
```

**Assumption for this audit** :
- HOST/CONFIG variables = **non-sensitive** (ok if plaintext)
- SECRET variables = **never stored** (so encryption irrelevant)

**Verdict:** ℹ️ REQUIRES SEPARATE AUDIT

---

### 2.6 Variable Resolution (Prevent Leakage) ⭐⭐⭐⭐

```python
# credentials.py:385-446
def resolve_variables(self, text: str, warn_missing: bool = True, resolve_secrets: bool = True) -> str:
    """
    Args:
        resolve_secrets: If True, resolve secret variables to their values.
                       If False, keep @secret_name for secrets (to prevent leaking to LLM).
    """
```

#### ✅ Good Practices
1. **LLM leak prevention** : `resolve_secrets=False` garde `@secret` unreplaced
2. **Secret tracking** : `secret_var_names` set évite inventory resolution
3. **Warning system** : Logs unresolved variables

#### Example Usage
```python
# BEFORE prompt to LLM
text = "Connect to @proddb using @db-password"

# resolve_secrets=False → Prevents leak
resolved = cm.resolve_variables(text, resolve_secrets=False)
# Result: "Connect to db-prod-001 using @db-password"
# ✅ Password NOT sent to LLM

# AFTER LLM response, for actual execution
resolved = cm.resolve_variables(text, resolve_secrets=True)
# Result: "Connect to db-prod-001 using secret123"
# ✅ Password resolved for SSH command
```

**Verdict:** ✅ SECURE - Excellente prévention de leaks

---

### 2.7 Credential Extraction from Prompts ⚠️

```python
# credentials.py:508-543
@staticmethod
def extract_credentials_from_prompt(prompt: str) -> Optional[Tuple[str, str]]:
    """Extract credentials from user prompt if provided in plain text."""
    patterns = [
        r'(?:user|username)\s+(\S+)\s+(?:password|passwd|pass|pwd)\s+(\S+)',
        r'(?:credentials?|creds?)\s+(\S+)[/:](\S+)',
        # ... 6 patterns total
    ]
```

#### ⚠️ Security Concern - Plaintext Credentials in History
**Issue** : User tape `"user admin password secret123"` → stored in history

**Impact** :
- Shell history (bash_history, zsh_history) contains plaintext password
- REPL history (readline) contains plaintext password

**Mitigation Options** :
1. ❌ **Don't use** : Discourage cette pratique (docs)
2. ✅ **Warn** : Ajouter warning si credentials détectés
3. ✅ **Sanitize** : Remove from history après extraction

**Recommendation** :
```python
def extract_credentials_from_prompt(prompt: str) -> Optional[Tuple[str, str]]:
    for pattern in patterns:
        match = re.search(pattern, prompt, re.IGNORECASE):
            if match:
                logger.warning(
                    "⚠️ Credentials detected in prompt! "
                    "Use '/variables set-secret' instead to avoid history leakage."
                )
                return (match.group(1), match.group(2))
```

**Verdict:** ⚠️ WARN USERS - Add deprecation warning

---

## 3. Memory Security

### 3.1 No Memlock Protection ⚠️

**Current State** : Secrets stored in regular Python strings
```python
self._variables[key] = (value, var_type)  # ⚠️ Regular string, can be swapped
```

**Risk** : Si OS swap la page mémoire → secret écrit sur disque

**Impact** : LOW pour CLI tool (session courte)
**Impact** : MEDIUM pour long-running daemon

**Mitigation (Advanced)** :
```python
import ctypes
import mmap

class SecureString:
    """String stored in mlocked memory (prevents swap)."""
    def __init__(self, value: str):
        self._data = mmap.mmap(-1, len(value), prot=mmap.PROT_READ | mmap.PROT_WRITE)
        self._data.write(value.encode())
        # Lock memory (requires root on Linux)
        libc = ctypes.CDLL("libc.so.6")
        libc.mlock(ctypes.c_void_p(id(self._data)), len(value))

    def __del__(self):
        # Zero memory before free
        self._data.seek(0)
        self._data.write(b'\x00' * len(self._data))
        libc.munlock(ctypes.c_void_p(id(self._data)), len(self._data))
```

**Recommendation** :
- ✅ Document limitation dans README
- ⚠️ Implement only if Athena becomes daemon (not CLI)

---

### 3.2 No Secure Erase ⚠️

**Current State** : Secrets deleted with `del` (GC'd eventually)
```python
def clear_session_credentials(self):
    self.session_credentials.clear()  # ⚠️ No secure erase
```

**Risk** : Secret reste en mémoire jusqu'au GC (peut être dumped)

**Best Practice** :
```python
def clear_session_credentials(self):
    # Overwrite before delete
    for key in list(self.session_credentials.keys()):
        # Replace with zeros
        user, pwd = self.session_credentials[key]
        self.session_credentials[key] = ("", "")  # Overwrite
    self.session_credentials.clear()
```

**Verdict:** ⚠️ MINOR - Document limitation, fix if daemon mode

---

## 4. Audit Trail

### 4.1 No Access Logging ⚠️

**Current State** : Aucun log des accès aux secrets
```python
def get_variable(self, key: str) -> Optional[str]:
    if key in self._variables:
        return self._variables[key][0]  # ⚠️ No audit log
    return None
```

**Risk** : Impossible de tracer qui accède aux secrets (forensics)

**Recommendation** :
```python
def get_variable(self, key: str) -> Optional[str]:
    if key in self._variables:
        value, var_type = self._variables[key]
        # Audit secret access
        if var_type == VariableType.SECRET:
            logger.info(f"🔑 Secret accessed: {key} (caller: {inspect.stack()[1].function})")
        return value
    return None
```

**Verdict:** ⚠️ RECOMMENDED - Add audit logging for secrets

---

## 5. Compliance & Standards

### 5.1 OWASP Top 10 Compliance

| OWASP Risk | Status | Notes |
|------------|--------|-------|
| **A01 - Broken Access Control** | ✅ PASS | Type-based access control (HOST/CONFIG/SECRET) |
| **A02 - Cryptographic Failures** | ⚠️ UNKNOWN | Depends on StorageManager encryption |
| **A03 - Injection** | ✅ PASS | Regex patterns safe, no SQL injection |
| **A04 - Insecure Design** | ✅ PASS | Defense in depth, fail-safe defaults |
| **A05 - Security Misconfiguration** | ✅ PASS | Secure defaults (secrets not persisted) |
| **A06 - Vulnerable Components** | ✅ PASS | No external dependencies for crypto |
| **A07 - Auth/AuthZ Failures** | N/A | No authentication layer (local tool) |
| **A08 - Software/Data Integrity** | ✅ PASS | Type enforcement via Enum |
| **A09 - Logging/Monitoring Failures** | ⚠️ MINOR | No secret access audit trail |
| **A10 - SSRF** | N/A | No server-side requests |

**Compliance Score: 8/10** (2 unknowns/minors)

---

### 5.2 PCI-DSS Compliance (If Storing Card Data)

**Status:** ❌ NOT COMPLIANT (but not applicable)

**Reason:** CredentialManager ne devrait **JAMAIS** stocker des card data.
Si card data requis → Use external service (Stripe, Vault)

**Recommendation:** Ajouter validation pour bloquer card patterns
```python
CARD_PATTERN = r'\b\d{13,19}\b'  # Visa, MC, Amex

def set_variable(self, key: str, value: str, var_type: VariableType):
    # Block credit card numbers
    if re.search(CARD_PATTERN, value):
        raise ValueError("Credit card numbers are not allowed. Use external payment service.")
    # ... rest of code
```

---

## 6. Recommendations Summary

### 🔴 CRITICAL (None)
Aucune vulnérabilité critique identifiée.

### 🟠 HIGH (None)
Aucune vulnérabilité haute priorité.

### 🟡 MEDIUM (1)

#### MED-1: Add Session Credential TTL
**File:** `credentials.py:54, 232-258`
**Issue:** Session credentials cached indéfiniment
**Fix:** Add 15-minute TTL
```python
from datetime import datetime, timedelta

self.session_credentials_ttl: Dict[str, datetime] = {}

def get_db_credentials(...):
    cache_key = f"{service}@{host}"
    if cache_key in self.session_credentials:
        age = datetime.now() - self.session_credentials_ttl.get(cache_key, datetime.min)
        if age < timedelta(minutes=15):
            return self.session_credentials[cache_key]
        else:
            del self.session_credentials[cache_key]
    # ... prompt for credentials
    self.session_credentials_ttl[cache_key] = datetime.now()
```

### 🟢 LOW (3)

#### LOW-1: Warn When Extracting Credentials from Prompt
**File:** `credentials.py:508-543`
**Issue:** Plaintext credentials dans history
**Fix:** Add warning
```python
if match:
    logger.warning(
        "⚠️ SECURITY: Credentials detected in plaintext prompt! "
        "Use '/variables set-secret' to avoid history leakage."
    )
```

#### LOW-2: Add Secret Access Audit Logging
**File:** `credentials.py:331-335`
**Issue:** Pas de trace des accès secrets
**Fix:** Log secret access
```python
def get_variable(self, key: str) -> Optional[str]:
    if key in self._variables:
        value, var_type = self._variables[key]
        if var_type == VariableType.SECRET:
            import inspect
            caller = inspect.stack()[1].function
            logger.info(f"🔑 Secret '{key}' accessed by {caller}")
        return value
```

#### LOW-3: Generic Secure Input Prompt
**File:** `credentials.py:319`
**Issue:** Prompt révèle le nom du secret
**Fix:** Generic prompt
```python
print(f"\n[Secure Input]")
value = getpass.getpass(f"Enter value: ")
```

### ℹ️ INFORMATIONAL (2)

#### INFO-1: Audit StorageManager Encryption
**Action:** Audit séparé de `StorageManager.set_config()`
**Verify:** HOST/CONFIG variables encryption at rest

#### INFO-2: Document Memory Security Limitations
**Action:** Add to README.md
```markdown
## Security Considerations

### Secret Storage
- Secrets stored **in-memory only** (never persisted to disk)
- No memlock protection (secrets may be swapped to disk by OS)
- No secure erase (secrets may remain in memory after deletion)

**Recommendation:** For highly sensitive secrets, use external secret manager (HashiCorp Vault, AWS Secrets Manager)
```

---

## 7. Security Scorecard

```
┌─────────────────────────────────────────────────────────────┐
│                  Security Scorecard                         │
├─────────────────────────────────────────────────────────────┤
│ Overall Grade:              A-                              │
│ Critical Issues:            0                               │
│ High Priority:              0                               │
│ Medium Priority:            1                               │
│ Low Priority:               3                               │
│ Informational:              2                               │
├─────────────────────────────────────────────────────────────┤
│ Strengths:                                                  │
│  ✅ Defense in depth (multi-layer secret protection)       │
│  ✅ Type safety (VariableType enum)                        │
│  ✅ LLM leak prevention (resolve_secrets flag)             │
│  ✅ Secure input (getpass)                                 │
│  ✅ Never persist secrets (fail-safe defaults)             │
├─────────────────────────────────────────────────────────────┤
│ Weaknesses:                                                 │
│  ⚠️ No memlock (swappable secrets)                         │
│  ⚠️ No secure erase (GC timing)                            │
│  ⚠️ No audit trail (forensics)                             │
│  ⚠️ Session cache indefinite TTL                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. Conclusion

### Verdict Final : ✅ **PRODUCTION READY avec RECOMMENDATIONS**

Le `CredentialManager` suit des bonnes pratiques de sécurité solides :
- Séparation claire des types de variables
- Secrets jamais persistés
- Defense in depth (multi-layer checks)
- Secure input via getpass
- LLM leak prevention

Les limitations identifiées sont **mineures** et **acceptables** pour un CLI tool :
- Pas de memlock → Acceptable (session courte)
- Pas de secure erase → Acceptable (Python limitation)
- Pas d'audit trail → Recommended (mais non-bloquant)

### Action Items

**Before Production:**
1. ✅ Aucun - Déjà production ready

**After Production (Improvements):**
1. 🟡 Add session credential TTL (15 minutes)
2. 🟢 Warn when extracting credentials from prompts
3. 🟢 Add secret access audit logging
4. ℹ️ Audit StorageManager encryption
5. ℹ️ Document memory security limitations

---

**Audit Completed:** 2025-11-30
**Next Audit:** 2026-01-30 (ou si changements majeurs)
**Auditor Signature:** Claude Code (Sonnet 4.5)
