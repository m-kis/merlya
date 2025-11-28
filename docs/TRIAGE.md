# Athena Triage System

The triage system classifies user requests by **intent** and **priority** to optimize response behavior.

## Overview

```
User Request
     │
     v
┌─────────────────────────────────────────────┐
│           3-Tier Classification             │
│  ┌─────────────────────────────────────┐   │
│  │  1. Smart Classifier (Embeddings)   │   │ ← Semantic similarity
│  │     ↓ fallback                      │   │
│  │  2. AI Classifier (LLM)             │   │ ← Fast LLM (haiku/mini)
│  │     ↓ fallback                      │   │
│  │  3. Signal Detector (Keywords)      │   │ ← Deterministic rules
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
     │
     v
┌─────────────┐  ┌─────────────┐
│   Intent    │  │  Priority   │
│ QUERY/ACTION│  │  P0-P3      │
│ /ANALYSIS   │  │             │
└─────────────┘  └─────────────┘
```

---

## Intent Classification

### Intent Types

| Intent | Description | Behavior |
|--------|-------------|----------|
| `QUERY` | Information request | Read-only, gather data, present clearly |
| `ACTION` | Execute something | Verify, execute, report results |
| `ANALYSIS` | Deep investigation | Investigate, explain, recommend |

### Intent Keywords

**QUERY** (information gathering):
```
French: quels sont, quel est, dis moi, montre moi, liste, affiche, combien
English: what is, which, show me, list, display, how many, where is, tell me
```

**ACTION** (execution):
```
French: vérifie, redémarre, arrête, exécute, lance, installe, supprime
English: check, restart, stop, start, run, install, remove, fix, update
```

**ANALYSIS** (investigation):
```
French: analyse, diagnostique, investigue, pourquoi, problème, panne
English: analyze, diagnose, investigate, troubleshoot, why, debug, root cause
```

---

## Priority Classification

### Priority Levels

| Priority | Name | Response Time | Description |
|----------|------|---------------|-------------|
| **P0** | Critical | Immediate | Production down, data loss, security breach |
| **P1** | High | < 15 min | Service degraded, vulnerability, imminent failure |
| **P2** | Medium | < 1 hour | Performance issues, non-critical failures |
| **P3** | Low | Normal | Routine requests, maintenance, questions |

### P0 Keywords (Critical)
```
Production down: down, outage, unreachable, not responding, site down
Data loss: data loss, corruption, database crash, disk full, backup failed
Security: breach, hacked, compromised, ransomware, unauthorized access
```

### P1 Keywords (High)
```
Degradation: degraded, slow, high latency, timeout, intermittent
Security: vulnerability, CVE, exposed, suspicious activity, brute force
Imminent: disk almost full, memory pressure, OOM, certificate expiring
```

### P2 Keywords (Medium)
```
Performance: optimize, slow query, high cpu, memory usage, bottleneck
Non-critical: backup warning, replica lag, queue growing, cache miss
Capacity: scaling, resources
```

### P3 (Default)
All other requests default to P3.

---

## Environment Amplifiers

Requests mentioning production environments get priority boosts:

| Environment | Multiplier | Minimum Priority |
|-------------|------------|------------------|
| `prod`, `production`, `live` | 1.5x | P1 |
| `staging`, `preprod`, `uat` | 1.0x | P2 |
| `dev`, `development`, `test` | 0.5x | P3 |

---

## Impact Amplifiers

Certain keywords increase priority:

| Pattern | Multiplier |
|---------|------------|
| `all users`, `everyone` | 2.0x |
| `revenue`, `business critical` | 2.0x |
| `customer` | 1.5x |
| `urgent`, `asap` | 1.3-1.5x |
| `internal` | 0.8x |

---

## Classifier Details

### 1. Smart Classifier (Optional)

Uses sentence-transformers for semantic similarity matching.

**Requirements:**
```bash
pip install athena-ai-ops[smart-triage]
# or
pip install sentence-transformers falkordb
```

**Features:**
- Learns from user feedback
- Semantic pattern matching
- Per-user classification history
- FalkorDB storage for patterns

**Usage:**
```python
from athena_ai.triage import get_smart_classifier

classifier = get_smart_classifier(
    db_client=falkordb_client,
    user_id="user123"
)
result = await classifier.classify("mongo is slow on prod")
```

#### Embedding Models

The Smart Classifier uses sentence-transformers for embeddings. Models can be configured via the `/model embedding` command or `ATHENA_EMBEDDING_MODEL` environment variable.

**Available Models:**

