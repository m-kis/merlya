# Plan de Refonte SSH - Gestion Intelligente de l'Authentification

## Problème Actuel

L'authentification SSH échoue même avec un agent disponible car :
1. La clé n'est pas forcément chargée dans l'agent
2. Asyncssh ne gère pas correctement le flux MFA après publickey
3. Pas de fallback intelligent entre les méthodes d'auth

## Objectif

Gérer **tous les cas SSH possibles** de manière intelligente :
- Agent SSH avec clés chargées
- Agent SSH sans clés (les ajouter)
- Pas d'agent (en créer un ou charger directement)
- Auth par mot de passe (sans clé)
- MFA/2FA après auth initiale
- Jump hosts avec auth séparée

---

## Architecture Proposée

### 1. Nouveau Module : `merlya/ssh/auth.py`

```
SSHAuthStrategy (ABC)
├── AgentAuthStrategy      # Utilise l'agent SSH existant
├── KeyFileAuthStrategy    # Charge la clé depuis le fichier
├── PasswordAuthStrategy   # Auth username/password
└── ManagedAgentStrategy   # Crée et gère son propre agent
```

### 2. Classe `SSHAuthManager`

Responsabilités :
- Détecter l'environnement SSH (agent, clés disponibles)
- Choisir la meilleure stratégie d'auth
- Gérer le cycle de vie des credentials
- Fournir les options à asyncssh

```python
class SSHAuthManager:
    async def prepare_auth(self, host: Host) -> SSHAuthOptions:
        """Prépare l'authentification pour un host."""

    async def ensure_key_in_agent(self, key_path: str, passphrase: str | None) -> bool:
        """S'assure que la clé est dans l'agent (ajoute si nécessaire)."""

    def get_agent_keys(self) -> list[str]:
        """Liste les clés dans l'agent."""

    async def start_managed_agent(self) -> bool:
        """Démarre un agent SSH géré par Merlya si nécessaire."""
```

---

## Implémentation Détaillée

### Phase 1 : Détection de l'Environnement SSH

**Fichier:** `merlya/ssh/auth.py`

```python
@dataclass
class SSHEnvironment:
    """État de l'environnement SSH."""
    agent_available: bool           # SSH_AUTH_SOCK existe
    agent_keys: list[AgentKeyInfo]  # Clés dans l'agent
    managed_agent_pid: int | None   # PID si agent géré par Merlya

@dataclass
class AgentKeyInfo:
    fingerprint: str
    key_type: str       # rsa, ed25519, etc.
    comment: str        # Souvent le chemin du fichier
    bits: int

async def detect_ssh_environment() -> SSHEnvironment:
    """Détecte l'état de l'environnement SSH."""
    agent_sock = os.environ.get("SSH_AUTH_SOCK")
    if not agent_sock or not Path(agent_sock).exists():
        return SSHEnvironment(agent_available=False, agent_keys=[], managed_agent_pid=None)

    # Lister les clés via ssh-add -l
    keys = await _list_agent_keys()
    return SSHEnvironment(agent_available=True, agent_keys=keys, managed_agent_pid=None)

async def _list_agent_keys() -> list[AgentKeyInfo]:
    """Liste les clés dans l'agent SSH."""
    proc = await asyncio.create_subprocess_exec(
        "ssh-add", "-l",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()

    if proc.returncode != 0:
        return []  # Pas de clés ou erreur

    keys = []
    for line in stdout.decode().strip().split("\n"):
        # Format: "4096 SHA256:xxx comment (RSA)"
        parts = line.split()
        if len(parts) >= 4:
            keys.append(AgentKeyInfo(
                bits=int(parts[0]),
                fingerprint=parts[1],
                comment=parts[2] if len(parts) > 2 else "",
                key_type=parts[-1].strip("()").lower(),
            ))
    return keys
```

### Phase 2 : Gestion de l'Agent SSH

