# 05 — Management & Team Ownership

The [proposal](../proposal.md) governs scope and success criteria.

## 1. Six Engineering Roles & Layer Ownership

Each team member owns a specific architectural layer. Beyond the initial working baseline, each owner is strictly responsible for ensuring their assigned layer functions to course standards, passing tests, and defending their component during the 20-minute presentation and final report.

| Layer & Role | AWS Services Owned | Repository Ownership | Core Ownership Mandate (Definition of Done) |
|---|---|---|---|
| **1. Frontend & Client UX** | CloudFront, S3 Bucket | `storefront/` (`index.html`, `app.js`, `styles.css`), `infra/terraform/modules/edge` | You own the client web store: ensure product browsing, cart updates, checkout, countdown timer, and simulated pay buttons render cleanly, respond without errors, and integrate smoothly with Cognito and backend APIs. |
| **2. API & Core Ingress Services** | Application Load Balancer (ALB), ECS Fargate, ECR | `services/catalog_cart/`, `services/checkout/`, `infra/terraform/modules/compute`, `modules/registry` | You own the FastAPI containerized services: ensure public API endpoints for catalog, cart merge, and checkout return low-latency responses (HTTP 202 in <200ms) and scale reliably under high concurrency. |
| **3. Asynchronous Worker & Messaging** | SQS FIFO Queue, DLQ, EventBridge Scheduler, Lambda (`order_worker`, `outbox_relay`), SNS | `functions/order_worker/`, `functions/outbox_relay/`, `functions/notify_*`, `infra/terraform/modules/queues`, `modules/events`, `modules/functions` | You own background event processing: ensure orders in SQS FIFO are consumed atomically by Lambda, 15-minute order expirations fire reliably via EventBridge Scheduler, and domain events fan out to SNS. |
| **4. Database & Concurrency Architect** | DynamoDB (Single-Table, GSI1, Streams, TTL, PITR) | `shared/python/chopee/keys.py`, `models.py`, `infra/terraform/modules/data`, `scripts/seed_catalog.py`, `scripts/reconcile.py` | You own data persistence and mutexes: ensure single-table schema integrity, guarantee stock reservation never oversells via conditional transactions, and verify zero discrepancies with `reconcile.py`. |
| **5. Security, Identity & Compliance** | Cognito User Pool (Lite), IAM Roles & Policies, SSM Parameter Store, CloudTrail | `shared/python/chopee/auth.py`, `signing.py`, `infra/terraform/modules/identity`, `scripts/sim_gateway.py` | You own platform security and authentication: ensure Cognito sign-up/login works, payment webhook HMAC signatures reject tampering with HTTP 401, IAM enforces least-privilege, and architecture satisfies Singapore PDPA. |
| **6. Reliability, SRE & Chaos Lead** | CloudWatch (Dashboard, Alarms, Logs Insights), X-Ray, AWS Budgets | `infra/terraform/modules/observe`, `loadtest/`, `tests/`, `scripts/smoke.py`, `inject_poison.py`, `stop_checkout_task.sh`, `verify_empty.sh` | You own platform observability, testing, and cloud governance: ensure unit tests pass in `pytest`, drive the 500 orders/s k6 burst, maintain the CloudWatch dashboard, prove DLQ alarming, verify teardown, and document incurred costs. Cleanup does not erase existing charges. |

---

## 2. Documented Technical Gaps by Ownership Layer

The baseline prototype is functional, but each owner should close the following identified gaps within their layer:

- **Frontend & Client UX (Owner 1):**
  - Expose numerical inventory remaining for hot items (e.g. `LIMITED-01` counting down from 50) rather than only a boolean "Sold Out" badge.
  - Disable `#btn-checkout` during request flight to prevent duplicate submission clicks.
  - Replace serial client-side cart clearing loop with parallel requests (`Promise.all`).
  - Clear polling intervals properly inside `signOut()`.
  - Add `cache_control = "no-cache, no-store, must-revalidate"` to `aws_s3_object.config` in `modules/edge`.
