# Plan de Refonte : Inventaire et Scan

## Vision

Transformer le système d'inventaire d'Athena pour :
1. **Scan local initial** : Scanner la machine hôte au démarrage, stocker en BDD
2. **Inventaire manuel** : Commande `/inventory` pour import multi-formats
3. **Scans on-demand** : Plus de scan automatique, seulement lors d'actions ciblées
4. **Améliorations** : Parallélisation, versioning, relations IA, rate limiting, retry

---

## Phase 1 : Refonte du Schéma BDD

### 1.1 Nouvelles Tables SQLite

```sql
-- Table principale des hôtes (enrichie)
CREATE TABLE hosts_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hostname TEXT NOT NULL UNIQUE,
    ip_address TEXT,
    aliases TEXT,  -- JSON array
    environment TEXT,  -- prod/staging/dev
    groups TEXT,  -- JSON array
    role TEXT,
    service TEXT,
    ssh_port INTEGER DEFAULT 22,
    status TEXT DEFAULT 'unknown',  -- unknown, online, offline
    source_id INTEGER,  -- FK vers inventory_sources
    metadata TEXT,  -- JSON
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES inventory_sources(id)
);

-- Sources d'inventaire importées
CREATE TABLE inventory_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,  -- csv, txt, json, yaml, etc_hosts, ssh_config
    file_path TEXT,  -- Chemin original si fichier
    import_method TEXT,  -- manual, auto
    host_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT  -- JSON (paramètres d'import)
);

-- Versioning des hôtes
CREATE TABLE host_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    changes TEXT NOT NULL,  -- JSON des champs modifiés
    changed_by TEXT,  -- user ou system
    created_at TEXT NOT NULL,
    FOREIGN KEY (host_id) REFERENCES hosts_v2(id) ON DELETE CASCADE
);

-- Snapshots globaux de l'inventaire
CREATE TABLE inventory_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    description TEXT,
    host_count INTEGER,
    snapshot_data TEXT NOT NULL,  -- JSON complet
    created_at TEXT NOT NULL
);

-- Relations entre hôtes
CREATE TABLE host_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_host_id INTEGER NOT NULL,
    target_host_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,  -- depends_on, backup_of, cluster_member, etc.
    confidence REAL DEFAULT 1.0,  -- Score IA
    metadata TEXT,  -- JSON
    created_at TEXT NOT NULL,
    validated_by_user INTEGER DEFAULT 0,  -- 0=suggestion, 1=validé
    FOREIGN KEY (source_host_id) REFERENCES hosts_v2(id) ON DELETE CASCADE,
    FOREIGN KEY (target_host_id) REFERENCES hosts_v2(id) ON DELETE CASCADE
);

-- Cache des scans on-demand
CREATE TABLE scan_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id INTEGER NOT NULL,
    scan_type TEXT NOT NULL,  -- os, services, resources, processes, etc.
    data TEXT NOT NULL,  -- JSON
    ttl_seconds INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (host_id) REFERENCES hosts_v2(id) ON DELETE CASCADE
);

-- Contexte de la machine locale
CREATE TABLE local_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,  -- os, network, services, processes, etc_files
    key TEXT NOT NULL,
    value TEXT NOT NULL,  -- JSON si complexe
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(category, key)
);
```

### 1.2 Fichiers à Modifier/Créer

| Action | Fichier | Description |
|--------|---------|-------------|
| CREATE | `athena_ai/memory/persistence/inventory_repository.py` | Nouveau repository pour inventaire v2 |
| MODIFY | `athena_ai/memory/persistence/host_repository.py` | Migration vers nouveau schéma |

---

## Phase 2 : Scan Local Initial (avec Cache Intelligent)

### 2.1 Nouveau Module LocalScanner

**Fichier** : `athena_ai/context/local_scanner.py`