| Model | Size | Dims | Speed | Quality | Best For |
|-------|------|------|-------|---------|----------|
| `BAAI/bge-small-en-v1.5` (default) | 45MB | 384 | fast | better | General use, semantic search |
| `BAAI/bge-base-en-v1.5` | 110MB | 768 | medium | best | High accuracy classification |
| `intfloat/e5-small-v2` | 45MB | 384 | fast | better | Multilingual support |
| `intfloat/e5-base-v2` | 110MB | 768 | medium | best | Multilingual high accuracy |
| `thenlper/gte-small` | 45MB | 384 | fast | better | Fast inference |
| `thenlper/gte-base` | 110MB | 768 | medium | best | High accuracy |
| `all-MiniLM-L6-v2` | 22MB | 384 | fast | good | Minimal footprint |
| `paraphrase-MiniLM-L3-v2` | 17MB | 384 | fast | good | Ultra-fast, basic quality |
| `multi-qa-MiniLM-L6-cos-v1` | 22MB | 384 | fast | better | Q&A optimization |
| `all-mpnet-base-v2` | 420MB | 768 | slow | best | Maximum quality |

**Configuration:**

```bash
# Via environment variable (persistent)
export ATHENA_EMBEDDING_MODEL="BAAI/bge-base-en-v1.5"

# Via REPL command (session-only)
/model embedding set BAAI/bge-base-en-v1.5
```

**Commands:**

```bash
/model embedding         # Show current model
/model embedding list    # List all available models
/model embedding set <model>  # Change model
```

**Python API:**

```python
from athena_ai.triage import get_embedding_config, EmbeddingConfig

# Get current model
config = get_embedding_config()
print(config.current_model)  # BAAI/bge-small-en-v1.5

# Change model
config.set_model("all-MiniLM-L6-v2")

# Get model info
info = config.model_info
print(f"Size: {info.size_mb}MB, Dimensions: {info.dimensions}")

# List available models
models = EmbeddingConfig.list_models()
```

---

### 2. AI Classifier

Uses a fast LLM for intelligent classification.

**Features:**
- Uses user's configured LLM router
- In-memory cache (500 entries)
- Keyword fallback when LLM unavailable
- 5-second timeout

**Usage:**
```python
from athena_ai.triage import get_ai_classifier

classifier = get_ai_classifier(llm_router=router)
result = await classifier.classify("check disk space on web-01")

# Result:
# AIClassificationResult(
#     intent=Intent.QUERY,
#     priority=Priority.P3,
#     reasoning="Information request about disk space"
# )
```

---

### 3. Signal Detector (Fallback)

Deterministic keyword-based classification. Always available.

**Features:**
- No external dependencies
- Fast (< 5ms)
- Regex pattern matching
- Environment/impact detection

**Usage:**
```python
from athena_ai.triage import SignalDetector

detector = SignalDetector()

# Detect intent
intent, confidence, signals = detector.detect_intent("list all hosts")
# (Intent.QUERY, 0.85, ["query:list"])

# Detect priority
priority, signals, confidence = detector.detect_keywords("prod is down!")
# (Priority.P0, ["P0:down"], 0.9)

# Detect environment
env, multiplier, min_priority = detector.detect_environment("prod-web-01")
# ("prod", 1.5, Priority.P1)

# Full detection
result = detector.detect_all("production database is slow")
# {
#     "intent": Intent.ANALYSIS,
#     "intent_confidence": 0.8,
#     "keyword_priority": Priority.P1,
#     "environment": "prod",
#     "host": "database",
#     "service": "mongodb"
# }
```

---

## Behavior Profiles

Based on intent, Athena adapts its behavior:

### QUERY Mode
```
- Focus: GATHER and PRESENT information
- Collect requested information efficiently
- Present results clearly and organized
- READ-ONLY: avoid making changes
```

### ACTION Mode
```
- Focus: EXECUTE safely
- Verify targets before acting
- Execute the requested task
- Report results clearly
```

### ANALYSIS Mode
```
- Focus: INVESTIGATE and RECOMMEND
- Dig deep: check logs, configs, status
- EXPLAIN what you find in clear terms
- PROPOSE solutions with example commands
- Ask before executing any fixes
- This is a teaching moment: educate the user
```

---

## Tool Restrictions

Based on priority and intent, tool access may be restricted:

| Priority | Intent | Allowed Tools |
|----------|--------|---------------|
| P0 | Any | All tools (emergency) |
| P1-P3 | QUERY | Read-only tools only |
| P1-P3 | ACTION | All tools |
| P1-P3 | ANALYSIS | Read + analysis tools |

---

## Error Analysis

The triage system also includes error classification:

```python
from athena_ai.triage import get_error_analyzer

analyzer = get_error_analyzer()
result = analyzer.analyze("Permission denied: /etc/nginx/nginx.conf")

# ErrorAnalysis(
#     error_type=ErrorType.PERMISSION,
#     confidence=0.95,
#     suggestion="Use sudo or request elevation"
# )
```

### Error Types

| Type | Examples |
|------|----------|
| `PERMISSION` | Permission denied, Access denied |
| `CONNECTION` | Connection refused, timeout, unreachable |
| `NOT_FOUND` | File not found, command not found |
| `RESOURCE` | Out of memory, disk full |
| `CONFIGURATION` | Invalid config, syntax error |
| `AUTHENTICATION` | Auth failed, invalid credentials |

