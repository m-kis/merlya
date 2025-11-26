"""
Role Inference Service - DDD Domain Service.

Responsible for:
- Inferring server roles from hostnames and services
- Generating human-readable role explanations
"""
from typing import Dict, List, Optional


class RoleInferenceService:
    """
    Domain Service for inferring server roles and generating explanations.
    """

    # Type names mapping
    TYPE_NAMES = {
        "load_balancer": "Load Balancer",
        "database": "Serveur de Base de Données",
        "cache": "Serveur de Cache",
        "web": "Serveur Web",
        "app": "Serveur d'Application",
        "unknown": "Serveur"
    }

    # Service pattern matching
    SERVICE_PATTERNS = {
        "load_balancer": ["haproxy", "nginx", "traefik"],
        "database": ["mysql", "postgres", "mongodb", "mariadb"],
        "cache": ["redis", "memcached"],
        "web": ["nginx", "apache", "httpd"],
        "app": ["java", "python", "node"]
    }

    # Service descriptions for explanations
    SERVICE_DESCRIPTIONS = {
        "haproxy": "**HAProxy** : Distribution intelligente du trafic avec health checks",
        "nginx": "**Nginx** : Reverse proxy, load balancer et serveur web haute performance",
        "mysql": "**MySQL** : Base de données relationnelle SQL",
        "mariadb": "**MariaDB** : Base de données relationnelle (fork de MySQL)",
        "postgres": "**PostgreSQL** : Base de données relationnelle avancée",
        "mongodb": "**MongoDB** : Base de données NoSQL orientée documents",
        "redis": "**Redis** : Cache en mémoire et broker de messages",
        "memcached": "**Memcached** : Système de cache distribué en mémoire",
        "apache": "**Apache** : Serveur web HTTP",
        "traefik": "**Traefik** : Reverse proxy et load balancer moderne"
    }

    # Type icons for display
    TYPE_ICONS = {
        "load_balancer": "⚖️",
        "database": "🗄️",
        "cache": "⚡",
        "web": "🌐",
        "app": "📦",
        "unknown": "🖥️"
    }

    def infer_role(self, hostname: str, services: List[str]) -> Dict:
        """
        Infer server role from hostname pattern and installed services.

        Args:
            hostname: Server hostname
            services: List of detected services

        Returns:
            {
                "type": "load_balancer" | "database" | "cache" | "web" | "app" | "unknown",
                "environment": "production" | "préproduction" | "staging" | "développement" | "unknown",
                "primary_services": [list of main services],
                "description": "Human-readable description"
            }
        """
        role = {
            "type": "unknown",
            "environment": "unknown",
            "primary_services": [],
            "description": ""
        }

        hostname_lower = hostname.lower()

        # Detect environment from hostname
        role["environment"] = self._detect_environment(hostname_lower)

        # Detect type from hostname
        role["type"] = self._detect_type_from_hostname(hostname_lower)

        # Refine type with services (service patterns override hostname guessing)
        role = self._refine_type_with_services(role, services)

        # Remove duplicates
        role["primary_services"] = list(set(role["primary_services"]))

        # Generate description
        role["description"] = self.TYPE_NAMES.get(role["type"], "Serveur")
        if role["environment"] != "unknown":
            role["description"] += f" de {role['environment']}"

        return role

    def _detect_environment(self, hostname_lower: str) -> str:
        """Detect environment from hostname."""
        if "prod" in hostname_lower and "preprod" not in hostname_lower:
            return "production"
        elif "preprod" in hostname_lower:
            return "préproduction"
        elif "staging" in hostname_lower or "stag" in hostname_lower:
            return "staging"
        elif "dev" in hostname_lower:
            return "développement"
        elif "qa" in hostname_lower or "test" in hostname_lower:
            return "test/QA"
        return "unknown"

    def _detect_type_from_hostname(self, hostname_lower: str) -> str:
        """Detect type from hostname patterns."""
        if "lb" in hostname_lower or "loadbalancer" in hostname_lower or "haproxy" in hostname_lower:
            return "load_balancer"
        elif "db" in hostname_lower or "database" in hostname_lower or "sql" in hostname_lower:
            return "database"
        elif "cache" in hostname_lower or "redis" in hostname_lower or "memcache" in hostname_lower:
            return "cache"
        elif "web" in hostname_lower or "front" in hostname_lower or "www" in hostname_lower:
            return "web"
        elif "app" in hostname_lower or "backend" in hostname_lower:
            return "app"
        return "unknown"

    def _refine_type_with_services(self, role: Dict, services: List[str]) -> Dict:
        """Refine type detection using installed services."""
        for service_type, patterns in self.SERVICE_PATTERNS.items():
            matches = [s for s in services if any(p in s.lower() for p in patterns)]
            if matches:
                if role["type"] == "unknown" or len(matches) >= 2:
                    # If we found 2+ matching services, it's a strong signal
                    role["type"] = service_type
                role["primary_services"].extend(matches[:3])  # Keep top 3
        return role

    def generate_explanation(
        self,
        hostname: str,
        role_info: Dict,
        services: List[str],
        uptime_days: Optional[int] = None
    ) -> str:
        """
        Generate human-readable explanation of server's role.

        Args:
            hostname: Server hostname
            role_info: Role information dict from infer_role()
            services: List of detected services
            uptime_days: Uptime in days (optional)

        Returns:
            Formatted Markdown explanation
        """
        lines = []
        lines.append("")

        # Header with icon
        icon = self.TYPE_ICONS.get(role_info["type"], "🖥️")
        lines.append(f"# {icon} {hostname.upper()} - {role_info['description']}")
        lines.append("")

        # Role section
        lines.append("## 🎯 Rôle")
        lines.append("")
        lines.append(self._get_role_description(hostname, role_info["type"]))
        lines.append("")

        # Services section
        if role_info["primary_services"]:
            lines.append("## 🔧 Services Principaux")
            lines.append("")
            for service in role_info["primary_services"]:
                service_desc = self.SERVICE_DESCRIPTIONS.get(service, f"**{service}**")
                lines.append(f"- {service_desc}")
            lines.append("")

        # Environment section
        lines.append("## 🌍 Environnement")
        lines.append("")
        env_display = role_info['environment'].capitalize() if role_info['environment'] != "unknown" else "Non identifié"
        type_display = role_info['description']
        lines.append(f"- **Type** : {type_display}")
        lines.append(f"- **Environnement** : {env_display}")

        if uptime_days is not None:
            status_icon = "✅" if uptime_days > 0 else "❓"
            lines.append(f"- **Disponibilité** : {status_icon} Opérationnel ({uptime_days} jours d'uptime)")

        lines.append("")

        return "\n".join(lines)

    def _get_role_description(self, hostname: str, role_type: str) -> str:
        """Get detailed role description based on type."""
        descriptions = {
            "load_balancer": f"**{hostname}** est un **load balancer** qui distribue le trafic HTTP/HTTPS entre plusieurs serveurs backend. Il assure la haute disponibilité et la répartition optimale de la charge.",
            "database": f"**{hostname}** est un **serveur de base de données** qui stocke et gère les données de l'application. Il assure la persistance et la cohérence des données.",
            "cache": f"**{hostname}** est un **serveur de cache** qui accélère les performances en mettant en cache des données fréquemment accédées. Il réduit la charge sur les bases de données.",
            "web": f"**{hostname}** est un **serveur web** qui héberge et sert les contenus statiques et dynamiques aux utilisateurs via HTTP/HTTPS.",
            "app": f"**{hostname}** est un **serveur d'application** qui exécute la logique métier et traite les requêtes des utilisateurs.",
            "unknown": f"**{hostname}** est un serveur dont le rôle exact n'a pas pu être déterminé automatiquement."
        }
        return descriptions.get(role_type, descriptions["unknown"])