```python
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

@dataclass
class LocalContext:
    os_info: dict
    network: dict
    services: dict
    processes: list
    etc_files: dict
    resources: dict
    scanned_at: datetime

class LocalScanner:
    """
    Scanner approfondi de la machine locale.
    Stocké en BDD, re-scanné uniquement si:
    - Pas de scan existant
    - Scan trop vieux (> 12h par défaut)
    """

    DEFAULT_TTL_HOURS = 12

    def __init__(self, repo: 'InventoryRepository' = None):
        self.repo = repo or InventoryRepository()

    def get_or_scan(self, force: bool = False, ttl_hours: int = None) -> LocalContext:
        """
        Récupère le contexte local depuis la BDD ou scanne si nécessaire.

        Args:
            force: Force un nouveau scan même si cache valide
            ttl_hours: TTL personnalisé (défaut: 12h)

        Returns:
            LocalContext avec les infos de la machine locale
        """
        ttl = ttl_hours or self.DEFAULT_TTL_HOURS

        if not force:
            # Vérifier si un scan existe et est encore valide
            existing = self.repo.get_local_context()
            if existing:
                scanned_at = datetime.fromisoformat(existing['scanned_at'])
                age_hours = (datetime.now() - scanned_at).total_seconds() / 3600

                if age_hours < ttl:
                    # Cache valide, retourner
                    return self._dict_to_context(existing)

                # Cache expiré, log et rescan
                logger.info(f"Local context expired ({age_hours:.1f}h > {ttl}h), rescanning...")

        # Scan complet
        context = self.scan_all()

        # Sauvegarder en BDD
        self.repo.save_local_context(self._context_to_dict(context))

        return context

    def scan_all(self) -> LocalContext:
        """Scan complet de la machine locale."""
        return LocalContext(
            os_info=self._scan_os(),
            network=self._scan_network(),
            services=self._scan_services(),
            processes=self._scan_processes(),
            etc_files=self._scan_etc_files(),
            resources=self._scan_resources(),
            scanned_at=datetime.now(),
        )

    def _scan_os(self) -> dict:
        """OS, Kernel, Distribution."""

    def _scan_network(self) -> dict:
        """Interfaces réseau, IPs, routes."""

    def _scan_services(self) -> dict:
        """
        Services actifs (multi-méthode):
        - systemd (Linux)
        - launchd (macOS)
        - init.d scripts
        - Docker containers
        """

    def _scan_processes(self) -> list:
        """Top processes avec CPU/RAM."""

    def _scan_etc_files(self) -> dict:
        """
        Fichiers pertinents dans /etc:
        - /etc/hosts
        - /etc/hostname
        - /etc/resolv.conf
        - /etc/ssh/ssh_config
        - etc.
        """

    def _scan_resources(self) -> dict:
        """CPU, RAM, Disque."""
```

### 2.2 Intégration au Démarrage

**Fichier à modifier** : `athena_ai/repl/core.py`

```python
class AthenaREPL:
    def __init__(self, env: str = "dev"):
        # ...existing code...

        # Contexte local (depuis cache ou scan si nécessaire)
        self._initialize_local_context()

    def _initialize_local_context(self):
        """
        Charge le contexte local.

        Logique:
        1. Si scan existe et < 12h → utiliser le cache
        2. Si scan existe et >= 12h → rescan
        3. Si pas de scan → premier scan
        """
        scanner = LocalScanner()

        with console.status("[cyan]Loading local context...[/cyan]", spinner="dots"):
            context = scanner.get_or_scan()

        logger.info(f"Local context loaded (scanned at: {context.scanned_at})")
```

---

## Phase 3 : Commande `/inventory` et Sélection `@Host`

### 3.1 Structure de la Commande REPL

**Fichier** : `athena_ai/repl/commands/inventory.py`

```python
INVENTORY_COMMANDS = {
    '/inventory add': 'Add inventory from file or path',
    '/inventory list': 'List all inventory sources',
    '/inventory show': 'Show hosts from a source',
    '/inventory remove': 'Remove an inventory source',
    '/inventory export': 'Export inventory to file',
    '/inventory snapshot': 'Create inventory snapshot',
    '/inventory relations': 'Manage host relations',
    '/inventory search': 'Search hosts by criteria',
}

class InventoryCommandHandler:
    def __init__(self, repl):
        self.repl = repl
        self.parser = InventoryParser()
        self.repo = InventoryRepository()
        self.classifier = HostRelationClassifier()

    def handle(self, args: list) -> bool:
        if not args:
            self._show_help()
            return True

        cmd = args[0]
        if cmd == 'add':
            return self._handle_add(args[1:])
        elif cmd == 'list':
            return self._handle_list(args[1:])
        # ...
```

### 3.2 Sélection d'Hôtes via `@hostname` dans les Prompts

