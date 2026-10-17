# 01 — Scope and Feasibility

The [proposal](../proposal.md) sets scope; target architecture and demo implementation are distinct.

## Context and goals

- 1.5 million MAU: 80% Singapore, with the remaining 20% split evenly across Malaysia, Thailand and Hong Kong. All regional resources and customer data stay in `ap-southeast-1`.
- Resilience: target 99.9% checkout availability, RTO <=15 minutes and RPO <=5 minutes. The 10,000 requests/second ingress estimate yields a 500-orders/second checkout target.
- Data protection: encrypted access and storage, least privilege and auditable operations. Protected seven-year audit retention is an internal enterprise policy.
- Capital efficiency: demand-based services, at most five hours per demo deployment and USD 80 cumulative project spend.

## Demo boundary

Implement CloudFront/S3 storefront delivery, Cognito authentication, an ALB with two Fargate services (catalog/cart and checkout/webhook), guest-cart merge, idempotent checkout, high-throughput FIFO/DLQ with one worker Lambda, atomic stock reservation, simulated payment outcomes/15-minute expiry, logistics/customer logging consumers, CloudWatch, sampled X-Ray, one scheduled report to S3 and DynamoDB PITR.

Enterprise-only: WAF, Route 53, ACM on the ALB, private subnets/NAT, three AZs, Redis, Aurora/RDS Proxy, dedicated KMS keys, Macie, Firehose log delivery, Glue/Athena/QuickSight, protected seven-year retention, sharded stock counters, remote Terraform state and live payment/carrier integrations. Demo encryption and deletable audit evidence remain required.

The demo reuses open-source code instead of building a shop: storefront screens and cart-merge logic from AWS's MIT-0 serverless shopping cart sample, Powertools for Lambda, and k6. Exactly what to build, and what not to, is fixed in [plan 06](06-demo-build.md); how it is presented and evidenced is in [plan 07](07-presentation-report.md).

## Feasibility and evidence

Use six engineering roles, manual Terraform and local-first verification. Phase 4 targets 500 accepted orders/second for 60 seconds, p95 acknowledgement <=200 ms, no duplicate orders or overselling, and queue drain within five minutes. This bounded run does not establish production availability, regional outage recovery or enterprise failover performance.

Budget USD 8–12/session, USD 32–48 for four monthly sessions; plan USD 60 of runs plus USD 20 contingency. Estimates assume no free allowances/credits, not continuous monthly deployment. Risks include slow Fargate scale-out, ALB warm-up, Cognito sign-in quotas, reduced Lambda concurrency and Fargate vCPU quotas on new accounts, CloudFront account verification, the Cognito tier defaulting to Essentials, downstream capacity, hot inventory, poison messages and billing delays. Mitigate through the account preflight in [plan 06](06-demo-build.md#72-account-preflight-once-at-least-a-week-before-m6), scheduled pre-scaling, pre-minted test-user tokens, bounded load spread across SKUs (sharded counters in the target), atomic updates, DLQ alarms, budget alerts and immediate teardown. See [architecture](02-architecture.md) and [operations](04-operations.md).
