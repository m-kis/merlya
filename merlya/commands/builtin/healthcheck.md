---
name: healthcheck
description: Comprehensive health check of a host
aliases: [hc, health]
---

# Health Check for {{$1|<HOST_REQUIRED>}}

**IMPORTANT**: If the host is not specified (shows "<HOST_REQUIRED>"), use `ask_user` to ask which host to check, then CONTINUE with the health check using that host. Do NOT terminate after getting the host name - proceed with the full health check.

Perform a comprehensive health check on {{$1|the specified host}}:

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