**Extension du système de variables existant** pour supporter les hôtes de l'inventaire.

**Fichier à modifier** : `athena_ai/security/credentials.py`

```python
class CredentialManager:
    """
    Gère les variables utilisateur ET les références aux hôtes de l'inventaire.

    Syntaxe supportée dans les prompts:
    - @variable_name → Variable définie par l'utilisateur
    - @MachineA → Hôte de l'inventaire (hostname)

    Priorité: Variables utilisateur > Hôtes inventaire
    """

    def resolve_variables(self, text: str) -> str:
        """
        Résout les @références dans le texte.

        Exemples:
        - "Vérifie @web-prod-01" → "Vérifie web-prod-01" (+ contexte hôte)
        - "Check @mydb using @dbpass" → Variables + hôte
        """
        # 1. Résoudre les variables utilisateur (existant)
        resolved = self._resolve_user_variables(text)

        # 2. Résoudre les références aux hôtes de l'inventaire
        resolved = self._resolve_inventory_hosts(resolved)

        return resolved

    def _resolve_inventory_hosts(self, text: str) -> str:
        """
        Détecte les @hostname et les enrichit avec le contexte.

        Si @MachineA est un hôte valide dans l'inventaire:
        - Remplace par le hostname canonique
        - Ajoute les métadonnées au contexte (IP, env, groups)
        """
        import re
        from athena_ai.memory.persistence.inventory_repository import InventoryRepository

        repo = InventoryRepository()
        pattern = r'@([a-zA-Z0-9_\-\.]+)'

        def replace_host(match):
            potential_host = match.group(1)

            # Vérifier si c'est une variable utilisateur (priorité)
            if potential_host in self._variables:
                return self._variables[potential_host]

            # Vérifier si c'est un hôte de l'inventaire
            host = repo.get_host_by_name(potential_host)
            if host:
                # Stocker le contexte de l'hôte pour les tools
                self._current_host_context = host
                return host['hostname']

            # Ni variable ni hôte → garder tel quel
            return match.group(0)

        return re.sub(pattern, replace_host, text)

    def get_current_host_context(self) -> Optional[dict]:
        """Retourne le contexte de l'hôte résolu (si @host utilisé)."""
        return getattr(self, '_current_host_context', None)
```

### 3.3 Auto-complétion des Hôtes

**Fichier à modifier** : `athena_ai/repl/completer.py`

```python
def create_completer(context_manager, credentials_manager) -> Completer:
    """
    Crée le completer avec support:
    - Commandes slash (/)
    - Variables (@var)
    - Hôtes inventaire (@hostname)
    """

    class AthenaCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            word = document.get_word_before_cursor()

            # Complétion @host ou @variable
            if '@' in text:
                prefix = text.split('@')[-1]

                # 1. Variables utilisateur
                for var in credentials_manager.list_variables():
                    if var.startswith(prefix):
                        yield Completion(var, start_position=-len(prefix))

                # 2. Hôtes de l'inventaire
                repo = InventoryRepository()
                for host in repo.search_hosts(pattern=prefix, limit=20):
                    if host['hostname'].startswith(prefix):
                        # Afficher avec contexte (env, IP)
                        display = f"{host['hostname']} ({host.get('environment', '?')})"
                        yield Completion(
                            host['hostname'],
                            start_position=-len(prefix),
                            display=display,
                            display_meta=host.get('ip_address', ''),
                        )
```

### 3.4 Mise à Jour du `/help`

**Fichier à modifier** : `athena_ai/repl/commands.py`

