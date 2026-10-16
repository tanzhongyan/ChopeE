# 07 — Final Presentation, Evidence and Report

This plan turns the [course specification](../project_specifications.md) into what the team shows and writes. It covers the Final Presentation & Demo (8%, 20 minutes) and the Final Report (15%, 5–30 pages). The demo it relies on is specified in [plan 06](06-demo-build.md).

## 1. Rubric traceability

Every rubric line needs a design answer, a live or recorded proof, and a report section. Tier 1 additionally needs all five Well-Architected pillars ([proposal Appendix E](../proposal.md#e-well-architected-pillar-mapping)).

| Criterion | Design answer (proposal) | Demo proof | Report section |
|---|---|---|---|
| 1 Feasibility | §1 goals (max 3), §2 use cases, Appendix A–C requirements and sizing | Storefront flow end to end; requirement → demo coverage table | 1, 2 |
| 2 Resource allocation & justification | §3.1 per-tier justification; §3.2 demo reductions with cost table; plan 02 capacity check | Terraform plan summary; Fargate/Lambda sizing shown on dashboard | 3 |
| 3 Resource linkage & message flow | §2.2 checkout → FIFO → worker → outbox → SNS; Scheduler expiry; scheduled report | One order traced from 202 through `PAID` to both consumers (X-Ray + logs); expiry; report file in S3 | 4 |
| 4 Overall design & implementation | Three tiers, two services, one worker; reuse decisions (plan 06 §2) | Live storefront, idempotent retry, DLQ isolation | 4, 5 |
| 5 Monitoring, observability & alerts | §5 alarms and KPIs; plan 04 thresholds | Dashboard during the burst; DLQ alarm email arrives; trace map | 6 |
| 6 Scalability, reliability & availability | §4 DR (RTO/RPO), Multi-AZ, auto-scaling, DLQ, circuit breaking | 500 orders/s burst; checkout tasks scale; one task stopped while traffic continues; PITR enabled | 7 |
| 7 Cloud management & governance | §6 IaC, roles, cost; Appendix D PDPA | `terraform plan/apply/destroy`; budget alerts; tags; empty-state check; cost record | 8, 9 |

Metrics checklist from specification Section 5, and where each is answered: SLAs/KPIs (proposal §5), TCO and CAPEX vs OPEX (report §9, method below), ingress/egress (report §9), PDPA/PCI DSS/audit retention (Appendix D, §2.1), RTO/RPO (§4), compute and triggers (§3.1, plan 02), VPC/route tables/NACLs/security groups/API entry (plan 02, plan 06 §6.2), data lifecycle tiers (proposal §3.4), Multi-AZ/DLQ/circuit breaking (§3.1, §4).

## 2. Twenty-minute presentation script

The stack is deployed and smoke-tested at least 60 minutes before the slot (CloudFront creation and alarm email confirmation take time). A full screen recording from the M8 dress rehearsal is the fallback for any live step that fails; switch to it without debugging on stage.

| Time | Segment | Content | Live action |
|---|---|---|---|
| 0:00–2:00 | Context | ChopeE, users, three business goals, flash-sale problem | **Place an order and leave it unpaid** (15-minute expiry timer starts) |
| 2:00–5:00 | Target architecture | Figure 1 by tier; why Fargate + FIFO + DynamoDB + Aurora; RTO/RPO; PDPA | – |
| 5:00–7:00 | Demo scope | Figure 2; reduction table; reuse decisions; cost per run | – |
| 7:00–12:00 | Functional demo | Guest cart → sign in → merge; checkout 202 → `PENDING_PAYMENT` → pay → `PAID`; replay the same key (200, one order); decline releases stock; `sim_gateway.py --bad-signature` → 401; consumer logs for both subscribers | Storefront + CloudWatch Logs Insights |
| 12:00–15:00 | Scale | Start k6 burst (2 minutes total); show dashboard: accepted rate, ALB p95, task count, queue age draining; stop one checkout task mid-burst and show ALB/ECS replace it | k6 + dashboard |
| 15:00–17:00 | Failure handling | `inject_poison.py` → DLQ → alarm email on screen; other customers' orders continue; show X-Ray trace of one order; show the order from 0:00 now `CANCELLED/PAYMENT_TIMEOUT` with stock restored | Email + console |
| 17:00–19:00 | Governance & cost | Terraform modules, tags, budget alerts, five-hour lifecycle, cost per run vs actual bill, PDPA controls, Well-Architected summary | – |
| 19:00–20:00 | Close | Results vs targets (including any missed), what the enterprise build adds | – |

Rehearse the poison-message step early in the session if alarm delivery is slow; alarms evaluate one-minute periods, so expect the email in roughly 1–3 minutes.

## 3. Evidence checklist (capture during M7/M8 and the final run)

- k6 summary JSON and the dashboard screenshot covering ramp, hold and drain.
- ALB `TargetResponseTime` p95 and `RequestCount` for the hold window; `HTTPCode_Target_5XX_Count`.
- `reconcile.py` output: accepted vs terminal counts, duplicates = 0, minimum stock ≥ 0.
- Contention test on `LIMITED-01` (more buyers than stock): exactly 50 reserved, the rest `REJECTED`.
- One X-Ray trace (checkout → SQS → worker) and correlated log lines by `orderId`.
- DLQ alarm email with timestamps (breach time vs received time, for the MTTD KPI).
- ECS events showing a stopped task replaced; ECS deployment circuit breaker setting.
- Consumer log lines for `OrderPaid` (logistics) and status events (customer), including one `duplicate_ignored`.
- Report object in the reports bucket.
- `terraform plan` resource count, `terraform destroy` output and `verify_empty.sh` output.
- Cost Explorer daily cost for each run day, filtered by tag `Project=chopee` where available, against the USD 8–12 estimate and the USD 80 cap.

Screenshots are binaries: keep them in the report or a shared drive, never under `docs/`.

## 4. Final report outline (target 20–25 pages)

1. **Executive summary** — goals, what was built, headline results vs targets (1 page).
2. **Business context and requirements** — users, three goals, use cases, BR/FR/NFR tables, sizing (proposal §1–2, Appendix A–C).
3. **Target architecture and resource justification** — Figure 1; per-tier service choice and the alternatives rejected (API Gateway vs ALB, Lambda vs Fargate for the API, standard vs FIFO SQS, DynamoDB vs Aurora per data type).
4. **Message flow and linkages** — sequence of checkout, payment, expiry and notification; idempotency and ordering argument; outbox.
5. **Demo implementation** — Figure 2; reduction table; open-source reuse; what was custom-built.
6. **Monitoring, observability and alerting** — dashboard, alarm table, KPIs (MTTD, MTTR), tracing, logs, audit.
7. **Scalability, reliability and DR** — capacity check, load-test results (pass/miss), task-failure test, DLQ isolation, RTO/RPO strategy and what the demo did and did not prove.
8. **Security and compliance** — network controls (SGs, prefix list, NACLs in target), IAM least privilege, encryption, PDPA mapping (Appendix D), PCI DSS scope reduction via hosted payments.
9. **Cost and governance** — demo cost estimate vs actual; enterprise monthly estimate (below); CAPEX vs OPEX; data transfer; Terraform workflow; tagging; budgets; team roles.
10. **Well-Architected review** — pillar table (Appendix E) with the honest gaps.
11. **Limitations and next steps** — deviations listed in plan 06 §6.2, sharded stock, Aurora reconciliation, real gateway.

**Enterprise monthly cost (TCO) method.** Build an AWS Pricing Calculator estimate for `ap-southeast-1`: baseline month at 100 req/s average with four flash-sale days (one hour at 10,000 req/s each), Fargate at minimum 6 tasks scaling to 65, Aurora Serverless v2 writer + reader at 0.5–16 ACU, Redis two small nodes, DynamoDB on-demand from the order volume in Appendix C, NAT per AZ, WAF, CloudFront egress for the storefront, and log archive growth. Export the calculator link into the report. Contrast with an always-on peak-sized fleet to show the OPEX/scale-to-zero argument. Do not quote numbers that were not produced by the calculator or a bill.

## 5. Likely questions to prepare

- Why ALB + Fargate instead of API Gateway + Lambda for the API? (No 15-minute limit, steady per-request cost at 10,000 req/s, connection reuse; Lambda kept for event-driven work.)
- Why one FIFO queue for three message types? (Per-customer ordering of order → payment → expiry; plan 02.)
- How does a 202 become a failure the customer sees? (Order status and `OrderRejected` event; plan 03.)
- What stops overselling at 500 orders/s on one hot SKU? (Conditional writes; sharded counters in the target; the demo spreads load and tests contention separately.)
- What happens if an AZ fails? (Two-AZ ALB/Fargate in the demo, three in the target; regional managed services; RTO/RPO table.)
- How is the ALB protected without WAF? (CloudFront-only prefix list, secret origin header, JWT and HMAC checks; WAF in the target.)
- Is card data in scope for PCI? (Hosted payment page and webhooks keep card data out; scope reduction, not compliance by itself.)
- How do you know teardown worked and spend is controlled? (`verify_empty.sh`, tags, budget alerts, cost record.)