```python
class ManagedSSHAgent:
    """Agent SSH géré par Merlya."""

    _instance: ClassVar["ManagedSSHAgent | None"] = None
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    def __init__(self):
        self.agent_pid: int | None = None
        self.agent_sock: str | None = None
        self._keys_added: set[str] = set()  # Fingerprints des clés ajoutées

    @classmethod
    async def get_instance(cls) -> "ManagedSSHAgent":
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    async def ensure_running(self) -> bool:
        """S'assure qu'un agent est disponible (démarre si nécessaire)."""
        env = await detect_ssh_environment()

        if env.agent_available:
            logger.info("Using existing SSH agent")
            return True

        # Démarrer un nouvel agent
        return await self._start_agent()

    async def _start_agent(self) -> bool:
        """Démarre un nouvel agent SSH."""
        proc = await asyncio.create_subprocess_exec(
            "ssh-agent", "-s",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            logger.error("Failed to start SSH agent")
            return False

        # Parser la sortie : SSH_AUTH_SOCK=/tmp/...; export SSH_AUTH_SOCK;
        output = stdout.decode()
        for line in output.split(";"):
            if "SSH_AUTH_SOCK=" in line:
                self.agent_sock = line.split("=", 1)[1].strip()
                os.environ["SSH_AUTH_SOCK"] = self.agent_sock
            elif "SSH_AGENT_PID=" in line:
                self.agent_pid = int(line.split("=", 1)[1].strip())
                os.environ["SSH_AGENT_PID"] = str(self.agent_pid)

        logger.info(f"Started SSH agent (PID: {self.agent_pid})")
        return True

    async def add_key(self, key_path: str, passphrase: str | None = None) -> bool:
        """Ajoute une clé à l'agent."""
        key_path = str(Path(key_path).expanduser())

        if passphrase:
            # Utiliser SSH_ASKPASS pour passer le passphrase
            return await self._add_key_with_passphrase(key_path, passphrase)
        else:
            proc = await asyncio.create_subprocess_exec(
                "ssh-add", key_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                if b"passphrase" in stderr.lower():
                    return False  # Clé chiffrée, passphrase requis
                logger.error(f"Failed to add key: {stderr.decode()}")
                return False

            logger.info(f"Added key to agent: {key_path}")
            return True

    async def _add_key_with_passphrase(self, key_path: str, passphrase: str) -> bool:
        """Ajoute une clé chiffrée avec son passphrase."""
        import tempfile

        # Créer un script askpass temporaire
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(f'#!/bin/sh\necho "{passphrase}"')
            askpass_script = f.name

        try:
            os.chmod(askpass_script, 0o700)

            env = os.environ.copy()
            env["SSH_ASKPASS"] = askpass_script
            env["SSH_ASKPASS_REQUIRE"] = "force"
            env["DISPLAY"] = ":0"  # Requis pour SSH_ASKPASS

            proc = await asyncio.create_subprocess_exec(
                "ssh-add", key_path,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(f"Failed to add key with passphrase: {stderr.decode()}")
                return False

            logger.info(f"Added encrypted key to agent: {key_path}")
            return True
        finally:
            Path(askpass_script).unlink(missing_ok=True)

    async def cleanup(self):
        """Arrête l'agent géré si c'est le nôtre."""
        if self.agent_pid:
            try:
                os.kill(self.agent_pid, signal.SIGTERM)
                logger.info(f"Stopped managed SSH agent (PID: {self.agent_pid})")
            except ProcessLookupError:
                pass
            self.agent_pid = None
            self.agent_sock = None
```

### Phase 3 : Stratégies d'Authentification