```python
SLASH_COMMANDS = {
    # ... existing commands ...
    '/inventory': 'Inventory management (add, list, remove, export, relations)',
}

def _show_help(self):
    # ... existing help ...

    help_text += "\n## Inventory Management\n\n"
    help_text += "Manage your infrastructure inventory:\n"
    help_text += "- `/inventory add <file>` - Import hosts from file (CSV, JSON, YAML, etc.)\n"
    help_text += "- `/inventory add /etc/hosts` - Import from system file\n"
    help_text += "- `/inventory list` - List all inventory sources\n"
    help_text += "- `/inventory show [source]` - Show hosts from a source\n"
    help_text += "- `/inventory search <pattern>` - Search hosts\n"
    help_text += "- `/inventory remove <source>` - Remove an inventory source\n"
    help_text += "- `/inventory export <file>` - Export inventory\n"
    help_text += "- `/inventory snapshot [name]` - Create inventory snapshot\n"
    help_text += "- `/inventory relations suggest` - Get AI-suggested host relations\n"
    help_text += "- `/inventory relations list` - List validated relations\n"

    help_text += "\n## Host References (@hostname)\n\n"
    help_text += "Reference hosts from inventory in your prompts:\n"
    help_text += "- `check nginx on @web-prod-01` - Reference by hostname\n"
    help_text += "- `compare @db-master with @db-replica` - Multiple hosts\n"
    help_text += "- `@hostname` auto-completes from inventory (press Tab)\n"
    help_text += "- Priority: user variables > inventory hosts\n"

    help_text += "\n## Examples\n\n"
    help_text += "- `/inventory add ~/servers.csv`\n"
    help_text += "- `/inventory add /etc/hosts`\n"
    help_text += "- `vérifie moi la @MachineA`\n"
    help_text += "- `check mysql status on @db-prod-01`\n"
    help_text += "- `/inventory relations suggest` → validate AI suggestions\n"
```

### 3.5 Parseur Multi-Format avec IA

**Fichier** : `athena_ai/inventory/parser.py`

```python
class InventoryParser:
    """
    Parseur intelligent multi-format.
    Utilise un LLM local (Ollama) pour comprendre les formats non-standard.
    """

    SUPPORTED_FORMATS = ['csv', 'json', 'yaml', 'txt', 'ini', 'etc_hosts', 'ssh_config']

    def __init__(self):
        self.llm = LLMRouter(provider='ollama')

    def parse(self, source: str, format_hint: str = None) -> List[Host]:
        """
        Parse une source d'inventaire.

        Args:
            source: Chemin fichier ou contenu brut
            format_hint: Format suggéré (optionnel)
        """
        # Détecter le format
        if format_hint:
            format_type = format_hint
        else:
            format_type = self._detect_format(source)

        # Parser selon le format
        if format_type in ['csv', 'json', 'yaml', 'ini']:
            return self._parse_structured(source, format_type)
        elif format_type == 'etc_hosts':
            return self._parse_etc_hosts(source)
        elif format_type == 'ssh_config':
            return self._parse_ssh_config(source)
        else:
            # Format non-standard -> LLM
            return self._parse_with_llm(source)

    def _parse_with_llm(self, content: str) -> List[Host]:
        """
        Utilise le LLM pour comprendre un format non-standard.
        """
        prompt = f"""
        Analyse ce contenu d'inventaire et extrait les hôtes.
        Retourne un JSON array avec les champs:
        - hostname (required)
        - ip_address (optional)
        - environment (optional: prod/staging/dev)
        - groups (optional: array)
        - metadata (optional: dict)

        Contenu:
        {content[:2000]}

        Retourne UNIQUEMENT le JSON, sans explication.
        """

        response = self.llm.generate(prompt, task='correction')
        return self._parse_llm_response(response)
```

### 3.6 Formats Supportés

| Format | Détection | Parser |
|--------|-----------|--------|
| CSV | `.csv` ou header | `csv.DictReader` |
| JSON | `.json` ou `{`/`[` | `json.loads` |
| YAML | `.yml`/`.yaml` | `yaml.safe_load` |
| INI (Ansible) | `.ini` ou `[group]` | Custom parser |
| /etc/hosts | Chemin ou format | Regex parser |
| ~/.ssh/config | Chemin ou `Host ` | Custom parser |
| Autre | Fallback | LLM parser |

---

## Phase 4 : Scan On-Demand

### 4.1 Refonte du Scanner

**Fichier** : `athena_ai/context/on_demand_scanner.py`

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Optional
import time

@dataclass
class ScanResult:
    host_id: int
    hostname: str
    scan_type: str
    data: dict
    success: bool
    error: Optional[str] = None
    duration_ms: int = 0

