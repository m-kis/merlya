# Changelog - Athena

## 2025-11-24 - Conversational References & Corrections

### 🔥 Bugs Fixés (11 Corrections Majeures)

#### Correction 10 : Investigation Intelligente des Concepts ⭐ **NOUVELLE FONCTIONNALITÉ**

**Problème** : Query "verifie si les backups sont ok sur db-qarc-1" → execute `systemctl status backups` qui échoue
**Cause Racine** : Traitement de "backup" comme nom de service systemd littéral au lieu d'un concept à investiguer
**Fichiers** : `athena_ai/agents/smart_orchestrator.py:649-805`

**Solution - Architecture à 3 Niveaux** :

```python
# NIVEAU 1: Services Directs (mysql, nginx, postgres...)
if _is_direct_service(service_name):
    commands = ["systemctl status mysql", "ps aux | grep mysql"]

# NIVEAU 2: Concepts (backup, monitoring, logs, security...)  ⭐ NOUVEAU
elif service_name:
    # LLM génère 5-7 commandes d'investigation intelligentes
    commands = _investigate_concept(service_name, target_host, query)

# NIVEAU 3: Générique (aucun service détecté)
else:
    commands = ["uptime", "df -h"]
```

**Méthodes Ajoutées** :

1. **`_is_direct_service()` - Ligne 649** : Distingue services systemd vs concepts abstraits
2. **`_investigate_concept()` - Ligne 666** : ⭐ Génère commandes via LLM pour investiguer n'importe quel concept

**Exemple Investigation "backup"** :
Le LLM génère automatiquement 7 commandes intelligentes :

```bash
1. systemctl status *backup* --no-pager
2. ps aux | grep -i '[b]ackup'
3. find /etc -type f -exec grep -l "backup" {} \; 2>/dev/null
4. tail -50 /var/log/syslog | grep -i 'backup|save|archive'
5. crontab -l | grep -i 'backup|save|archive'
6. find / -name "*backup*" -type d -ls 2>/dev/null
7. du -sh /backup* /var/backup* /*backup* 2>/dev/null
```

**Généricité** : Fonctionne pour ANY concept (monitoring, logs, security, etc.)

**Tests** :

- ✅ "verifie si les backups sont ok sur db-qarc-1" → 7 commandes générées
- ✅ "check monitoring on webserver01" → investigation adaptée
- ✅ "analyse les logs de nginx" → commandes pertinentes

#### Correction 11 : Synthesis Parser pour Commandes Complexes

**Problème** : Synthesis affiche "Service service: unknown" et "Process process: not found" (placeholders)
**Cause Racine** : Regex parser ne gère pas les patterns complexes :

- `systemctl status *backup*` (wildcards)
- `ps aux | grep -i '[b]ackup'` (brackets regex)

**Fichiers** : `athena_ai/agents/smart_orchestrator.py:1571-1643`

**Solution** :

- Amélioration regex pour extraire "backup" de `*backup*` et `[b]ackup`
- Si parsing échoue → skip la métrique (pas de placeholder)
- Support patterns : `[b]ackup`, `*backup*`, `grep -i backup`

**Avant** :

```text
⚠️ Service service: unknown ❌ Process process: not found
```

**Après** :

```text
⚠️ Service backup: unknown ❌ Process backup: not found
```

#### Correction 1 : Interface LLM Incompatible
**Problème** : `'LiteLLMRouter' object has no attribute 'generate'`
**Fichier** : `athena_ai/agents/autogen_orchestrator.py:127-136`
**Solution** : Créé instance dédiée `LLMRouter()` avec méthode `generate()` pour SmartOrchestrator

#### Correction 2 : Extraction d'Entités Incorrecte
**Problème** : Query "y a t il un backup sur ce serveur ?" → extrait "backup" comme hostname
**Fichier** : `athena_ai/agents/smart_orchestrator.py:843-990`
**Solution** :
- Ajout validation contre inventaire
- Amélioration patterns conversationnels
- Return `__CLARIFICATION_NEEDED__` si ambigu

#### Correction 3 : Ajout Prompts de Clarification
**Problème** : Aucune demande de clarification à l'utilisateur
**Fichier** : `athena_ai/agents/smart_orchestrator.py:1034-1103`
**Solution** : Nouvelle méthode `_request_clarification()` avec :
- Affichage dernier serveur en mémoire
- Liste serveurs disponibles (10 premiers)
- Suggestions d'actions

#### Correction 4 : Circuit Breaker SSH
**Problème** : 6 tentatives échouées répétées sur host inexistant
**Fichier** : `athena_ai/executors/ssh_connection_pool.py:13-118`
**Solution** : Implémentation circuit breaker :
- Seuil : 3 échecs → timeout 5 min
- Blocage permanent pour erreurs DNS
- Auto-reset après connexion réussie

