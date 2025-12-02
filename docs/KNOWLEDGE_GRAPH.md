# Knowledge Graph (FalkorDB)

Merlya utilise FalkorDB comme base de données graph pour la **mémoire à long terme** des incidents, patterns et connaissances opérationnelles.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        OpsKnowledgeManager                       │
│  (Facade unifiée pour toute la gestion des connaissances)       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────┐          │
│  │IncidentMemory│  │PatternLearner │  │  CVEMonitor  │          │
│  │              │  │               │  │              │          │
│  │- Enregistre  │  │- Apprend des  │  │- Surveille   │          │
│  │  incidents   │  │  résolutions  │  │  vulnérabilit│          │
│  │- Trouve      │  │- Matche les   │  │  és          │          │
│  │  similaires  │  │  patterns     │  │              │          │
│  └──────┬───────┘  └───────┬───────┘  └──────────────┘          │
│         │                  │                                     │
│         └────────┬─────────┘                                     │
│                  ▼                                               │
│         ┌────────────────────┐                                   │
│         │   StorageManager   │                                   │
│         │ (Hybrid Storage)   │                                   │
│         └────────┬───────────┘                                   │
│                  │                                               │
│     ┌────────────┴────────────┐                                  │
│     ▼                         ▼                                  │
│ ┌─────────┐           ┌─────────────┐                            │
│ │ SQLite  │◄─────────►│  FalkorDB   │                            │
│ │ (local) │   sync    │ (graph DB)  │                            │
│ └─────────┘           └─────────────┘                            │
│                                                                  │
│ Toujours disponible    Optionnel, enrichit                       │
│ Fallback automatique   les requêtes graph                        │
└─────────────────────────────────────────────────────────────────┘
```

## Rôle de FalkorDB

### Ce que FalkorDB apporte

| Fonctionnalité | Sans FalkorDB (SQLite) | Avec FalkorDB |
|---------------|------------------------|---------------|
| Stockage incidents | Basique | Graphe relationnel |
| Recherche similaire | Keyword matching | Traversée de graphe |
| Corrélation patterns | Limitée | Relations multi-niveaux |
| Visualisation | Non | Possible (RedisInsight) |
| Performance sur relations | O(n) | O(1) via index |

### Cas d'usage principaux

1. **Mémoire des incidents**
   - Stocke chaque incident avec ses symptômes, cause racine, solution
   - Relie incidents similaires via `SIMILAR_TO`
   - Permet de retrouver les résolutions passées

2. **Apprentissage de patterns**
   - Extrait des patterns des incidents résolus
   - Matche automatiquement les nouveaux problèmes
   - Suggère des solutions basées sur l'historique

3. **Corrélation infrastructure**
   - Hosts → Services → Incidents
   - Dépendances entre services
   - Impact d'un problème sur l'infra

4. **Suivi CVE**
   - Relie CVE aux services/hosts affectés
   - Track les vulnérabilités par environnement

## Schéma du graphe

### Types de noeuds

```
Host        - hostname, ip, os, environment, role
Service     - name, version, port, status, criticality
Incident    - id, title, priority, status, symptoms, solution
Symptom     - description, metric, threshold, severity
RootCause   - description, category, confidence
Solution    - description, steps, commands, success_rate
Pattern     - name, symptoms, keywords, confidence
CVE         - id, severity, cvss_score, affected_packages
```

### Relations

```
Service    -[RUNS_ON]->     Host
Service    -[DEPENDS_ON]->  Service
Incident   -[HAS_SYMPTOM]-> Symptom
Incident   -[CAUSED_BY]->   RootCause
Incident   -[RESOLVED_BY]-> Solution
Incident   -[SIMILAR_TO]->  Incident
Incident   -[AFFECTED]->    Host/Service
Pattern    -[MATCHES]->     Incident
Pattern    -[SUGGESTS]->    Solution
CVE        -[EXPLOITS]->    Service/Host
```

## Installation et configuration

### Démarrer FalkorDB

```bash
# Démarrage simple
docker run -d -p 6379:6379 --name merlya-falkordb falkordb/falkordb:latest

# Avec persistance
docker run -d -p 6379:6379 \
  --name merlya-falkordb \
  -v falkordb-data:/data \
  --restart unless-stopped \
  falkordb/falkordb:latest
```

### Configuration

Variables d'environnement (optionnelles) :

```bash
FALKORDB_HOST=localhost    # Défaut: localhost
FALKORDB_PORT=6379         # Défaut: 6379
FALKORDB_GRAPH=ops_knowledge  # Nom du graphe
```

### Auto-démarrage Docker

Merlya peut démarrer automatiquement le conteneur Docker si :
- Docker est installé et accessible
- `auto_start_docker=True` dans la config (défaut)

## Utilisation dans Merlya

### Vérifier le statut

```bash
merlya status
```

Affiche :
```
FalkorDB: ✅ Connected (62 nodes, 0 relationships)
```

ou :
```
FalkorDB: ❌ Not available (SQLite fallback active)
```

### Dans le REPL

La ligne de statut indique :
- `✅ FalkorDB` - Connecté, mémoire long terme active
- `💾 SQLite only` - Mode dégradé, SQLite uniquement

### Via l'API

```python
from merlya.knowledge import get_knowledge_manager

km = get_knowledge_manager()

# Enregistrer un incident
incident_id = km.record_incident(
    title="MongoDB connection timeout",
    priority="P1",
    service="mongodb",
    symptoms=["connection refused", "timeout after 30s"],
    environment="prod"
)

