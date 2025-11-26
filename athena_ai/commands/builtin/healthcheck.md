---
name: healthcheck
description: Comprehensive health check of a host
aliases: [hc, health]
---

# Health Check for {{$1}}

Perform a comprehensive health check on {{$1}}:

## System Resources
- Check CPU usage and load average
- Check memory usage (free -h)
- Check disk space (df -h)
- Check swap usage

## Services
- List all running services
- Check for failed systemd units
- Verify critical services are running

## Network
- Check network connectivity
- List open ports (ss -tuln)
- Check DNS resolution

## Logs
- Check for recent errors in syslog
- Look for OOM killer events
- Check for disk I/O errors

Provide a summary with:
- Overall health status (healthy/degraded/critical)
- List of issues found
- Recommended actions