---

## API Reference

### Classes

```python
# Priority and Intent enums
from athena_ai.triage import Priority, Intent

Priority.P0  # Critical
Priority.P1  # High
Priority.P2  # Medium
Priority.P3  # Low

Intent.QUERY     # Information request
Intent.ACTION    # Execution request
Intent.ANALYSIS  # Investigation request
```

### Factory Functions

```python
from athena_ai.triage import (
    # Classifiers
    get_smart_classifier,    # Semantic (requires extras)
    get_ai_classifier,       # LLM-based
    get_classifier,          # Deterministic

    # Utilities
    classify_priority,       # Quick classification
    get_error_analyzer,      # Error classification
    get_behavior,            # Get behavior profile
    describe_behavior,       # Human-readable behavior

    # Reset
    reset_smart_classifier,  # Clear classifier cache
)
```

### Results

```python
# Priority classification result
PriorityResult(
    priority=Priority.P1,
    signals=["P1:degraded", "env:prod"],
    confidence=0.85,
    environment="prod"
)

# Full triage result
TriageResult(
    priority_result=PriorityResult(...),
    intent=Intent.ANALYSIS,
    intent_confidence=0.9,
    allowed_tools=["scan_host", "tail_logs", "read_remote_file"],
    behavior=BehaviorProfile(...)
)
```

---

## Configuration

### LLM Router Integration

The AI classifier uses the user's configured LLM router:

```python
from athena_ai.llm import LLMRouter

router = LLMRouter(
    model="haiku",  # Use fast model for triage
    timeout=5.0
)

classifier = get_ai_classifier(llm_router=router)
```

### Smart Classifier Setup

```python
from falkordb import FalkorDB
from athena_ai.triage import get_smart_classifier

# Connect to FalkorDB
db = FalkorDB(host="localhost", port=6379)
client = db.select_graph("athena_triage")

# Create classifier
classifier = get_smart_classifier(
    db_client=client,
    user_id="user123"
)

# Learn from feedback
await classifier.learn(
    query="mongo is slow",
    intent=Intent.ANALYSIS,
    priority=Priority.P1,
    feedback_score=1.0
)
```

---

## Embedding Models

The Smart Classifier and Tool Selector use sentence-transformers for semantic similarity matching.

### Available Embedding Models

| Model | Size | Dims | Speed | Quality | Description |
|-------|------|------|-------|---------|-------------|
| `BAAI/bge-small-en-v1.5` | 45MB | 384 | fast | better | **Default** - SOTA 2024, excellent for semantic search |
| `BAAI/bge-base-en-v1.5` | 110MB | 768 | medium | best | Top MTEB performer, best quality/size |
| `intfloat/e5-small-v2` | 45MB | 384 | fast | better | Fast multilingual, good for classification |
| `intfloat/e5-base-v2` | 110MB | 768 | medium | best | Strong multilingual support |
| `thenlper/gte-small` | 45MB | 384 | fast | better | Competitive with BGE |
| `thenlper/gte-base` | 110MB | 768 | medium | best | Top MTEB performer |
| `all-MiniLM-L6-v2` | 22MB | 384 | fast | good | Proven classic, 5x faster than BERT |
| `paraphrase-MiniLM-L3-v2` | 17MB | 384 | fast | good | Smallest, ultra-fast |
| `multi-qa-MiniLM-L6-cos-v1` | 22MB | 384 | fast | better | Optimized for Q&A |
| `all-mpnet-base-v2` | 420MB | 768 | slow | best | Highest quality legacy |

### Embedding Model Configuration

**Via Environment Variable (persistent):**

```bash
export ATHENA_EMBEDDING_MODEL="BAAI/bge-small-en-v1.5"
```

**Via Command (runtime):**

```bash
/model embedding list       # Show all available models
/model embedding            # Show current model
/model embedding set <name> # Change model
```

**Via Code:**

```python
from athena_ai.triage.embedding_config import get_embedding_config

config = get_embedding_config()
config.set_model("BAAI/bge-base-en-v1.5")  # Higher quality
```

### Embedding Model Selection Guide

| Use Case | Recommended Model |
|----------|-------------------|
| Fast CLI response | `paraphrase-MiniLM-L3-v2` (17MB) |
| Balanced (default) | `BAAI/bge-small-en-v1.5` (45MB) |
| Best quality | `BAAI/bge-base-en-v1.5` (110MB) |
| Multilingual | `intfloat/e5-base-v2` (110MB) |
| Limited resources | `all-MiniLM-L6-v2` (22MB) |

---

## See Also

- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [TOOLS.md](TOOLS.md) - Available tools
- [TESTING.md](TESTING.md) - Testing the triage system
