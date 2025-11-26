---
name: incident
description: Start incident response workflow for a host
aliases: [inc, ir]
---

# Incident Response for {{$1}}

You are starting an incident response workflow. Follow these steps carefully:

## 1. Initial Assessment
- Check if {{$1}} is responding (ping, SSH)
- Get current system status (uptime, load)
- Check disk space and memory

## 2. Gather Information
- Collect last 100 lines of system logs
- Check for recent service restarts
- Look for error patterns

## 3. Diagnose
- Identify the root cause based on gathered data
- Check if this is a known issue

## 4. Mitigate
- Suggest immediate actions to restore service
- Prioritize based on impact

## 5. Report
- Provide a clear summary of findings
- Include timeline of events

Priority Level: {{$2|P2}}