# Résoudre avec apprentissage
km.resolve_incident(
    incident_id=incident_id,
    root_cause="Connection pool exhausted",
    solution="Increased max_pool_size from 10 to 50",
    commands_executed=["vim /etc/mongodb.conf", "systemctl restart mongod"],
    learn_pattern=True  # Crée un pattern automatiquement
)

# Trouver des incidents similaires
similar = km.find_similar_incidents(
    symptoms=["connection refused"],
    service="mongodb"
)

# Obtenir une suggestion basée sur l'historique
suggestion = km.get_suggestion(
    text="mongodb high latency",
    service="mongodb"
)
```

## Fonctionnement du StorageManager

### Architecture hybride

Le `StorageManager` combine SQLite et FalkorDB :

```python
class StorageManager:
    def store_incident(self, incident):
        # 1. Essaie FalkorDB d'abord
        synced = self.falkordb.store_incident(incident)  # Returns True/False

        # 2. Stocke toujours dans SQLite (avec flag synced)
        self.sqlite.store_incident(incident, synced=synced)
```

### Synchronisation

Les données non-synchronisées sont rattrapées :

```python
# Sync manuel
storage.sync_to_falkordb()

# Sync automatique en background (configurable)
storage = StorageManager(auto_sync_interval=300)  # Toutes les 5 min
```

### Retry avec backoff exponentiel

```python
RetryConfig(
    max_retries=3,
    initial_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0
)
```

## Requêtes Cypher

### Exemples de requêtes directes

```python
from merlya.knowledge.falkordb_client import get_falkordb_client

client = get_falkordb_client(auto_connect=True)

# Trouver tous les incidents P0
results = client.query("""
    MATCH (i:Incident)
    WHERE i.priority = 'P0'
    RETURN i
    ORDER BY i.created_at DESC
    LIMIT 10
""")

# Trouver les services affectés par un incident
results = client.query("""
    MATCH (i:Incident)-[:AFFECTED]->(s:Service)
    WHERE i.id = $incident_id
    RETURN s.name, s.status
""", {"incident_id": "INC-20241201120000"})

# Chaîne de dépendances
results = client.query("""
    MATCH path = (s:Service)-[:DEPENDS_ON*1..3]->(dep:Service)
    WHERE s.name = 'api-gateway'
    RETURN path
""")
```

## Dégradation gracieuse

Si FalkorDB n'est pas disponible :

1. **Détection automatique** - Merlya teste la connexion au démarrage
2. **Fallback SQLite** - Toutes les opérations utilisent SQLite
3. **Pas de perte de données** - SQLite stocke tout, prêt pour sync ultérieur
4. **Fonctionnalités réduites** - Pas de requêtes graph complexes

```
[WARNING] FalkorDB not available - using SQLite-only mode.
Run 'docker run -d -p 6379:6379 falkordb/falkordb' to enable.
```

## Visualisation

### RedisInsight

FalkorDB est compatible avec RedisInsight pour visualiser le graphe :

```bash
docker run -d -p 8001:8001 redislabs/redisinsight:latest
```

Puis ouvrir http://localhost:8001 et connecter à `localhost:6379`.

### Statistiques

```bash
merlya status
```

Ou via Python :

```python
km = get_knowledge_manager()
stats = km.get_stats()
print(stats['storage']['falkordb'])
# {'connected': True, 'graph_name': 'ops_knowledge', 'total_nodes': 62, ...}
```

## Bonnes pratiques

1. **Toujours résoudre les incidents avec `learn_pattern=True`** pour enrichir la base de connaissances

2. **Utiliser des symptômes descriptifs** pour améliorer le matching :
   ```python
   # Bon
   symptoms=["connection refused on port 27017", "timeout after 30s"]

   # Moins bon
   symptoms=["error", "timeout"]
   ```

3. **Synchroniser régulièrement** si FalkorDB était indisponible :
   ```python
   km.sync_knowledge()
   ```

4. **Monitorer le graphe** via `merlya status` ou les stats API

## Troubleshooting

### FalkorDB ne se connecte pas

```bash
# Vérifier si le port est ouvert
nc -zv localhost 6379

# Vérifier les conteneurs Docker
docker ps -a | grep falkordb

# Logs du conteneur
docker logs merlya-falkordb
```

### Erreur "unhashable type: list"

Ce bug était présent dans les versions < 0.x.x. Mettez à jour Merlya :
```bash
pip install --upgrade merlya
```

### Données non synchronisées

```python
# Voir le statut de sync
storage.get_sync_status()
# {'unsynced_incidents': 5, 'falkordb_available': True, ...}

# Forcer la sync
storage.sync_to_falkordb()
```

## Fichiers sources

| Fichier | Description |
|---------|-------------|
| `merlya/knowledge/graph/client.py` | Client FalkorDB bas niveau |
| `merlya/knowledge/graph/config.py` | Configuration FalkorDB |
| `merlya/knowledge/storage/falkordb_store.py` | Store FalkorDB |
| `merlya/knowledge/storage_manager.py` | Gestionnaire hybride SQLite+FalkorDB |
| `merlya/knowledge/schema.py` | Schéma du graphe (nodes, relations) |
| `merlya/knowledge/ops_knowledge_manager.py` | Facade principale |
| `merlya/knowledge/incident_memory.py` | Gestion des incidents |
| `merlya/knowledge/pattern_learner.py` | Apprentissage de patterns |
