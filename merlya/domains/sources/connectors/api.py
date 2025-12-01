"""
REST API connector for querying infrastructure data from APIs.

Supports common infrastructure APIs like Netbox, Nautobot, etc.
"""
from typing import Any, Dict, List, Optional

import requests

from merlya.domains.sources.connectors.base import BaseConnector, ConnectorError, SourceMetadata, SourceType
from merlya.utils.logger import logger


class APIConnector(BaseConnector):
    """
    REST API connector for infrastructure APIs.

    Supports:
    - Netbox
    - Nautobot
    - Custom REST APIs
    """

    def __init__(
        self,
        host: str,
        port: int = 443,
        base_url: str = "",
        api_token: Optional[str] = None,
        api_type: str = "generic",
        verify_ssl: bool = True,
        **kwargs
    ):
        """
        Initialize API connector.

        Args:
            host: API host
            port: API port
            base_url: Base URL path (e.g., "/api/v1")
            api_token: API authentication token
            api_type: Type of API ("netbox", "nautobot", "generic")
            verify_ssl: Verify SSL certificates
        """
        super().__init__(host=host, port=port, **kwargs)
        self.base_url = base_url
        self.api_token = api_token
        self.api_type = api_type
        self.verify_ssl = verify_ssl

        # Build full base URL
        protocol = "https" if port == 443 else "http"
        port_str = "" if port in [80, 443] else f":{port}"
        self.full_base_url = f"{protocol}://{host}{port_str}{base_url}"

    def test_connection(self) -> bool:
        """Test API connection."""
        try:
            headers = {}
            if self.api_token:
                headers["Authorization"] = f"Token {self.api_token}"

            # Try to access root API endpoint
            response = requests.get(
                self.full_base_url,
                headers=headers,
                verify=self.verify_ssl,
                timeout=5
            )

            if response.status_code in [200, 401, 403]:
                # 200 = success, 401/403 = auth required but API is reachable
                logger.info(f"✓ API connection test successful: {self.full_base_url}")
                return True
            else:
                logger.debug(f"API connection test failed: HTTP {response.status_code}")
                return False

        except requests.exceptions.RequestException as e:
            logger.debug(f"API connection test failed: {e}")
            return False

    def query(self, query_str: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Execute API query.

        Args:
            query_str: API endpoint path (e.g., "/dcim/devices")
            params: Query parameters

        Returns:
            List of results
        """
        try:
            headers = {}
            if self.api_token:
                headers["Authorization"] = f"Token {self.api_token}"

            # Build full URL
            url = f"{self.full_base_url}{query_str}"

            response = requests.get(
                url,
                headers=headers,
                params=params or {},
                verify=self.verify_ssl,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()

                # Handle paginated responses (Netbox/Nautobot style)
                if isinstance(data, dict) and 'results' in data:
                    return data['results']
                elif isinstance(data, list):
                    return data
                else:
                    return [data]
            else:
                raise ConnectorError(f"API query failed: HTTP {response.status_code} - {response.text}")

        except requests.exceptions.RequestException as e:
            raise ConnectorError(f"API query failed: {e}") from e

    def get_metadata(self) -> SourceMetadata:
        """Get metadata about this API source."""
        return SourceMetadata(
            name=f"api_{self.api_type}_{self.host}",
            source_type=SourceType.API,
            host=self.host,
            port=self.port,
            description=f"{self.api_type.title()} API at {self.host}",
            capabilities=["inventory", "cmdb", "rest_api"]
        )

    def close(self):
        """Close API connection (no persistent connection for REST)."""
        pass

    @staticmethod
    def detect_on_localhost() -> List[Dict[str, Any]]:
        """
        Detect common infrastructure APIs on localhost.

        Checks for:
        - Netbox (default port 8000)
        - Nautobot (default port 8000, 8080)
        - Generic APIs on common ports
        """
        detected = []

        # Common API configurations
        api_configs = [
            {"port": 8000, "base_url": "/api", "api_type": "netbox"},
            {"port": 8080, "base_url": "/api", "api_type": "nautobot"},
            {"port": 8000, "base_url": "/api/v1", "api_type": "generic"},
        ]

        for config in api_configs:
            try:
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(('localhost', config['port']))
                sock.close()

                if result == 0:
                    logger.info(f"Detected {config['api_type']} API on localhost:{config['port']}")
                    detected.append({
                        "host": "localhost",
                        "port": config['port'],
                        "base_url": config['base_url'],
                        "api_type": config['api_type'],
                        "confidence": 0.6  # Lower confidence, needs verification
                    })

            except Exception as e:
                logger.debug(f"API detection failed: {e}")

        return detected

    def discover_endpoints(self) -> List[str]:
        """
        Discover available API endpoints.

        Returns:
            List of endpoint paths
        """
        try:
            # For Netbox/Nautobot, try to get API schema
            if self.api_type in ["netbox", "nautobot"]:
                headers = {}
                if self.api_token:
                    headers["Authorization"] = f"Token {self.api_token}"

                response = requests.get(
                    self.full_base_url,
                    headers=headers,
                    verify=self.verify_ssl,
                    timeout=10
                )

                if response.status_code == 200:
                    data = response.json()
                    # Netbox/Nautobot returns list of available endpoints
                    if isinstance(data, dict):
                        return list(data.keys())

        except Exception as e:
            logger.debug(f"Failed to discover API endpoints: {e}")

        return []