#### Correction 5 : Synthèse d'Erreurs Améliorée
**Problème** : Réponse vide après échec
**Fichier** : `athena_ai/agents/smart_orchestrator.py:1105-1233`
**Solution** : Nouvelle méthode `_synthesize_failure()` avec diagnostic :
- Pattern matching pour erreurs courantes
- Suggestions basées sur type d'erreur
- Affichage hosts disponibles

#### Correction 6 : Gestion `__CLARIFICATION_NEEDED__` dans Workflow
**Problème** : Marker utilisé comme hostname réel → SSH vers "__CLARIFICATION_NEEDED__"
**Fichier** : `athena_ai/agents/smart_orchestrator.py:594-606, 636-648, 449-460`
**Solution** : Ajout checks dans :
- `_action_gather_info()`
- `_action_analyze()`
- `_execute_with_cot()` pour détecter erreur "CLARIFICATION_NEEDED"

#### Correction 7 : Signature LLMRouter.generate()
**Problème** : `got an unexpected keyword argument 'temperature'`
**Fichier** : `athena_ai/agents/smart_orchestrator.py:853-857`
**Solution** : Utilisation correcte des paramètres :
- `prompt` et `system_prompt` au lieu de `temperature`/`max_tokens`
- Paramètre `task="extraction"` pour modèle rapide

#### Correction 8 : ~~Détection Conversationnelle Trop Aggressive~~ ❌ **REMPLACÉE par Correction 9**
**Problème** : Query "analyse le serveur unifyqarcdb" détectée comme référence conversationnelle
**Tentative de solution** : Check si hostname suit le pattern et est dans inventaire
**Nouveau problème introduit** : Rejette les hostnames non listés dans inventaire
**Status** : ❌ Remplacée par Correction 9

#### Correction 9 : Architecture LLM-First + Fallback Flexible ⭐ **SOLUTION FINALE**
**Problème 1** : Query "a quoi sert le serveur unifyqarcdb ?" → demande clarification
**Problème 2** : Hostnames valides rejetés s'ils ne sont pas dans l'inventaire

**Cause Racine** :
- Ordre de détection inversé (pattern conversationnel checké avant LLM)
- Fallback regex rejetait hostnames non listés
- Validation inventaire trop stricte

**Fichiers** : `athena_ai/agents/smart_orchestrator.py:924-1046`

**Solution - Réarchitecture Complète** :
```python
# STRATEGY 1: LLM FIRST (ligne 924-937)
entities = self._extract_entities_with_llm(query)
if entities.get("target_host"):
    extracted = entities["target_host"]
    # Accepte MÊME SI pas dans inventaire
    return extracted

# STRATEGY 2: Conversational reference (ligne 939-973)
# Seulement si LLM n'a rien trouvé
# Patterns plus stricts : "ce serveur" (pas "le serveur")
conversational_patterns = [
    r'\b(ce|cette)\s+(serveur|machine|host)\b',  # Plus strict !
    r'\b(this|that)\s+(server|machine|host)\b',
]

# STRATEGY 3: Fallback regex (ligne 975-1042)
if potential_hosts:
    extracted = potential_hosts[0]
    # Utilise même si pas dans inventaire !
    return extracted
```

**Changements Clés** :
1. ✅ **LLM toujours appelé en premier** - Intelligence maximale
2. ✅ **Hostnames extraits acceptés même si non listés** - Flexibilité
3. ✅ **Patterns conversationnels plus stricts** - "ce/cette" uniquement
4. ✅ **Fallback regex flexible** - Utilise hostnames trouvés

**Tests unitaires** : 4/4 passent ✅
- ✅ "a quoi sert le serveur unifyqarcdb ?" → extrait "unifyqarcdb" (dans inventaire)
- ✅ "a quoi sert le serveur newhost ?" → extrait "newhost" (PAS dans inventaire)
- ✅ "analyse ce serveur" (avec mémoire) → utilise mémoire
- ✅ "analyse ce serveur" (sans mémoire) → demande clarification

### 🎯 Scénarios Maintenant Supportés

#### Scénario 1 : Hostname Explicite
```bash
$ athena ask "analyse le serveur unifyqarcdb et dis ce qu'il fait"
→ ✅ Extrait "unifyqarcdb" directement (même avec "le serveur")
→ Exécute analyse sans demander clarification
```

#### Scénario 2 : Référence Conversationnelle avec Contexte
```bash
$ athena ask "analyse le serveur webserver01"
[... analyse ...]

$ athena ask "y a t il des backups sur ce serveur ?"
→ ✅ Utilise mémoire : "ce serveur" = webserver01
→ Exécute commandes SSH sur webserver01
```

