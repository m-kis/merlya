# Tracked Tickets

This file tracks larger, multi-provider features that are intentionally not
implemented yet. Code should link to these IDs via `TODO(<ID>): ...` comments.

## PROV-AWS-001

Add EC2/EBS snapshot support in `AWSProvider`.

- Desired surface area: create/list/delete snapshots for instances and/or EBS volumes.
- Backends: SDK (`boto3`), Terraform resources, and MCP hooks.

## PROV-AWS-002

Add S3 object storage support in `AWSProvider`.

- Desired surface area: list/create/delete buckets, put/get/delete objects.
- Backends: SDK (`boto3`), Terraform resources, and MCP hooks.

## PROV-AWS-003

Add Auto Scaling Groups support in `AWSProvider`.

- Desired surface area: create/list/update/scale/delete ASGs.
- Backends: SDK, Terraform, and MCP hooks.

## PROV-AWS-004

Add load balancing support in `AWSProvider` (ELB/ALB/NLB).

- Desired surface area: create/list/update/delete load balancers and target groups.
- Backends: SDK, Terraform, and MCP hooks.

## PROV-AWS-005

Add DNS record management in `AWSProvider` (Route 53).

- Desired surface area: create/list/update/delete DNS records and zones.
- Backends: SDK, Terraform, and MCP hooks.

