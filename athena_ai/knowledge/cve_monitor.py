"""
CVE Monitor for Athena.

Uses OSV.dev API to:
- Check packages for known vulnerabilities
- Monitor for new CVEs affecting the infrastructure
- Provide security recommendations
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger

OSV_API_URL = "https://api.osv.dev/v1"


@dataclass
class CVE:
    """A CVE/vulnerability record."""
    id: str
    summary: str = ""
    details: str = ""
    severity: str = ""  # CRITICAL, HIGH, MEDIUM, LOW
    cvss_score: float = 0.0
    affected_packages: List[str] = field(default_factory=list)
    affected_versions: List[str] = field(default_factory=list)
    fixed_versions: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    published: str = ""
    modified: str = ""
    aliases: List[str] = field(default_factory=list)


@dataclass
class VulnerabilityCheck:
    """Result of a vulnerability check."""
    package: str
    version: str
    ecosystem: str
    vulnerabilities: List[CVE] = field(default_factory=list)
    is_vulnerable: bool = False
    highest_severity: str = ""
    checked_at: str = ""


class CVEMonitor:
    """
    Monitor CVEs using OSV.dev API.

    Features:
    - Check packages for known vulnerabilities
    - Query by CVE ID
    - Batch checking for multiple packages
    - Caching to avoid repeated API calls
    """

    def __init__(self, cache_ttl_hours: int = 24):
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self._cache: Dict[str, Dict] = {}  # cache_key -> {data, timestamp}

    def _get_cache_key(self, package: str, version: str, ecosystem: str) -> str:
        """Generate cache key for a package check."""
        return f"{ecosystem}:{package}:{version}"

    def _is_cache_valid(self, key: str) -> bool:
        """Check if cache entry is still valid."""
        if key not in self._cache:
            return False
        entry = self._cache[key]
        return datetime.now() - entry["timestamp"] < self.cache_ttl

    def _make_request(self, endpoint: str, data: Dict = None) -> Optional[Dict]:
        """Make HTTP request to OSV API."""
        url = f"{OSV_API_URL}/{endpoint}"

        try:
            if data:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(data).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
            else:
                req = urllib.request.Request(url)

            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))

        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            logger.error(f"OSV API error: {e.code} {e.reason}")
            return None
        except urllib.error.URLError as e:
            logger.error(f"OSV API connection error: {e.reason}")
            return None
        except Exception as e:
            logger.error(f"OSV API request failed: {e}")
            return None

    def check_package(
        self,
        package: str,
        version: str,
        ecosystem: str = "PyPI",
    ) -> VulnerabilityCheck:
        """
        Check a package for vulnerabilities.

        Args:
            package: Package name (e.g., "requests")
            version: Package version (e.g., "2.28.0")
            ecosystem: Package ecosystem (PyPI, npm, Go, Maven, etc.)

        Returns:
            VulnerabilityCheck with results
        """
        cache_key = self._get_cache_key(package, version, ecosystem)

        # Check cache
        if self._is_cache_valid(cache_key):
            cached = self._cache[cache_key]["data"]
            logger.debug(f"CVE cache hit: {package}@{version}")
            return cached

        # Query OSV
        response = self._make_request("query", {
            "package": {
                "name": package,
                "ecosystem": ecosystem,
            },
            "version": version,
        })

        vulnerabilities = []
        highest_severity = ""
        severity_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

        if response and "vulns" in response:
            for vuln in response["vulns"]:
                cve = self._parse_vulnerability(vuln)
                vulnerabilities.append(cve)

                # Track highest severity
                if cve.severity:
                    if severity_order.get(cve.severity, 0) > severity_order.get(highest_severity, 0):
                        highest_severity = cve.severity

        result = VulnerabilityCheck(
            package=package,
            version=version,
            ecosystem=ecosystem,
            vulnerabilities=vulnerabilities,
            is_vulnerable=len(vulnerabilities) > 0,
            highest_severity=highest_severity,
            checked_at=datetime.now().isoformat(),
        )

        # Cache result
        self._cache[cache_key] = {
            "data": result,
            "timestamp": datetime.now(),
        }

        if result.is_vulnerable:
            logger.warning(
                f"Package {package}@{version} has {len(vulnerabilities)} vulnerabilities "
                f"(highest: {highest_severity})"
            )

        return result

    def _parse_vulnerability(self, vuln_data: Dict) -> CVE:
        """Parse OSV vulnerability response into CVE object."""
        # Get severity from CVSS if available
        severity = ""
        cvss_score = 0.0

        if "severity" in vuln_data:
            for sev in vuln_data["severity"]:
                if sev.get("type") == "CVSS_V3":
                    cvss_score = sev.get("score", 0.0)
                    # Map CVSS score to severity
                    if cvss_score >= 9.0:
                        severity = "CRITICAL"
                    elif cvss_score >= 7.0:
                        severity = "HIGH"
                    elif cvss_score >= 4.0:
                        severity = "MEDIUM"
                    else:
                        severity = "LOW"
                    break

        # If no CVSS, try database_specific
        if not severity and "database_specific" in vuln_data:
            db_severity = vuln_data["database_specific"].get("severity")
            if db_severity:
                severity = db_severity.upper()

        # Get affected and fixed versions
        affected_versions = []
        fixed_versions = []
        affected_packages = []

        for affected in vuln_data.get("affected", []):
            pkg = affected.get("package", {})
            pkg_name = pkg.get("name", "")
            if pkg_name:
                affected_packages.append(pkg_name)

            for version_range in affected.get("ranges", []):
                for event in version_range.get("events", []):
                    if "introduced" in event:
                        affected_versions.append(f">={event['introduced']}")
                    if "fixed" in event:
                        fixed_versions.append(event["fixed"])

        # Get references
        references = [
            ref.get("url", "")
            for ref in vuln_data.get("references", [])
            if ref.get("url")
        ]

        # Get aliases (including CVE IDs)
        aliases = vuln_data.get("aliases", [])

        return CVE(
            id=vuln_data.get("id", ""),
            summary=vuln_data.get("summary", ""),
            details=vuln_data.get("details", ""),
            severity=severity,
            cvss_score=cvss_score,
            affected_packages=affected_packages,
            affected_versions=affected_versions,
            fixed_versions=fixed_versions,
            references=references[:5],  # Limit references
            published=vuln_data.get("published", ""),
            modified=vuln_data.get("modified", ""),
            aliases=aliases,
        )

    def get_cve(self, cve_id: str) -> Optional[CVE]:
        """
        Get details for a specific CVE/vulnerability ID.

        Args:
            cve_id: CVE ID (e.g., "CVE-2024-1234") or OSV ID (e.g., "GHSA-xxx")

        Returns:
            CVE details or None if not found
        """
        response = self._make_request(f"vulns/{cve_id}")

        if not response:
            return None

        return self._parse_vulnerability(response)

    def batch_check(
        self,
        packages: List[Dict[str, str]],
    ) -> List[VulnerabilityCheck]:
        """
        Check multiple packages for vulnerabilities.

        Args:
            packages: List of dicts with "name", "version", and optional "ecosystem"

        Returns:
            List of VulnerabilityCheck results
        """
        results = []

        for pkg in packages:
            name = pkg.get("name", "")
            version = pkg.get("version", "")
            ecosystem = pkg.get("ecosystem", "PyPI")

            if name and version:
                result = self.check_package(name, version, ecosystem)
                results.append(result)

        return results

    def check_requirements_txt(self, content: str) -> List[VulnerabilityCheck]:
        """
        Check packages from requirements.txt content.

        Args:
            content: Contents of requirements.txt file

        Returns:
            List of VulnerabilityCheck results
        """
        packages = []

        for line in content.split("\n"):
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            # Parse package==version
            if "==" in line:
                parts = line.split("==")
                name = parts[0].strip()
                version = parts[1].split()[0].strip()  # Handle extras
                packages.append({
                    "name": name,
                    "version": version,
                    "ecosystem": "PyPI",
                })

        return self.batch_check(packages)

    def check_package_json(self, content: str) -> List[VulnerabilityCheck]:
        """
        Check packages from package.json content.

        Args:
            content: Contents of package.json file

        Returns:
            List of VulnerabilityCheck results
        """
        packages = []

        try:
            data = json.loads(content)

            for dep_type in ["dependencies", "devDependencies"]:
                deps = data.get(dep_type, {})
                for name, version in deps.items():
                    # Clean version string (remove ^, ~, etc.)
                    clean_version = version.lstrip("^~>=<")
                    if clean_version and clean_version[0].isdigit():
                        packages.append({
                            "name": name,
                            "version": clean_version,
                            "ecosystem": "npm",
                        })

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse package.json: {e}")

        return self.batch_check(packages)

    def get_summary(self, checks: List[VulnerabilityCheck]) -> Dict[str, Any]:
        """
        Get summary of vulnerability checks.

        Returns:
            Summary with counts, critical packages, recommendations
        """
        total_packages = len(checks)
        vulnerable_packages = [c for c in checks if c.is_vulnerable]
        total_vulnerabilities = sum(len(c.vulnerabilities) for c in checks)

        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for check in vulnerable_packages:
            for vuln in check.vulnerabilities:
                if vuln.severity in severity_counts:
                    severity_counts[vuln.severity] += 1

        # Identify critical packages
        critical_packages = [
            {
                "package": c.package,
                "version": c.version,
                "severity": c.highest_severity,
                "count": len(c.vulnerabilities),
                "fix_available": any(v.fixed_versions for v in c.vulnerabilities),
            }
            for c in vulnerable_packages
            if c.highest_severity in ("CRITICAL", "HIGH")
        ]

        return {
            "total_packages": total_packages,
            "vulnerable_packages": len(vulnerable_packages),
            "total_vulnerabilities": total_vulnerabilities,
            "severity_counts": severity_counts,
            "critical_packages": critical_packages,
            "needs_attention": severity_counts["CRITICAL"] > 0 or severity_counts["HIGH"] > 0,
        }

    def clear_cache(self):
        """Clear the vulnerability cache."""
        self._cache.clear()
        logger.debug("CVE cache cleared")