#### Scénario 3 : Référence Conversationnelle sans Contexte
```bash
$ athena ask "y a t il un backup sur ce serveur ?"
→ ❓ Prompt de clarification :
   - Aucun serveur cible identifié
   - Liste des serveurs disponibles
   - Suggestions : préciser le nom, utiliser "list", etc.
```

#### Scénario 4 : Host Inexistant avec Circuit Breaker
```bash
$ athena ask "analyse le serveur invalid_host"
→ ❌ Tentative 1 : Connection failed
→ ❌ Tentative 2 : Connection failed
→ ❌ Tentative 3 : Connection failed
→ 🚫 Circuit breaker OPEN (retry in 300s)
→ Synthèse d'erreur intelligente avec suggestions
```

## 2025-11-23 - Architecture Simplification & Intelligence

### 🔥 Bugs Fixés

- **orchestrator.py** : Nettoyé code dupliqué (2 classes Orchestrator)
- **orchestrator.py** : Fixé imports manquants (os, json)
- Architecture simplifiée : suppression de l'AgentCoordinator complexe

### ✨ Améliorations Majeures

#### 1. Architecture Directe (Orchestrator → AI → Exécution)
- Suppression de la couche AgentCoordinator
- L'Orchestrator appelle directement l'AI avec le contexte complet
- Approche "Mixture of Experts" implicite : l'AI décide elle-même

#### 2. Prompts Intelligents
L'AI comprend maintenant quand lire le contexte vs quand exécuter SSH :

**Avant** :
```bash
$ athena ask "list mongo preprod IPs"
→ Génère 7 commandes echo inutiles
→ Résultat verbeux et complexe
```

**Après** :
```bash
$ athena ask "list mongo preprod IPs"
→ Lit directement le contexte
→ Réponse claire avec MongoDB 4.4 vs 8.0 clusters
→ 0 commandes exécutées
```

#### 3. SSH avec Credentials du User
- **SSHManager amélioré** :
  - Support `ssh-agent` (allow_agent=True)
  - Support `~/.ssh/config` pour user/key par host
  - Détection automatique des clés SSH (id_ed25519, id_rsa, etc.)
  - Fallback intelligent

- **CredentialManager** :
  - Parse `~/.ssh/config` pour user custom par host
  - Détecte ssh-agent (SSH_AUTH_SOCK)
  - Order of preference : ed25519 > ecdsa > rsa

#### 4. Discovery SSH Automatique
- `athena init` scanne maintenant les hosts distants via SSH
- Pour chaque host dans inventory :
  - Teste connectivité SSH
  - Récupère OS, kernel, hostname
  - Liste services systemd actifs
  - Stocke dans context["remote_hosts"]

- L'AI voit maintenant :
  ```
  REMOTE HOSTS (detailed info from SSH scan):
  mongo-preprod-1 (203.0.113.10):
    - OS: Linux
    - Kernel: 5.15.0-89-generic
    - Running services: mongod.service, nginx.service, ...
  ```

### 🎯 Règles du Prompt Système

```
IMPORTANT RULES:
- NEVER use 'echo' commands to display inventory data
- For queries about hosts/IPs in the inventory, READ the context data directly
- Only generate shell commands when you need to check LIVE system state
- If information is already in context, just answer directly
- Be smart: "list mongo IPs" = read context, "check mongo status" = SSH needed
```

### 📊 Comparaison Avant/Après

#### Exemple 1: Liste des IPs
**Avant** :
- 7 commandes echo générées
- Temps : ~15 secondes
- Résultat : JSON complexe avec erreurs "requires confirmation"

**Après** :
- 0 commandes
- Temps : ~2 secondes
- Résultat : Réponse claire et structurée

#### Exemple 2: Check Service
**Avant** : (non testé mais probablement complexe)

**Après** :
```bash
$ athena ask "check if mongodb is running on mongo-preprod-1" --dry-run

Actions planned:
1. [mongo-preprod-1] systemctl status mongod || systemctl status mongodb || ps aux | grep mongod
   Reason: Check MongoDB service status with intelligent fallback
```

### 🛠️ Fichiers Modifiés

1. **athena_ai/orchestrator.py** - Réécriture complète (200 lignes, clean)
2. **athena_ai/executors/ssh.py** - SSH avec ssh-agent et config
3. **athena_ai/security/credentials.py** - Parse SSH config
4. **athena_ai/context/discovery.py** - Scan SSH des hosts distants
5. **athena_ai/context/manager.py** - Intégration scan remote

### 🚀 Prochaines Étapes

- [ ] Tester sur vraie infra (SSH réel)
- [ ] Améliorer gestion des erreurs SSH
- [ ] Ajouter cache pour éviter rescans fréquents
- [ ] Support Ansible/Terraform (ProvisioningAgent)
- [ ] Memory persistante pour actions critiques