class OnDemandScanner:
    """
    Scanner on-demand avec:
    - Parallélisation
    - Rate limiting
    - Retry logic
    - Cache intelligent
    """

    # TTL par type de donnée (en secondes)
    TTL_CONFIG = {
        'os': 86400,        # 24h - change rarement
        'kernel': 86400,    # 24h
        'resources': 3600,  # 1h - RAM/CPU statique
        'disk': 3600,       # 1h
        'services': 1800,   # 30min
        'processes': 300,   # 5min - change souvent
        'network': 3600,    # 1h
        'connectivity': 60, # 1min - test rapide
    }

    def __init__(
        self,
        max_parallel: int = 5,
        rate_limit_per_second: float = 2.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self.max_parallel = max_parallel
        self.rate_limit = rate_limit_per_second
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.repo = InventoryRepository()
        self.ssh = SSHManager()
        self._last_request_time = 0
        self._executor = ThreadPoolExecutor(max_workers=max_parallel)

    async def scan_hosts(
        self,
        hostnames: List[str],
        scan_types: List[str] = None,
        force: bool = False,
    ) -> Dict[str, ScanResult]:
        """
        Scan plusieurs hôtes en parallèle.

        Args:
            hostnames: Liste des hôtes à scanner
            scan_types: Types de scan (default: tous)
            force: Ignorer le cache
        """
        scan_types = scan_types or ['connectivity', 'os', 'services']
        results = {}

        # Filtrer les hôtes avec cache valide
        if not force:
            hostnames = self._filter_cached(hostnames, scan_types)

        # Créer les tâches
        tasks = []
        for hostname in hostnames:
            task = self._scan_with_retry(hostname, scan_types)
            tasks.append(task)

        # Exécuter en parallèle avec rate limiting
        async for result in self._execute_with_rate_limit(tasks):
            results[result.hostname] = result

        return results

    async def _scan_with_retry(
        self,
        hostname: str,
        scan_types: List[str],
    ) -> ScanResult:
        """Scan avec retry logic."""
        last_error = None

        for attempt in range(self.max_retries):
            try:
                return await self._do_scan(hostname, scan_types)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))

        return ScanResult(
            host_id=0,
            hostname=hostname,
            scan_type='failed',
            data={},
            success=False,
            error=str(last_error),
        )

    async def _execute_with_rate_limit(self, tasks):
        """Exécute les tâches avec rate limiting."""
        semaphore = asyncio.Semaphore(self.max_parallel)

        async def limited_task(task):
            async with semaphore:
                # Rate limiting
                elapsed = time.time() - self._last_request_time
                if elapsed < 1.0 / self.rate_limit:
                    await asyncio.sleep(1.0 / self.rate_limit - elapsed)
                self._last_request_time = time.time()
                return await task

        for coro in asyncio.as_completed([limited_task(t) for t in tasks]):
            yield await coro
```

### 4.2 Détection de Services (Multi-Méthode)

```python
class ServiceDetector:
    """
    Détection robuste de services (pas seulement systemd).
    """

    def detect(self, hostname: str) -> List[dict]:
        """Détecte tous les services sur un hôte."""
        services = []

        # 1. systemd (Linux moderne)
        services.extend(self._detect_systemd(hostname))

        # 2. init.d (Linux legacy)
        services.extend(self._detect_initd(hostname))

        # 3. Docker containers
        services.extend(self._detect_docker(hostname))

        # 4. Processus écoutant sur ports
        services.extend(self._detect_listening_ports(hostname))

        # 5. launchd (macOS)
        services.extend(self._detect_launchd(hostname))

        return self._deduplicate(services)

    def _detect_listening_ports(self, hostname: str) -> List[dict]:
        """Détecte les services via netstat/ss."""
        cmd = "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null"
        # Parse output...
```

---

## Phase 5 : Classification IA des Relations

### 5.0 Choix du Modèle IA

**Modèle utilisé** : Le même que pour l'intent parsing et le triage (Ollama local).

Configuré via `ModelConfig.TASK_MODELS['correction']` → modèle rapide (haiku/fast).

Pourquoi ce choix :

- **Consistance** : Même infrastructure que le triage existant
- **Performance** : Modèle rapide pour classification simple
- **Local** : Pas de dépendance cloud pour l'analyse des patterns
- **Configurable** : L'utilisateur peut changer le modèle via `/model set`

```python
# Utilisation dans le classifier
from athena_ai.llm.router import LLMRouter

