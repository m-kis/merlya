"""
Permission and privilege management for command execution.
Detects sudo availability, user groups, and handles privilege elevation intelligently.
"""
from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger


class PermissionManager:
    """
    Manages permissions and privilege elevation for remote/local command execution.

    Features:
    - Detect sudo availability on hosts
    - Check user group membership (sudo, wheel, admin)
    - Auto-elevate commands when needed
    - Cache permission capabilities per host
    - Provide alternative execution strategies
    """

    def __init__(self, executor):
        self.executor = executor
        # Cache permission capabilities per host: {host: {has_sudo: bool, sudo_nopasswd: bool, groups: [], user: str}}
        self.capabilities_cache: Dict[str, Dict[str, Any]] = {}

    def detect_capabilities(self, target: str) -> Dict[str, Any]:
        """
        Detect permission capabilities on a target host.

        Returns:
            {
                'user': str,
                'has_sudo': bool,
                'sudo_nopasswd': bool,  # Can sudo without password
                'groups': List[str],
                'is_root': bool,
                'elevation_method': Optional[str]  # 'sudo', 'su', 'doas', None
            }
        """
        # Check cache first
        if target in self.capabilities_cache:
            logger.debug(f"Using cached permission capabilities for {target}")
            return self.capabilities_cache[target]

        logger.debug(f"Detecting permission capabilities on {target}")

        capabilities = {
            'user': 'unknown',
            'has_sudo': False,
            'sudo_nopasswd': False,
            'has_su': False,
            'groups': [],
            'has_privileged_group': False,
            'privileged_groups': [],
            'is_root': False,
            'elevation_method': None
        }

        # 1. Detect current user
        result = self.executor.execute(target, "whoami", confirm=True)
        if result['success']:
            capabilities['user'] = result['stdout'].strip()
            capabilities['is_root'] = (capabilities['user'] == 'root')

        # 2. Detect user groups
        result = self.executor.execute(target, "groups", confirm=True)
        if result['success']:
            capabilities['groups'] = result['stdout'].strip().split()

        # Check for privileged groups (wheel, admin, sudo)
        privileged_groups = {'wheel', 'admin', 'sudo', 'root'}
        user_groups_set = set(capabilities['groups'])
        capabilities['has_privileged_group'] = bool(user_groups_set & privileged_groups)
        capabilities['privileged_groups'] = list(user_groups_set & privileged_groups)

        # 3. Check sudo availability
        result = self.executor.execute(target, "which sudo", confirm=True)
        if result['success'] and result['stdout'].strip():
            capabilities['has_sudo'] = True

            # 4. Check if sudo works without password (try non-invasive command)
            result = self.executor.execute(target, "sudo -n true", confirm=True)
            if result['success']:
                capabilities['sudo_nopasswd'] = True
                capabilities['elevation_method'] = 'sudo'
            # Note: Don't set elevation_method yet if sudo requires password
            # We'll check for su first and prefer it over sudo-with-password

        # 5. Check for alternative elevation methods
        # Check for doas (OpenBSD/Alpine alternative to sudo)
        result = self.executor.execute(target, "which doas", confirm=True)
        if result['success'] and result['stdout'].strip():
            if not capabilities['elevation_method']:
                capabilities['elevation_method'] = 'doas'
                logger.info(f"{target}: Using doas for elevation")

        # Check for su (available on most Unix systems)
        # Prefer su if user is in wheel/admin group OR if sudo requires password
        result = self.executor.execute(target, "which su", confirm=True)
        if result['success'] and result['stdout'].strip():
            capabilities['has_su'] = True

            # Prefer su over sudo-with-password (to avoid password prompts)
            if not capabilities['elevation_method']:
                if capabilities['has_privileged_group']:
                    capabilities['elevation_method'] = 'su'
                    logger.info(f"{target}: User in privileged group {capabilities['privileged_groups']}, using 'su' for elevation")
                elif capabilities['has_sudo'] and not capabilities['sudo_nopasswd']:
                    # sudo exists but requires password, prefer su instead
                    capabilities['elevation_method'] = 'su'
                    logger.info(f"{target}: Preferring 'su' over 'sudo -S' (avoids password prompt)")
                else:
                    # su available but may not work, use as last resort
                    capabilities['elevation_method'] = 'su'
                    logger.warning(f"{target}: Using 'su' but user not in wheel/admin group, may fail")

        # 6. Fallback to sudo-with-password if nothing else available
        if not capabilities['elevation_method'] and capabilities['has_sudo']:
            capabilities['elevation_method'] = 'sudo_with_password'
            logger.warning(f"{target}: Only sudo-with-password available, commands may prompt for password")

        # 6. If root user, no elevation needed
        if capabilities['is_root']:
            capabilities['elevation_method'] = 'none'

        # Cache for future use
        self.capabilities_cache[target] = capabilities

        logger.info(f"Permission capabilities for {target}: user={capabilities['user']}, "
                   f"sudo={'yes (nopasswd)' if capabilities['sudo_nopasswd'] else 'yes' if capabilities['has_sudo'] else 'no'}, "
                   f"elevation={capabilities['elevation_method']}")

        return capabilities

    def requires_elevation(self, command: str) -> bool:
        """
        Determine if a command likely requires elevated privileges.

        Args:
            command: The command to check

        Returns:
            True if command likely needs root/sudo
        """
        # Commands that typically require root
        root_commands = [
            'systemctl', 'service', 'apt', 'yum', 'dnf', 'pacman',
            'useradd', 'userdel', 'groupadd', 'visudo',
            'iptables', 'firewall-cmd', 'ufw',
            'mount', 'umount', 'fdisk', 'parted',
            'reboot', 'shutdown', 'halt', 'poweroff'
        ]

        # Paths that require root access for writes
        root_paths = [
            '/etc/', '/var/log/', '/root/', '/sys/', '/proc/sys/',
            '/usr/bin/', '/usr/sbin/', '/sbin/'
        ]

        # Paths that often require root even for reads (protected configs)
        protected_read_paths = [
            '/etc/shadow', '/etc/gshadow', '/etc/sudoers',
            '/etc/datadog-agent/', '/etc/dd-agent/',
            '/etc/newrelic/', '/etc/zabbix/',
            '/etc/ssl/private/', '/etc/pki/tls/private/',
            '/var/log/secure', '/var/log/auth.log',
            '/var/log/audit/', '/var/log/messages',
            '/root/',
        ]

        cmd_lower = command.lower()

        # Check if command starts with a known root command
        for root_cmd in root_commands:
            if cmd_lower.startswith(root_cmd) or f" {root_cmd} " in cmd_lower:
                return True

        # Check if command accesses root paths (for write operations)
        write_operations = ['>', '>>', 'tee', 'mv', 'cp', 'rm', 'mkdir', 'touch', 'chmod', 'chown']
        for path in root_paths:
            if path in command:
                for op in write_operations:
                    if op in command:
                        return True

        # Check if command reads from protected paths (even read requires elevation)
        read_commands = ['cat', 'tail', 'head', 'less', 'more', 'grep', 'awk', 'sed', 'vim', 'vi', 'nano', 'bat', 'view']
        for protected_path in protected_read_paths:
            if protected_path in command:
                for read_cmd in read_commands:
                    # Use space suffix to avoid false positives (e.g., 'batch' matching 'bat')
                    if cmd_lower.startswith(f"{read_cmd} ") or f" {read_cmd} " in cmd_lower or f"|{read_cmd} " in cmd_lower:
                        return True

        # Check if command reads from /var/log/ (logs are often protected)
        if '/var/log/' in command:
            for read_cmd in read_commands:
                if cmd_lower.startswith(f"{read_cmd} ") or f" {read_cmd} " in cmd_lower or f"|{read_cmd} " in cmd_lower:
                    return True

        return False

    def elevate_command(self, command: str, target: str, method: Optional[str] = None) -> str:
        """
        Add privilege elevation prefix to command.

        Args:
            command: Original command
            target: Target host
            method: Optional specific method ('sudo', 'doas', etc.). Auto-detect if None.

        Returns:
            Command with elevation prefix
        """
        # Get capabilities for target
        capabilities = self.detect_capabilities(target)

        # If already root, no elevation needed
        if capabilities['is_root']:
            return command

        # If command already has sudo/doas/su, don't double-elevate
        if command.strip().startswith(('sudo ', 'doas ', 'su ', 'su-')):
            return command

        # Determine elevation method
        if method is None:
            method = capabilities.get('elevation_method')

        if method == 'sudo' or method == 'sudo_with_password':
            return f"sudo {command}"
        elif method == 'doas':
            return f"doas {command}"
        elif method == 'su':
            # su requires special handling (run command via -c)
            # Escape single quotes in command: ' becomes '\''
            # This works because: end quote ('), literal quote (\'), start quote (')
            escaped_command = command.replace("'", "'\"'\"'")
            return f"su -c '{escaped_command}'"
        else:
            # No elevation available - return original command
            logger.warning(f"No privilege elevation method available on {target} for command: {command}")
            return command

    def get_adaptive_strategies(self, goal: str, target: str) -> List[Dict[str, Any]]:
        """
        Generate adaptive execution strategies for achieving a goal.

        For example, "check mysql status" could try:
        1. systemctl status mysql (if systemd available)
        2. service mysql status (if service command available)
        3. /etc/init.d/mysql status (if init.d script exists)
        4. Check process with ps aux | grep mysql
        5. Check if MySQL port is listening

        Args:
            goal: High-level goal (e.g., "check mysql status", "restart nginx")
            target: Target host

        Returns:
            List of strategies: [{'command': str, 'description': str, 'requires_elevation': bool}, ...]
        """
        self.detect_capabilities(target)
        strategies = []

        # Parse goal to understand intent
        goal_lower = goal.lower()

        # MySQL status check strategies
        if 'mysql' in goal_lower and 'status' in goal_lower:
            strategies.extend([
                {'command': 'systemctl status mysql', 'description': 'Check via systemd', 'requires_elevation': False},
                {'command': 'systemctl status mariadb', 'description': 'Check MariaDB via systemd', 'requires_elevation': False},
                {'command': 'service mysql status', 'description': 'Check via service command', 'requires_elevation': True},
                {'command': '/etc/init.d/mysql status', 'description': 'Check via init.d script', 'requires_elevation': True},
                {'command': "ps aux | grep -i mysql | grep -v grep", 'description': 'Check if MySQL process running', 'requires_elevation': False},
                {'command': "netstat -tlnp | grep 3306 || ss -tlnp | grep 3306", 'description': 'Check if MySQL port listening', 'requires_elevation': True}
            ])

        # MongoDB status check strategies
        elif 'mongo' in goal_lower and 'status' in goal_lower:
            strategies.extend([
                {'command': 'systemctl status mongod', 'description': 'Check via systemd', 'requires_elevation': False},
                {'command': 'service mongod status', 'description': 'Check via service command', 'requires_elevation': True},
                {'command': "ps aux | grep -i mongod | grep -v grep", 'description': 'Check if MongoDB process running', 'requires_elevation': False},
                {'command': "netstat -tlnp | grep 27017 || ss -tlnp | grep 27017", 'description': 'Check if MongoDB port listening', 'requires_elevation': True}
            ])

        # Nginx status check strategies
        elif 'nginx' in goal_lower and 'status' in goal_lower:
            strategies.extend([
                {'command': 'systemctl status nginx', 'description': 'Check via systemd', 'requires_elevation': False},
                {'command': 'service nginx status', 'description': 'Check via service command', 'requires_elevation': True},
                {'command': "ps aux | grep -i nginx | grep -v grep", 'description': 'Check if nginx process running', 'requires_elevation': False},
                {'command': "nginx -t", 'description': 'Test nginx configuration', 'requires_elevation': True}
            ])

        # Add elevation prefix to commands that need it
        for strategy in strategies:
            if strategy['requires_elevation']:
                strategy['command'] = self.elevate_command(strategy['command'], target)

        return strategies

    def clear_cache(self, target: Optional[str] = None):
        """Clear cached permission capabilities."""
        if target:
            self.capabilities_cache.pop(target, None)
        else:
            self.capabilities_cache.clear()

    def format_capabilities_summary(self, target: str) -> str:
        """Format permission capabilities as human-readable summary."""
        caps = self.detect_capabilities(target)

        lines = [
            f"User: {caps['user']}",
            f"Root: {'Yes' if caps['is_root'] else 'No'}",
            f"Groups: {', '.join(caps['groups'][:5])}{'...' if len(caps['groups']) > 5 else ''}",
        ]

        # Highlight privileged groups if any
        if caps.get('has_privileged_group'):
            privileged = ', '.join(caps.get('privileged_groups', []))
            lines.append(f"Privileged groups: {privileged}")

        lines.extend([
            f"Sudo: {'Yes (no password)' if caps['sudo_nopasswd'] else 'Yes (password required)' if caps['has_sudo'] else 'No'}",
            f"Elevation method: {caps['elevation_method'] or 'None available'}"
        ])

        return "\n".join(lines)
