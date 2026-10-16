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

Phases map to the build milestones in [plan 06 Section 7](06-demo-build.md#7-build-order-and-acceptance-checks).

1. Confirm scope, resource boundaries, workload assumptions and USD 80 cumulative budget. Apply the budget root and run the account preflight.
2. Build and test locally (M0–M4): shared library, order worker, both services, events and storefront, with `pytest` and `moto`. No cloud spend.
3. Write Terraform (M5) and run the first cloud smoke run (M6): identity, VPC/ALB/Fargate, DynamoDB, high-throughput FIFO/DLQ, Scheduler, SNS consumers and CloudFront/S3.
4. Rehearse operational failures and the 60-second checkout burst (M7): 500 accepted orders/second, p95 acknowledgement <=200 ms, no duplicate commits/oversells, drain within five minutes. Use at least 1,000 customer groups. Record notification outcomes, received DLQ alarm, traces, test results and costs. See plans [02](02-architecture.md) and [04](04-operations.md).
5. Dress rehearsal (M8) and final presentation per [plan 07](07-presentation-report.md); write the final report from the evidence; destroy and verify empty state after each run.

## Governance

Commit directly to `main`; use short team check-ins and explicit owners for each run. Operators review the saved Terraform plan before manual apply. Keep deployments to five hours maximum, with full teardown between sessions. Budget USD 8–12/session and USD 32–48 for four sessions/month; reserve USD 20 of the USD 80 total for contingency. Enterprise remote-state governance in proposal Section 6 is design-only; the demo uses local state.
