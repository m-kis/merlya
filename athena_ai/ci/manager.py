"""
CI Platform Manager - Agnostic platform detection and management.

Automatically detects available CI platforms and provides unified access.
No hardcoded platform preferences - adapts to what's available.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from athena_ai.ci.config import CIConfig
from athena_ai.ci.models import DetectedPlatform
from athena_ai.ci.protocols import CIPlatformProtocol, CIPlatformType
from athena_ai.ci.registry import get_ci_registry, register_builtin_platforms
from athena_ai.utils.logger import logger


class CIPlatformManager:
    """
    Manages CI platform detection and access.

    Features:
    - Automatic platform detection from multiple sources
    - Dynamic adapter selection based on availability
    - Support for multiple simultaneous platforms
    - No hardcoded platform preferences
    """

    # Platform detection patterns
    CONFIG_PATTERNS: Dict[str, List[str]] = {
        "github": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
        "gitlab": [".gitlab-ci.yml", ".gitlab-ci.yaml"],
        "jenkins": ["Jenkinsfile", "jenkins/*.groovy"],
        "circleci": [".circleci/config.yml", ".circleci/config.yaml"],
        "travis": [".travis.yml", ".travis.yaml"],
        "azure": ["azure-pipelines.yml", ".azure-pipelines/*.yml"],
        "bitbucket": ["bitbucket-pipelines.yml"],
    }

    # Git remote patterns for platform detection
    REMOTE_PATTERNS: Dict[str, List[str]] = {
        "github": [r"github\.com[:/]", r"github\..*[:/]"],  # Includes GHE
        "gitlab": [r"gitlab\.com[:/]", r"gitlab\..*[:/]"],  # Includes self-hosted
        "bitbucket": [r"bitbucket\.org[:/]", r"bitbucket\..*[:/]"],
        "azure": [r"dev\.azure\.com[:/]", r"visualstudio\.com[:/]"],
    }

    # CLI tools for platform detection
    CLI_TOOLS: Dict[str, str] = {
        "github": "gh",
        "gitlab": "glab",
        "jenkins": "jenkins-cli",
        "circleci": "circleci",
    }

    # Environment variables for platform detection
    ENV_VARS: Dict[str, List[str]] = {
        "github": ["GITHUB_ACTIONS", "GITHUB_TOKEN", "GH_TOKEN"],
        "gitlab": ["GITLAB_CI", "GITLAB_TOKEN", "CI_JOB_TOKEN"],
        "jenkins": ["JENKINS_URL", "JENKINS_HOME", "BUILD_ID"],
        "circleci": ["CIRCLECI", "CIRCLE_TOKEN"],
        "travis": ["TRAVIS", "TRAVIS_BUILD_ID"],
        "azure": ["TF_BUILD", "AZURE_DEVOPS_EXT_PAT"],
        "bitbucket": ["BITBUCKET_BUILD_NUMBER", "BITBUCKET_PIPELINE_UUID"],
    }

    def __init__(
        self,
        project_path: Optional[Path] = None,
        config: Optional[CIConfig] = None,
    ):
        """
        Initialize the platform manager.

        Args:
            project_path: Path to project root (default: current directory)
            config: Optional explicit configuration
        """
        self.project_path = project_path or Path.cwd()
        self.explicit_config = config
        self._detected: Optional[List[DetectedPlatform]] = None
        self._adapters: Dict[str, CIPlatformProtocol] = {}

        # Ensure builtin platforms are registered
        register_builtin_platforms()

    def detect_platforms(self, force: bool = False) -> List[DetectedPlatform]:
        """
        Detect all available CI platforms.

        Checks multiple sources:
        1. Config files in project
        2. Git remote URL
        3. Environment variables
        4. Available CLI tools

        Args:
            force: Force re-detection even if cached

        Returns:
            List of detected platforms with confidence scores
        """
        if self._detected is not None and not force:
            return self._detected

        detected: Dict[str, DetectedPlatform] = {}

        # Check config files
        self._detect_from_configs(detected)

        # Check git remote
        self._detect_from_git_remote(detected)

        # Check environment variables
        self._detect_from_env(detected)

        # Check CLI tools
        self._detect_from_cli(detected)

        # Sort by confidence
        result = sorted(
            detected.values(),
            key=lambda d: d.confidence,
            reverse=True,
        )

        self._detected = result
        logger.info(f"Detected {len(result)} CI platforms")
        for d in result:
            logger.debug(f"  - {d.platform.value}: {d.confidence:.0%} ({d.detection_source})")

        return result

    def get_platform(
        self,
        platform_type: Optional[CIPlatformType] = None,
    ) -> Optional[CIPlatformProtocol]:
        """
        Get a CI platform adapter.

        Args:
            platform_type: Specific platform to get (default: best available)

        Returns:
            Platform adapter, or None if not available
        """
        # If explicit config provided, use it
        if self.explicit_config:
            return self._get_adapter_from_config(self.explicit_config)

        # Detect platforms if not already done
        detected = self.detect_platforms()

        if not detected:
            logger.warning("No CI platforms detected")
            return None

        # If specific platform requested
        if platform_type:
            for d in detected:
                if d.platform == platform_type:
                    return self._get_adapter(d)
            logger.warning(f"Platform {platform_type.value} not detected")
            return None

        # Return best available (highest confidence with available adapter)
        for d in detected:
            adapter = self._get_adapter(d)
            if adapter and adapter.is_available():
                return adapter

        # Fallback: return first detected even if not fully available
        return self._get_adapter(detected[0]) if detected else None

    def get_all_platforms(self) -> Dict[str, CIPlatformProtocol]:
        """
        Get all available platform adapters.

        Returns:
            Dict mapping platform name to adapter
        """
        detected = self.detect_platforms()
        result = {}

        for d in detected:
            adapter = self._get_adapter(d)
            if adapter:
                result[d.platform.value] = adapter

        return result

    def get_best_platform(self) -> Tuple[Optional[CIPlatformProtocol], Optional[DetectedPlatform]]:
        """
        Get the best available platform with its detection info.

        Returns:
            Tuple of (adapter, detection_info) or (None, None)
        """
        detected = self.detect_platforms()

        for d in detected:
            adapter = self._get_adapter(d)
            if adapter and adapter.is_available():
                return adapter, d

        return None, None

    def _detect_from_configs(self, detected: Dict[str, DetectedPlatform]) -> None:
        """Detect platforms from config files."""
        for platform, patterns in self.CONFIG_PATTERNS.items():
            for pattern in patterns:
                # Handle glob patterns
                if "*" in pattern:
                    parent = pattern.split("*")[0].rstrip("/")
                    parent_path = self.project_path / parent
                    if parent_path.exists():
                        suffix = pattern.split("*")[-1]
                        matches = list(parent_path.glob(f"*{suffix}"))
                        if matches:
                            self._add_detection(
                                detected,
                                platform,
                                "config_file",
                                0.9,
                                {"files": [str(m) for m in matches[:5]]},
                            )
                            break
                else:
                    config_path = self.project_path / pattern
                    if config_path.exists():
                        self._add_detection(
                            detected,
                            platform,
                            "config_file",
                            0.95,
                            {"file": str(config_path)},
                        )
                        break

    def _detect_from_git_remote(self, detected: Dict[str, DetectedPlatform]) -> None:
        """Detect platforms from git remote URL."""
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                remote_url = result.stdout.strip()

                for platform, patterns in self.REMOTE_PATTERNS.items():
                    for pattern in patterns:
                        if re.search(pattern, remote_url):
                            # Extract repo info
                            repo_info = self._parse_repo_url(remote_url)
                            self._add_detection(
                                detected,
                                platform,
                                "git_remote",
                                0.8,
                                {"url": remote_url, **repo_info},
                            )
                            break

        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    def _detect_from_env(self, detected: Dict[str, DetectedPlatform]) -> None:
        """Detect platforms from environment variables."""
        for platform, env_vars in self.ENV_VARS.items():
            for var in env_vars:
                if os.environ.get(var):
                    # Higher confidence for CI-specific vars
                    confidence = 0.95 if "_CI" in var or "ACTIONS" in var else 0.7
                    self._add_detection(
                        detected,
                        platform,
                        "environment",
                        confidence,
                        {"env_var": var},
                    )
                    break

    def _detect_from_cli(self, detected: Dict[str, DetectedPlatform]) -> None:
        """Detect platforms from available CLI tools."""
        for platform, cli_tool in self.CLI_TOOLS.items():
            if shutil.which(cli_tool):
                self._add_detection(
                    detected,
                    platform,
                    "cli_tool",
                    0.6,
                    {"tool": cli_tool},
                )

    def _add_detection(
        self,
        detected: Dict[str, DetectedPlatform],
        platform: str,
        source: str,
        confidence: float,
        details: Dict[str, Any],
    ) -> None:
        """Add or update a detection entry."""
        try:
            platform_type = CIPlatformType(platform)
        except ValueError:
            logger.debug(f"Unknown platform type: {platform}")
            return

        existing = detected.get(platform)

        if existing:
            # Update if higher confidence
            if confidence > existing.confidence:
                existing.confidence = confidence
                existing.detection_source = source
                existing.details = details
            # Merge details
            existing.details.update(details)
        else:
            detected[platform] = DetectedPlatform(
                platform=platform_type,
                confidence=confidence,
                detection_source=source,
                details=details,
            )

    def _parse_repo_url(self, url: str) -> Dict[str, str]:
        """Parse repository owner/name from URL."""
        result: Dict[str, str] = {}

        # SSH format: git@github.com:owner/repo.git
        ssh_match = re.search(r"[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
        if ssh_match:
            result["owner"] = ssh_match.group(1)
            result["repo"] = ssh_match.group(2)

        # HTTPS format: https://github.com/owner/repo.git
        https_match = re.search(r"https?://[^/]+/([^/]+)/([^/]+?)(?:\.git)?$", url)
        if https_match:
            result["owner"] = https_match.group(1)
            result["repo"] = https_match.group(2)

        return result

    def _get_adapter(self, detection: DetectedPlatform) -> Optional[CIPlatformProtocol]:
        """Get or create adapter for detected platform."""
        platform_name = detection.platform.value

        if platform_name in self._adapters:
            return self._adapters[platform_name]

        # Build config from detection
        config = self._build_config(detection)

        return self._get_adapter_from_config(config)

    def _get_adapter_from_config(self, config: CIConfig) -> Optional[CIPlatformProtocol]:
        """Get adapter from explicit config."""
        platform_name = config.platform

        if platform_name in self._adapters:
            return self._adapters[platform_name]

        registry = get_ci_registry()

        if not registry.has(platform_name):
            logger.warning(f"No adapter registered for platform: {platform_name}")
            return None

        try:
            adapter = registry.get(platform_name, config=config)
            self._adapters[platform_name] = adapter
            return adapter
        except Exception as e:
            logger.error(f"Failed to create adapter for {platform_name}: {e}")
            return None

    def _build_config(self, detection: DetectedPlatform) -> CIConfig:
        """Build config from detection details."""
        platform = detection.platform
        details = detection.details

        if platform == CIPlatformType.GITHUB:
            return CIConfig.for_github(
                repo_owner=details.get("owner"),
                repo_name=details.get("repo"),
            )
        elif platform == CIPlatformType.GITLAB:
            owner = details.get("owner", "")
            repo = details.get("repo", "")
            project_path = f"{owner}/{repo}" if owner and repo else None
            return CIConfig.for_gitlab(project_path=project_path)
        elif platform == CIPlatformType.JENKINS:
            return CIConfig.for_jenkins(
                api_base_url=os.environ.get("JENKINS_URL", "http://localhost:8080"),
            )
        elif platform == CIPlatformType.CIRCLECI:
            owner = details.get("owner", "")
            repo = details.get("repo", "")
            project_slug = f"gh/{owner}/{repo}" if owner and repo else None
            return CIConfig.for_circleci(project_slug=project_slug)
        else:
            # Generic config
            return CIConfig(platform=platform.value)
