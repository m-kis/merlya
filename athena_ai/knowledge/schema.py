"""
Graph Schema for FalkorDB Knowledge Graph.

Defines node types, relationship types, and indexes for the
infrastructure knowledge graph.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List


class NodeType(str, Enum):
    """Types of nodes in the knowledge graph."""

    # Infrastructure
    HOST = "Host"
    SERVICE = "Service"
    CONTAINER = "Container"
    NETWORK = "Network"

    # Incidents
    INCIDENT = "Incident"
    SYMPTOM = "Symptom"
    ROOT_CAUSE = "RootCause"
    SOLUTION = "Solution"

    # Knowledge
    PATTERN = "Pattern"
    RUNBOOK = "Runbook"
    COMMAND = "Command"
    CVE = "CVE"

    # Context
    ENVIRONMENT = "Environment"
    TEAM = "Team"
    USER = "User"


class RelationType(str, Enum):
    """Types of relationships in the knowledge graph."""

    # Infrastructure relationships
    RUNS_ON = "RUNS_ON"  # Service -> Host
    DEPENDS_ON = "DEPENDS_ON"  # Service -> Service
    CONNECTS_TO = "CONNECTS_TO"  # Host -> Host
    PART_OF = "PART_OF"  # Host -> Network
    CONTAINS = "CONTAINS"  # Host -> Container

    # Incident relationships
    HAS_SYMPTOM = "HAS_SYMPTOM"  # Incident -> Symptom
    CAUSED_BY = "CAUSED_BY"  # Incident -> RootCause
    RESOLVED_BY = "RESOLVED_BY"  # Incident -> Solution
    SIMILAR_TO = "SIMILAR_TO"  # Incident -> Incident
    AFFECTED = "AFFECTED"  # Incident -> Host/Service

    # Knowledge relationships
    MATCHES = "MATCHES"  # Pattern -> Incident
    SUGGESTS = "SUGGESTS"  # Pattern -> Solution
    DOCUMENTED_IN = "DOCUMENTED_IN"  # Solution -> Runbook
    EXECUTED = "EXECUTED"  # Solution -> Command
    EXPLOITS = "EXPLOITS"  # CVE -> Service/Host

    # Context relationships
    BELONGS_TO = "BELONGS_TO"  # Host -> Environment
    OWNED_BY = "OWNED_BY"  # Service -> Team
    REPORTED_BY = "REPORTED_BY"  # Incident -> User


@dataclass
class NodeSchema:
    """Schema definition for a node type."""
    label: str
    properties: Dict[str, str]  # name -> type (string, int, float, datetime, list)
    required: List[str]
    indexes: List[str]  # Properties to index


@dataclass
class RelationshipSchema:
    """Schema definition for a relationship type."""
    type: str
    from_labels: List[str]
    to_labels: List[str]
    properties: Dict[str, str]


# Complete graph schema definition
GRAPH_SCHEMA = {
    "nodes": {
        NodeType.HOST: NodeSchema(
            label="Host",
            properties={
                "hostname": "string",
                "ip": "string",
                "os": "string",
                "os_version": "string",
                "environment": "string",
                "role": "string",
                "last_seen": "datetime",
                "accessible": "boolean",
                "created_at": "datetime",
            },
            required=["hostname"],
            indexes=["hostname", "ip", "environment"],
        ),

        NodeType.SERVICE: NodeSchema(
            label="Service",
            properties={
                "name": "string",
                "version": "string",
                "port": "int",
                "protocol": "string",
                "status": "string",  # running, stopped, degraded
                "criticality": "string",  # critical, high, medium, low
                "last_check": "datetime",
            },
            required=["name"],
            indexes=["name", "port"],
        ),

        NodeType.INCIDENT: NodeSchema(
            label="Incident",
            properties={
                "id": "string",
                "title": "string",
                "description": "string",
                "priority": "string",  # P0, P1, P2, P3
                "status": "string",  # open, investigating, resolved, closed
                "created_at": "datetime",
                "resolved_at": "datetime",
                "ttd": "int",  # Time to detect (seconds)
                "ttr": "int",  # Time to resolve (seconds)
                "environment": "string",
                "tags": "list",
            },
            required=["id", "title", "priority"],
            indexes=["id", "priority", "status", "created_at"],
        ),

        NodeType.SYMPTOM: NodeSchema(
            label="Symptom",
            properties={
                "description": "string",
                "metric": "string",
                "threshold": "float",
                "actual_value": "float",
                "severity": "string",
            },
            required=["description"],
            indexes=["metric"],
        ),

        NodeType.ROOT_CAUSE: NodeSchema(
            label="RootCause",
            properties={
                "description": "string",
                "category": "string",  # config, capacity, bug, external, human
                "confidence": "float",
            },
            required=["description"],
            indexes=["category"],
        ),

        NodeType.SOLUTION: NodeSchema(
            label="Solution",
            properties={
                "description": "string",
                "steps": "list",
                "commands": "list",
                "success_rate": "float",
                "avg_time_seconds": "int",
                "times_used": "int",
            },
            required=["description"],
            indexes=[],
        ),

        NodeType.PATTERN: NodeSchema(
            label="Pattern",
            properties={
                "name": "string",
                "description": "string",
                "symptoms": "list",  # List of symptom descriptions
                "keywords": "list",
                "confidence_threshold": "float",
                "times_matched": "int",
                "last_matched": "datetime",
            },
            required=["name"],
            indexes=["name"],
        ),

        NodeType.CVE: NodeSchema(
            label="CVE",
            properties={
                "id": "string",  # CVE-2024-1234
                "description": "string",
                "severity": "string",  # critical, high, medium, low
                "cvss_score": "float",
                "affected_packages": "list",
                "affected_versions": "list",
                "fixed_versions": "list",
                "published_at": "datetime",
                "last_checked": "datetime",
            },
            required=["id"],
            indexes=["id", "severity"],
        ),

        NodeType.COMMAND: NodeSchema(
            label="Command",
            properties={
                "command": "string",
                "description": "string",
                "is_read_only": "boolean",
                "is_dangerous": "boolean",
                "requires_sudo": "boolean",
                "times_executed": "int",
                "success_rate": "float",
            },
            required=["command"],
            indexes=["command"],
        ),

        NodeType.ENVIRONMENT: NodeSchema(
            label="Environment",
            properties={
                "name": "string",  # prod, staging, dev
                "description": "string",
                "criticality": "string",
            },
            required=["name"],
            indexes=["name"],
        ),
    },

    "relationships": {
        RelationType.RUNS_ON: RelationshipSchema(
            type="RUNS_ON",
            from_labels=["Service", "Container"],
            to_labels=["Host"],
            properties={"since": "datetime"},
        ),

        RelationType.DEPENDS_ON: RelationshipSchema(
            type="DEPENDS_ON",
            from_labels=["Service"],
            to_labels=["Service"],
            properties={"type": "string"},  # hard, soft
        ),

        RelationType.HAS_SYMPTOM: RelationshipSchema(
            type="HAS_SYMPTOM",
            from_labels=["Incident"],
            to_labels=["Symptom"],
            properties={"detected_at": "datetime"},
        ),

        RelationType.CAUSED_BY: RelationshipSchema(
            type="CAUSED_BY",
            from_labels=["Incident"],
            to_labels=["RootCause"],
            properties={"confidence": "float"},
        ),

        RelationType.RESOLVED_BY: RelationshipSchema(
            type="RESOLVED_BY",
            from_labels=["Incident"],
            to_labels=["Solution"],
            properties={"duration_seconds": "int", "success": "boolean"},
        ),

        RelationType.SIMILAR_TO: RelationshipSchema(
            type="SIMILAR_TO",
            from_labels=["Incident"],
            to_labels=["Incident"],
            properties={"similarity_score": "float"},
        ),

        RelationType.AFFECTED: RelationshipSchema(
            type="AFFECTED",
            from_labels=["Incident"],
            to_labels=["Host", "Service"],
            properties={"impact": "string"},
        ),

        RelationType.MATCHES: RelationshipSchema(
            type="MATCHES",
            from_labels=["Pattern"],
            to_labels=["Incident"],
            properties={"confidence": "float", "matched_at": "datetime"},
        ),

        RelationType.SUGGESTS: RelationshipSchema(
            type="SUGGESTS",
            from_labels=["Pattern"],
            to_labels=["Solution"],
            properties={"priority": "int"},
        ),

        RelationType.EXPLOITS: RelationshipSchema(
            type="EXPLOITS",
            from_labels=["CVE"],
            to_labels=["Service", "Host"],
            properties={"exploitable": "boolean", "checked_at": "datetime"},
        ),

        RelationType.BELONGS_TO: RelationshipSchema(
            type="BELONGS_TO",
            from_labels=["Host", "Service"],
            to_labels=["Environment"],
            properties={},
        ),
    },
}


def get_create_index_queries(graph_name: str = "ops_knowledge") -> List[str]:
    """Generate Cypher queries to create indexes for all indexed properties."""
    queries = []

    for _node_type, schema in GRAPH_SCHEMA["nodes"].items():
        for prop in schema.indexes:
            # FalkorDB index syntax
            query = f"CREATE INDEX FOR (n:{schema.label}) ON (n.{prop})"
            queries.append(query)

    return queries


def get_schema_description() -> str:
    """Get a human-readable description of the schema."""
    lines = ["# Knowledge Graph Schema\n"]

    lines.append("## Node Types\n")
    for _node_type, schema in GRAPH_SCHEMA["nodes"].items():
        lines.append(f"### {schema.label}")
        lines.append(f"Properties: {', '.join(schema.properties.keys())}")
        lines.append(f"Indexes: {', '.join(schema.indexes) if schema.indexes else 'none'}")
        lines.append("")

    lines.append("## Relationship Types\n")
    for _rel_type, schema in GRAPH_SCHEMA["relationships"].items():
        lines.append(f"### {schema.type}")
        lines.append(f"From: {', '.join(schema.from_labels)} -> To: {', '.join(schema.to_labels)}")
        if schema.properties:
            lines.append(f"Properties: {', '.join(schema.properties.keys())}")
        lines.append("")

    return "\n".join(lines)
