from dataclasses import dataclass

DEFAULT_PORT = 6379
DEFAULT_GRAPH = "ops_knowledge"

@dataclass
class FalkorDBConfig:
    """Configuration for FalkorDB connection."""
    host: str = "localhost"
    port: int = DEFAULT_PORT
    graph_name: str = DEFAULT_GRAPH
    auto_start_docker: bool = True
    connection_timeout: int = 30