llm = LLMRouter()  # Utilise le provider configuré (Ollama par défaut)
response = llm.generate(prompt, task='correction')  # Modèle rapide
```

### 5.1 Classificateur de Relations

**Fichier** : `athena_ai/inventory/relation_classifier.py`

```python
class HostRelationClassifier:
    """
    Suggère des relations entre hôtes basées sur:
    - Patterns de nommage
    - Groupes/environnements
    - Services détectés
    - Métadonnées

    Utilise le même modèle LLM que le triage (Ollama local par défaut).
    """

    RELATION_TYPES = [
        'depends_on',      # A dépend de B
        'backup_of',       # A est backup de B
        'cluster_member',  # A et B dans même cluster
        'load_balanced',   # A et B derrière même LB
        'database_replica',# Réplication DB
        'related_service', # Services liés
    ]

    def __init__(self):
        # Utilise le router LLM existant (même config que triage)
        self.llm = LLMRouter()

    def suggest_relations(
        self,
        hosts: List[Host],
        existing_relations: List[Relation] = None,
    ) -> List[RelationSuggestion]:
        """
        Suggère des relations entre les hôtes.
        Retourne des suggestions avec score de confiance.
        """
        suggestions = []

        # 1. Règles heuristiques (rapide, haute confiance)
        suggestions.extend(self._heuristic_relations(hosts))

        # 2. LLM pour patterns complexes (si peu de suggestions)
        if len(suggestions) < 5:
            suggestions.extend(self._llm_relations(hosts))

        # Filtrer les relations déjà existantes
        if existing_relations:
            suggestions = self._filter_existing(suggestions, existing_relations)

        return sorted(suggestions, key=lambda x: x.confidence, reverse=True)

    def _heuristic_relations(self, hosts: List[Host]) -> List[RelationSuggestion]:
        """Relations basées sur patterns de nommage."""
        suggestions = []

        for host in hosts:
            # Pattern: xxx-01, xxx-02 -> cluster_member
            match = re.match(r'(.+)-(\d+)$', host.hostname)
            if match:
                base_name = match.group(1)
                siblings = [h for h in hosts
                           if h.hostname.startswith(base_name + '-')
                           and h.hostname != host.hostname]
                for sibling in siblings:
                    suggestions.append(RelationSuggestion(
                        source=host,
                        target=sibling,
                        relation_type='cluster_member',
                        confidence=0.8,
                        reason=f"Same naming pattern: {base_name}-*",
                    ))

            # Pattern: xxx-primary, xxx-replica -> database_replica
            # etc.

        return suggestions
```

### 5.2 Interface Utilisateur pour Validation

```python
def _handle_relations(self, args: list) -> bool:
    """Handle /inventory relations command."""
    if not args or args[0] == 'suggest':
        # Générer suggestions
        hosts = self.repo.get_all_hosts()
        suggestions = self.classifier.suggest_relations(hosts)

        if not suggestions:
            print_warning("No relation suggestions found")
            return True

        # Afficher suggestions
        table = Table(title="Suggested Host Relations")
        table.add_column("#", style="cyan")
        table.add_column("Source", style="green")
        table.add_column("Relation", style="yellow")
        table.add_column("Target", style="green")
        table.add_column("Confidence", style="magenta")
        table.add_column("Reason", style="dim")

        for i, s in enumerate(suggestions[:10], 1):
            table.add_row(
                str(i),
                s.source.hostname,
                s.relation_type,
                s.target.hostname,
                f"{s.confidence:.0%}",
                s.reason[:40],
            )

        console.print(table)

        # Demander validation
        console.print("\n[yellow]Enter numbers to accept (e.g., '1,3,5') or 'all':[/yellow]")
        choice = input("> ").strip()

        if choice.lower() == 'all':
            indices = list(range(len(suggestions)))
        else:
            indices = [int(x.strip()) - 1 for x in choice.split(',') if x.strip().isdigit()]

        # Sauvegarder les relations validées
        for i in indices:
            if 0 <= i < len(suggestions):
                self.repo.save_relation(suggestions[i], validated=True)

        print_success(f"Saved {len(indices)} relations")
        return True
