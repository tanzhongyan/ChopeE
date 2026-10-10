# 01 — Scope and Feasibility

The [proposal](../proposal.md) sets scope; target architecture and demo implementation are distinct.

## Context and goals

- 1.5 million MAU: 80% Singapore, with the remaining 20% split evenly across Malaysia, Thailand and Hong Kong. All regional resources and customer data stay in `ap-southeast-1`.
- Resilience: target 99.9% checkout availability, RTO <=15 minutes and RPO <=5 minutes. The 10,000 requests/second ingress estimate yields a 500-orders/second checkout target.
- Data protection: encrypted access and storage, least privilege and auditable operations. Protected seven-year audit retention is an internal enterprise policy.
- Capital efficiency: demand-based services, at most five hours per demo deployment and USD 80 cumulative project spend.

## Demo boundary

Implement CloudFront/S3 storefront delivery, Cognito authentication, catalog/cart access, guest-cart merge, idempotent checkout, high-throughput FIFO/DLQ, atomic stock reservation, simulated payment outcomes/15-minute expiry, logistics/customer logging consumers, CloudWatch, sampled X-Ray and DynamoDB PITR.

Enterprise-only: private VPC connectivity, Redis, Aurora/RDS Proxy, WAF, dedicated KMS keys, protected seven-year retention and live payment/carrier integrations. Demo encryption and deletable audit evidence remain required.

## Feasibility and evidence

Use six engineering roles, manual Terraform and local-first verification. Phase 4 targets 500 accepted orders/second for 60 seconds, p95 acknowledgement <=200 ms, no duplicate orders or overselling, and queue drain within five minutes. This bounded run does not establish production availability, regional outage recovery or enterprise failover performance.

Budget USD 7–10/session, USD 28–40 for four monthly sessions; plan USD 60 of runs plus USD 20 contingency. Estimates assume no free allowances/credits, not continuous monthly deployment. Risks include cold starts, downstream capacity, hot inventory, poison messages and billing delays. Mitigate through quota checks, bounded load, atomic updates, DLQ alarms and immediate teardown. See [architecture](02-architecture.md) and [operations](04-operations.md).