```python
@dataclass
class SSHAuthOptions:
    """Options d'authentification pour asyncssh."""
    preferred_auth: str = "publickey,keyboard-interactive,password"
    client_keys: list[Any] | None = None  # Clés chargées
    password: str | None = None
    agent_path: str | None = None  # Chemin vers le socket agent
    passphrase_callback: Callable | None = None
    mfa_callback: Callable | None = None

class SSHAuthManager:
    """Gestionnaire intelligent d'authentification SSH."""

    def __init__(self, secrets: SecretStore, ui: ConsoleUI):
        self.secrets = secrets
        self.ui = ui
        self._managed_agent: ManagedSSHAgent | None = None

    async def prepare_auth(self, host: Host) -> SSHAuthOptions:
        """Prépare l'authentification pour un host."""
        options = SSHAuthOptions()

        # Déterminer la méthode d'auth
        if host.private_key:
            await self._prepare_key_auth(host, options)
        elif await self._has_stored_password(host):
            await self._prepare_password_auth(host, options)
        else:
            # Demander à l'utilisateur
            auth_method = await self._prompt_auth_method(host)
            if auth_method == "key":
                await self._prompt_and_prepare_key(host, options)
            else:
                await self._prompt_and_prepare_password(host, options)

        return options

    async def _prepare_key_auth(self, host: Host, options: SSHAuthOptions):
        """Prépare l'auth par clé."""
        key_path = Path(host.private_key).expanduser()

        # 1. Vérifier si la clé est dans l'agent
        env = await detect_ssh_environment()
        key_in_agent = any(
            key_path.name in k.comment or str(key_path) in k.comment
            for k in env.agent_keys
        )

        if key_in_agent:
            logger.info(f"Key already in agent: {key_path}")
            options.agent_path = os.environ.get("SSH_AUTH_SOCK")
            return

        # 2. Essayer d'ajouter la clé à l'agent
        passphrase = await self._get_passphrase(host, key_path)

        agent = await ManagedSSHAgent.get_instance()
        await agent.ensure_running()

        if await agent.add_key(str(key_path), passphrase):
            logger.info(f"Added key to agent: {key_path}")
            options.agent_path = os.environ.get("SSH_AUTH_SOCK")
            return

        # 3. Fallback: charger la clé directement
        logger.info(f"Loading key directly: {key_path}")
        import asyncssh
        try:
            key = asyncssh.read_private_key(str(key_path), passphrase)
            options.client_keys = [key]
        except Exception as e:
            logger.error(f"Failed to load key: {e}")
            raise

    async def _get_passphrase(self, host: Host, key_path: Path) -> str | None:
        """Récupère ou demande le passphrase d'une clé."""
        # Essayer le cache
        cache_keys = [
            f"ssh:passphrase:{host.name}",
            f"ssh:passphrase:{key_path.name}",
            f"ssh:passphrase:{key_path}",
        ]

        for key in cache_keys:
            passphrase = self.secrets.get(key)
            if passphrase:
                return passphrase

        # Vérifier si la clé est chiffrée
        if not await self._key_needs_passphrase(key_path):
            return None

        # Demander le passphrase
        passphrase = await self.ui.prompt_secret(f"Passphrase for {key_path}")

        if passphrase:
            # Cacher pour réutilisation
            for key in cache_keys:
                self.secrets.set(key, passphrase)

        return passphrase

    async def _key_needs_passphrase(self, key_path: Path) -> bool:
        """Vérifie si une clé est chiffrée."""
        import asyncssh
        try:
            asyncssh.read_private_key(str(key_path))
            return False
        except asyncssh.KeyEncryptionError:
            return True
        except Exception:
            return False

    async def _prepare_password_auth(self, host: Host, options: SSHAuthOptions):
        """Prépare l'auth par mot de passe."""
        password = self.secrets.get(f"ssh:password:{host.name}")
        if not password:
            password = await self.ui.prompt_secret(f"Password for {host.username}@{host.hostname}")
            if password:
                self.secrets.set(f"ssh:password:{host.name}", password)

        options.password = password
        options.preferred_auth = "password,keyboard-interactive"

    async def _has_stored_password(self, host: Host) -> bool:
        """Vérifie si un mot de passe est stocké."""
        return self.secrets.has(f"ssh:password:{host.name}")

    async def _prompt_auth_method(self, host: Host) -> str:
        """Demande la méthode d'auth à l'utilisateur."""
        self.ui.info(f"No authentication configured for {host.name}")
        choice = await self.ui.prompt(
            "Authentication method? [key/password]",
            default="key"
        )
        return "password" if choice.lower().startswith("p") else "key"
```

### Phase 4 : Intégration avec SSHPool

**Modifications dans `merlya/ssh/pool.py`:**

```python
class SSHPool:
    def __init__(self, ...):
        ...
        self._auth_manager: SSHAuthManager | None = None

    def set_auth_manager(self, manager: SSHAuthManager):
        """Configure le gestionnaire d'authentification."""
        self._auth_manager = manager

    async def _build_ssh_options(
        self,
        host: str,
        username: str | None,
        private_key: str | None,
        opts: SSHConnectionOptions,
    ) -> dict[str, object]:
        """Build SSH connection options."""
        known_hosts = None if self.auto_add_host_keys else self._get_known_hosts_path()

        options: dict[str, object] = {
            "host": host,
            "port": opts.port,
            "known_hosts": known_hosts,
            "agent_forwarding": True,
        }

        if username:
            options["username"] = username

        # Utiliser le gestionnaire d'auth si disponible
        if self._auth_manager:
            # Créer un Host temporaire pour l'auth manager
            temp_host = Host(
                id="temp",
                name=host,
                hostname=host,
                port=opts.port,
                username=username,
                private_key=private_key,
            )
            auth_opts = await self._auth_manager.prepare_auth(temp_host)

            options["preferred_auth"] = auth_opts.preferred_auth
            if auth_opts.client_keys:
                options["client_keys"] = auth_opts.client_keys
            if auth_opts.password:
                options["password"] = auth_opts.password
            if auth_opts.agent_path:
                options["agent_path"] = auth_opts.agent_path
        else:
            # Fallback ancien comportement
            options["preferred_auth"] = "publickey,keyboard-interactive"
            # ... ancien code ...

        return options
```

