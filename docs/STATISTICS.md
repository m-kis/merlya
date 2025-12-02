# Statistics and Metrics

Merlya includes a comprehensive statistics system for tracking performance, usage, and debugging.

## Quick Start

Use the `/stats` command to view statistics:

```bash
/stats              # Dashboard summary
/stats llm          # LLM call statistics
/stats queries      # Query execution statistics
/stats actions      # Command execution statistics
/stats embeddings   # Embedding generation statistics
/stats agents       # Agent task statistics
/stats session      # Current session statistics
/stats cleanup [days]  # Clean up old metrics
```

## Dashboard

The dashboard provides a comprehensive overview:

```
📊 Merlya Statistics Dashboard
Period: Last 24 hours | Generated: 2024-12-01T15:30:00

Summary:
┌─────────────┬───────┬──────────────┬──────────┐
│ Metric      │ Count │ Success Rate │ Avg Time │
├─────────────┼───────┼──────────────┼──────────┤
│ LLM Calls   │   42  │    98.5%     │  1.2s    │
│ Queries     │   15  │   100.0%     │  3.5s    │
│ Actions     │   28  │    96.4%     │  250ms   │
│ Embeddings  │   89  │   100.0%     │   45ms   │
│ Agent Tasks │    8  │    87.5%     │  8.2s    │
└─────────────┴───────┴──────────────┴──────────┘

Quick Stats:
  Total tokens used: 125,420
  Query p50/p95/p99: 2.1s / 5.3s / 8.7s
  Total actions executed: 28
```

## Metrics Tracked

### LLM Calls

- Provider and model used
- Token counts (prompt, completion, total)
- Response time in milliseconds
- Success/failure status
- Task type (synthesis, planning, correction)

### Queries

- Total processing time
- LLM time vs tool execution time
- Actions triggered per query
- Success rate
- Percentiles (p50, p95, p99)

### Actions

- Target (localhost or remote host)
- Command type (local, remote)
- Duration in milliseconds
- Exit code
- Risk level

### Embeddings

- Model used
- Input token count
- Dimensions
- Batch size
- Purpose (triage, search, similarity)

### Agent Tasks

- Agent name
- Task type
- Duration
- Steps count
- Tools used
- LLM calls made

## Data Storage

Metrics are stored in SQLite at `~/.merlya/metrics.db` with automatic:
- Index creation for fast queries
- Cleanup of old data (configurable retention)
- Thread-safe access

### Tables

| Table | Purpose |
|-------|---------|
| `llm_calls` | LLM API call metrics |
| `query_metrics` | User query processing |
| `action_metrics` | Command execution |
| `embedding_metrics` | Embedding generation |
| `agent_task_metrics` | Agent task execution |
| `performance_baselines` | Historical aggregates |

## API for Custom Integration

### Python API

```python
from merlya.utils.stats_manager import get_stats_manager

stats = get_stats_manager()

# Context manager for automatic timing
with stats.time_llm_call("openrouter", "gpt-4") as timer:
    response = llm.generate(prompt)
    timer.set_tokens(100, 50)

# Manual timing
timer = stats.start_timer()
result = execute_action()
stats.record_action("localhost", "local", timer.elapsed_ms(), 0, True, "low")

# Get statistics
dashboard = stats.get_dashboard(hours=24)
llm_stats = stats.get_llm_stats(hours=1)
```

### Available Context Managers

```python
# LLM calls
with stats.time_llm_call(provider, model, task_type=None) as timer:
    timer.set_tokens(prompt_tokens, completion_tokens)

# Embeddings
with stats.time_embedding(model, purpose=None) as ctx:
    ctx.set_metadata(input_tokens=50, dimensions=384, batch_size=1)

# Agent tasks
with stats.time_agent_task(agent_name, task_type) as ctx:
    ctx.add_step()
    ctx.add_tool("shell")
    ctx.add_llm_call()
```

## Performance Baselines

Calculate and store historical performance data:

```python
# Calculate daily baseline for queries
stats.calculate_baselines("query", period="daily")

# Get stored baselines
baselines = stats.get_baselines(metric_type="llm", period="hourly", limit=10)
```

Supported periods:
- `hourly` - Hourly aggregates
- `daily` - Daily aggregates
- `weekly` - Weekly aggregates

## Cleanup

Remove old metrics to manage database size:

```python
# Remove metrics older than 30 days
deleted = stats.cleanup(days=30)
```

Or via command:
```bash
/stats cleanup 30  # Remove metrics older than 30 days
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MERLYA_METRICS_DB` | Custom metrics database path | `~/.merlya/metrics.db` |
| `MERLYA_METRICS_RETENTION` | Days to retain metrics | 30 |

## Best Practices

1. **Regular Cleanup**: Run `/stats cleanup` periodically to manage database size
2. **Monitor Percentiles**: p95 and p99 times help identify slow queries
3. **Track Success Rates**: Low success rates indicate issues to investigate
4. **Use Session Stats**: Compare session performance over time
5. **Calculate Baselines**: Establish normal performance patterns

## Troubleshooting

### No Statistics Showing

1. Ensure the database file exists: `ls ~/.merlya/metrics.db`
2. Check permissions on the database file
3. Try a broader time range: `/stats llm 168` (7 days)

### High Response Times

1. Check LLM provider latency: `/stats llm`
2. Review action execution times: `/stats actions`
3. Look for slow queries: Check p95/p99 percentiles

### Database Growing Large

1. Run cleanup: `/stats cleanup 7` (keep only last 7 days)
2. Reduce retention in config
3. Consider exporting important data before cleanup
