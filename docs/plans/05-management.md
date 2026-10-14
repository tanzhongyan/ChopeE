# 05 — Management

The [proposal](../proposal.md) governs scope and success criteria.

## Six engineering roles

| Role | Delivery responsibility |
|---|---|
| Cloud solutions architect | Target/demo tiering, scope boundaries and presentation |
| IaC engineer | Manual Terraform, demo local state, deployment and complete teardown |
| Security/compliance specialist | IAM, encryption, audit evidence; enterprise WAF/KMS/private-network designs |
| Backend developer | Fargate services, Lambda worker, authentication integration, catalog/cart merge, checkout and simulated payments |
| Data architect | DynamoDB model, atomic stock/idempotency/ledger transitions; enterprise Aurora design |
| Observability/SRE engineer | Alarms, traces, notification evidence, load tests and cost records |

## Delivery phases

1. Confirm scope, resource boundaries, workload assumptions and USD 80 cumulative budget.
2. Provision core identity, VPC/ALB/Fargate, DynamoDB, high-throughput FIFO/DLQ and CloudFront/S3 through manual Terraform.
3. Implement cart merge, order/payment state transitions, expiry, event relay and both SNS logging consumers; verify locally.
4. Rehearse operational failures and the 60-second checkout burst: 500 accepted orders/second, p95 acknowledgement <=200 ms, no duplicate commits/oversells, drain within five minutes. Use at least 1,000 customer groups. Record notification outcomes, received DLQ alarm, traces, test results and costs. See plans [02](02-architecture.md) and [04](04-operations.md).
5. Prepare target/demo figures, scope/cost explanation and presentation; rehearse the timed demo, then destroy and verify empty state.

## Governance

Commit directly to `main`; use short team check-ins and explicit owners for each run. Operators review the saved Terraform plan before manual apply. Keep deployments to five hours maximum, with full teardown between sessions. Budget USD 8–12/session and USD 32–48 for four sessions/month; reserve USD 20 of the USD 80 total for contingency. Enterprise remote-state governance in proposal Section 6 is design-only; the demo uses local state.
