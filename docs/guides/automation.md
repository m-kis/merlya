# Automation

Automate infrastructure tasks with Merlya's scripting and scheduling capabilities.

## Non-Interactive Mode

Run Merlya commands without interactive prompts:

```bash
# Single command
merlya run "Check disk space on all web servers"

# From file
merlya run --file tasks.txt

# With confirmation disabled (use with caution)
merlya run --yes "Restart nginx on web-01"
```

## Task Files

Create reusable task files:

```yaml
# tasks/daily-checks.yml
name: Daily Infrastructure Checks
tasks:
  - description: Check disk space
    prompt: Check disk usage on all servers, warn if above 80%

  - description: Check memory
    prompt: Check memory usage on all servers

  - description: Check services
    prompt: Verify nginx and postgres are running on all servers
```

Run the task file:

```bash
merlya run --file tasks/daily-checks.yml
```

## Cron Integration

Schedule Merlya tasks with cron:

```bash
# Edit crontab
crontab -e

# Daily health check at 6 AM
0 6 * * * /usr/local/bin/merlya run "Run daily health checks" >> /var/log/merlya-daily.log 2>&1

# Hourly disk check
0 * * * * /usr/local/bin/merlya run "Check disk space, alert if above 90%" >> /var/log/merlya-disk.log 2>&1
```

## Webhooks

Trigger Merlya from webhooks:

```bash
#!/bin/bash
# webhook-handler.sh

PAYLOAD=$(cat)
EVENT=$(echo $PAYLOAD | jq -r '.event')

case $EVENT in
  "deploy")
    merlya run "Deploy latest version to staging servers"
    ;;
  "rollback")
    merlya run "Rollback to previous version on staging"
    ;;
  "scale-up")
    merlya run "Start 2 additional web servers"
    ;;
esac
```

## CI/CD Integration

### GitHub Actions

```yaml
name: Deploy with Merlya

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Merlya
        run: pip install merlya

      - name: Configure Merlya
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          merlya config set model.provider openai
          merlya config set model.model gpt-4o-mini

      - name: Deploy
        run: |
          merlya run --yes "Deploy the latest code to production servers"
```

### GitLab CI

```yaml
deploy:
  stage: deploy
  script:
    - pip install merlya
    - export OPENAI_API_KEY="$OPENAI_API_KEY"
    - merlya config set model.provider openai
    - merlya config set model.model gpt-4o-mini
    - merlya run --yes "Deploy version $CI_COMMIT_TAG to production"
  only:
    - tags
```

## Output Formats

Control output format for automation:

```bash
# JSON output (for parsing)
merlya run --format json "List all servers with high CPU"

# Quiet mode (only results)
merlya run --quiet "Check nginx status"

# Verbose mode (full logging)
merlya --verbose run "Deploy to production"
```

### JSON Output Example

```bash
merlya run --format json "Check disk space on web-01"
```

```json
{
  "success": true,
  "total": 1,
  "passed": 1,
  "failed": 0,
  "tasks": [
    {
      "task": "Check disk space on web-01",
      "success": true,
      "message": "…",
      "actions": ["ssh_execute"],
      "data": null,
      "task_type": "agent"
    }
  ]
}
```

## Error Handling

Handle errors in scripts:

```bash
#!/bin/bash
set -e

# Run with error handling
if merlya run --quiet "Check if all services are healthy"; then
    echo "All services healthy"
else
    echo "Service check failed!"
    merlya run "Send alert to ops team about service failures"
    exit 1
fi
```

## Logging

Configure logging for automation:

```bash
# Set console log level (alias: logging.level)
merlya config set logging.console_level debug

# Set file log level
merlya config set logging.file_level debug

# Run with specific log file
MERLYA_LOG_FILE=/tmp/task.log merlya run "Check servers"
```

## Best Practices

1. **Use `--yes` carefully** - Only for well-tested tasks
2. **Log everything** - Keep records of automated actions
3. **Set timeouts** - Prevent hanging tasks
4. **Use JSON output** - For reliable parsing
5. **Test in staging** - Before automating production tasks
6. **Monitor failures** - Set up alerts for failed tasks

## Examples

### Daily Backup Check

```bash
#!/bin/bash
# check-backups.sh

LOG_FILE="/var/log/merlya/backup-check.log"

echo "$(date): Starting backup check" >> $LOG_FILE

RESULT=$(merlya run --format json "Verify all database backups from last 24h exist and are valid")

if echo $RESULT | jq -e '.success' > /dev/null; then
    echo "$(date): Backup check passed" >> $LOG_FILE
else
    echo "$(date): Backup check FAILED" >> $LOG_FILE
    merlya run "Send urgent alert: backup verification failed"
fi
```

### Auto-Scaling

```bash
#!/bin/bash
# auto-scale.sh

CPU=$(merlya run --format json "Get average CPU across web tier" | jq '.cpu_percent')

if (( $(echo "$CPU > 80" | bc -l) )); then
    merlya run --yes "Scale up web tier by 2 instances"
elif (( $(echo "$CPU < 20" | bc -l) )); then
    merlya run --yes "Scale down web tier by 1 instance (keep minimum 2)"
fi
```