```

---

## Phase 6 : Cache Intelligent

### 6.1 Gestionnaire de Cache

**Fichier** : `athena_ai/context/cache_manager.py`

```python
class ScanCacheManager:
    """
    Cache intelligent avec:
    - TTL par type de donnée
    - Invalidation automatique
    - Persistance BDD
    """

    def __init__(self):
        self.repo = InventoryRepository()

    def get(
        self,
        host_id: int,
        scan_type: str,
    ) -> Optional[dict]:
        """Récupère du cache si valide."""
        cache_entry = self.repo.get_scan_cache(host_id, scan_type)

        if not cache_entry:
            return None

        if datetime.now() > datetime.fromisoformat(cache_entry['expires_at']):
            return None

        return json.loads(cache_entry['data'])

    def set(
        self,
        host_id: int,
        scan_type: str,
        data: dict,
        ttl: int = None,
    ):
        """Stocke en cache avec TTL."""
        if ttl is None:
            ttl = OnDemandScanner.TTL_CONFIG.get(scan_type, 3600)

        self.repo.save_scan_cache(
            host_id=host_id,
            scan_type=scan_type,
            data=json.dumps(data),
            ttl_seconds=ttl,
        )

    def invalidate_host(self, host_id: int):
        """Invalide tout le cache d'un hôte."""
        self.repo.delete_scan_cache(host_id=host_id)

    def invalidate_type(self, scan_type: str):
        """Invalide un type de scan pour tous les hôtes."""
        self.repo.delete_scan_cache(scan_type=scan_type)
```

---

## Phase 7 : Intégration avec les Agents

### 7.1 Tools Mis à Jour

**Fichier à modifier** : `athena_ai/tools/hosts.py`

```python
def scan_host(hostname: str) -> str:
    """
    Scan on-demand d'un hôte.
    Utilise le cache si disponible, sinon scan SSH.
    """
    ctx = get_tool_context()

    # Validation
    is_valid, message = validate_host(hostname)
    if not is_valid:
        return f"BLOCKED: {message}"

    # Scanner on-demand avec cache
    scanner = OnDemandScanner()
    result = asyncio.run(scanner.scan_hosts([hostname]))

    # Format output...
```

### 7.2 Nouveau Tool `inventory_tool`

```python
def query_inventory(
    pattern: str = "",
    environment: str = "all",
    group: str = "",
) -> str:
    """
    Query the inventory database.

    ALWAYS use this tool FIRST to find hosts.
    No network scan is performed.
    """
    repo = InventoryRepository()
    hosts = repo.search_hosts(
        pattern=pattern,
        environment=environment,
        group=group,
    )
    # Format output...
```

---

## Résumé des Fichiers

### Nouveaux Fichiers à Créer

1. `athena_ai/memory/persistence/inventory_repository.py` - Repository BDD
2. `athena_ai/context/local_scanner.py` - Scanner local initial
3. `athena_ai/context/on_demand_scanner.py` - Scanner on-demand
4. `athena_ai/context/cache_manager.py` - Gestionnaire de cache
5. `athena_ai/inventory/parser.py` - Parseur multi-format
6. `athena_ai/inventory/relation_classifier.py` - Classification IA
7. `athena_ai/repl/commands/inventory.py` - Commande /inventory
8. `tests/test_inventory_*.py` - Tests unitaires

### Fichiers à Modifier

1. `athena_ai/repl/commands.py` - Ajouter /inventory
2. `athena_ai/repl/core.py` - Intégration scan local
3. `athena_ai/tools/hosts.py` - Refonte scan_host
4. `athena_ai/context/host_registry.py` - Utiliser nouveau repo
5. `athena_ai/context/manager.py` - Simplifier (plus de scan auto)

### Fichiers à Supprimer/Déprécier

1. `athena_ai/context/inventory_setup.py` - Remplacé par /inventory
2. `athena_ai/context/inventory_sources.py` - Consolidé dans parser.py

---

## Ordre d'Implémentation

1. **Phase 1** : Schéma BDD + Repository (fondation)
2. **Phase 2** : Scanner local (contexte de base)
3. **Phase 3** : Commande /inventory (fonctionnalité principale)
4. **Phase 4** : Scanner on-demand (parallèle, retry, cache)
5. **Phase 5** : Classification IA (relations)
6. **Phase 6** : Cache intelligent
7. **Phase 7** : Intégration agents + tests

---

## Tests Requis

- [ ] Tests unitaires pour chaque parser (CSV, JSON, YAML, etc.)
- [ ] Tests d'intégration pour import/export
- [ ] Tests de performance pour scan parallèle
- [ ] Tests de retry logic
- [ ] Tests de cache (TTL, invalidation)
- [ ] Tests de la classification IA (mocks)