- **API & Core Ingress Services (Owner 2):**
  - Add `ConsistentRead=True` to `get_order()` in `services/checkout/app.py` to prevent eventual consistency misses when webhooks arrive immediately.
  - Monitor Fargate task spin-up latency and tune target-tracking CPU scaling thresholds (60%).
  - Ensure Docker container builds cleanly on ARM64 Graviton targets via `scripts/push_images.sh`.
- **Asynchronous Worker & Messaging (Owner 3):**
  - Ensure `models.validate_lines()` raises `models.InvalidMessage` so malformed payloads emit explicit `"poison_message"` structured logs.
  - Verify Powertools `SqsFifoPartialProcessor` correctly pauses FIFO batch consumption upon failure without stalling unrelated customer groups.
  - Safeguard the regional Singapore Lambda concurrency cap of 10 by validating `worker_max_concurrency = 7`.
- **Database & Concurrency Architect (Owner 4):**
  - Audit DynamoDB `TransactWriteItems` condition expressions to guarantee mathematical inventory conservation.
  - Maintain single-table GSI1 indexing and automatic TTL cleanup rules (guest carts after 24h, events after 1 day).
  - Run `scripts/reconcile.py` after heavy load tests to mathematically prove zero overselling, zero duplicate orders, and non-negative stock.
- **Security, Identity & Compliance (Owner 5):**
  - Verify Cognito Lite tier token expiration (3-hour token lifetime for load tests) and cached RS256 JWKS validation.
  - Verify HMAC-SHA256 signature verification in `sim_gateway.py` enforces a strict 300-second timestamp drift limit.
  - Conduct a Singapore PDPA audit ensuring all logs mask customer identities via `customerRef` (HMAC salt).
  - Document PCI-DSS SAQ A scope boundary reduction achieved by redirecting/simulating card payments.
- **Reliability, SRE & Chaos Lead (Owner 6):**
  - Verify the Python 3.12 virtual environment (`requirements-dev.txt`) and current `pytest` suite; the 2026-10-31 local baseline is 169 passing tests; the 2026-10-26 baseline was 113, rising to 124 after SRE-1. These are local tests, not AWS proof.
  - Maintain the 8-widget CloudWatch dashboard (including order outcomes and notification/DLQ) and 13 alarm resource definitions (19 alarm instances with the five configured Lambda functions).
  - Run `scripts/inject_poison.py` to trigger the DLQ alarm email and `scripts/stop_checkout_task.sh` to prove ECS task auto-recovery.
  - Local contributions implemented and locally tested (live verification pending): SRE-1's bounded Scheduler-group wait; SRE-2's exact cleanup targets and missing-state-directory failure; SRE-5's observability widgets and HCL regression tests; SRE-6's checkout/worker X-Ray instrumentation; SRE-7's verified ECS task replacement. See [plan 04's SRE contribution queue](04-operations.md#sre-contribution-queue--local-audit-2026-10-26) for the exact files, acceptance checks and remaining tasks.
  - Live tests, fault injection, load generation and teardown require explicit approval and coordination with the deployment operator and their authoritative state. Saved evidence and a zero script exit status do not replace the live/manual acceptance checks.

---

## 3. Delivery Phases & Governance

Phases map to build milestones in [plan 06 Section 7](06-demo-build.md#7-build-order-and-acceptance-checks).

1. **Phase 1: Baseline Verification & Environment Setup:** Each owner clones the repo, activates a virtualenv, and verifies their module on `main` (no developer branches; `AGENTS.md` governs).
2. **Phase 2: Local Quality Gates (M0–M4):** Owners implement gap closures and verify with `pytest` locally. No cloud spend.
3. **Phase 3: Ephemeral Smoke Deployment (M5–M6):** Coordinated 5-hour deployment to test end-to-end integration across all 6 layers, followed by `terraform destroy` and `verify_empty.sh`.
4. **Phase 4: Load & Chaos Burst Run (M7):** Execute the 500 TPS k6 load test, task termination chaos, poison message DLQ verification, and table reconciliation.
5. **Phase 5: Dress Rehearsal & Deliverables (M8):** 20-minute scripted presentation dry run, video recording capture, and final report compilation per [plan 07](07-presentation-report.md).

Commit directly to `main`, without feature branches or pull requests; maintain deployments strictly within 5 hours and below the USD 80 cumulative cap.