---

## Flux d'Authentification Révisé

```
/ssh connect deploy
        │
        ▼
┌─────────────────────────────────┐
│  SSHAuthManager.prepare_auth()  │
└─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│  Host a private_key configuré?  │
└─────────────────────────────────┘
        │
    ┌───┴───┐
   OUI     NON
    │       │
    ▼       ▼
┌────────┐  ┌────────────────────┐
│ Clé    │  │ Password stocké?   │
│ existe │  └────────────────────┘
└────────┘          │
    │          ┌────┴────┐
    ▼         OUI       NON
┌────────────────┐      │
│ Clé dans agent?│      ▼
└────────────────┘  ┌────────────────┐
    │               │ Demander méthode│
┌───┴───┐           │ (key/password) │
OUI    NON          └────────────────┘
│       │
▼       ▼
USE   ┌──────────────────┐
AGENT │ Clé chiffrée?    │
      └──────────────────┘
           │
      ┌────┴────┐
     OUI       NON
      │         │
      ▼         ▼
  ┌─────────┐ ┌─────────────┐
  │ Get/Ask │ │ Add to agent│
  │passphrase│ │ directly   │
  └─────────┘ └─────────────┘
      │
      ▼
  ┌─────────────────┐
  │ Add key to agent│
  │ avec passphrase │
  └─────────────────┘
      │
      ▼
  ┌─────────────────┐
  │ Connexion via   │
  │ agent SSH       │
  └─────────────────┘
```

---

## Fichiers à Créer/Modifier

### Nouveaux Fichiers

| Fichier | Description |
|---------|-------------|
| `merlya/ssh/auth.py` | SSHAuthManager, ManagedSSHAgent, stratégies |

### Fichiers à Modifier

| Fichier | Modifications |
|---------|---------------|
| `merlya/ssh/pool.py` | Intégrer SSHAuthManager, simplifier `_build_ssh_options` |
| `merlya/commands/handlers/ssh.py` | Utiliser SSHAuthManager, simplifier callbacks |
| `merlya/core/context.py` | Ajouter `get_auth_manager()` |
| `merlya/persistence/models.py` | Ajouter `auth_method: str` à Host (optional) |

---

## Tests à Ajouter

```
tests/
├── test_ssh_auth.py
│   ├── test_detect_ssh_environment
│   ├── test_managed_agent_lifecycle
│   ├── test_add_key_to_agent
│   ├── test_add_encrypted_key_to_agent
│   ├── test_auth_manager_key_in_agent
│   ├── test_auth_manager_key_not_in_agent
│   ├── test_auth_manager_password_auth
│   └── test_auth_manager_prompt_method
```

---

## Avantages de cette Architecture

1. **Séparation des responsabilités** : Auth séparé du pooling
2. **Réutilisation de l'agent** : Pas besoin de re-entrer le passphrase
3. **Fallback intelligent** : Agent → Clé directe → Password
4. **Support MFA** : Intégré via keyboard-interactive
5. **Cache des credentials** : Via SecretStore (keyring)
6. **Testable** : Chaque composant mockable

---

## Ordre d'Implémentation

1. [ ] Créer `merlya/ssh/auth.py` avec `detect_ssh_environment()`
2. [ ] Implémenter `ManagedSSHAgent` (singleton, start, add_key)
3. [ ] Implémenter `SSHAuthManager.prepare_auth()`
4. [ ] Intégrer dans `SSHPool._build_ssh_options()`
5. [ ] Simplifier `merlya/commands/handlers/ssh.py`
6. [ ] Ajouter tests unitaires
7. [ ] Nettoyer le code de debug temporaire
8. [ ] Tester avec serveur MFA réel

---

## Questions/Décisions

1. **Faut-il persister l'état de l'agent géré entre les sessions?**
   - Recommandation: Non, l'agent meurt avec le process Merlya

2. **Timeout pour les clés dans l'agent?**
   - Recommandation: Utiliser le défaut ssh-agent (pas de timeout)

3. **Support des certificats SSH?**
   - À ajouter dans une phase ultérieure si besoin
