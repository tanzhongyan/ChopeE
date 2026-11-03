# Owner 2 — API & core ingress hardening

Implementation plan for the Owner 2 checklist in [05-management.md](05-management.md). Scope: the `catalog-cart` and `checkout` FastAPI services, their images, `modules/compute` (ALB, listener rules, target groups, ECS cluster/services, task/execution roles, autoscaling) and `modules/registry` (ECR). Owner 2 also owns those resources end to end in every cloud run: build, push, apply, verify, evidence and teardown.

## Context

A review on 2026-11-03 compared `main` (`669c43d`) with [plan 06](06-demo-build.md) Sections 3, 5.2 and 6.2, [plan 02](02-architecture.md) and the Owner 2 mandate: HTTP 202 in under 200 ms, and reliable scaling under high concurrency. The local suite passes (208 tests, 1 skipped). Nothing has been verified in a live deployment yet.

### Status against the demo architecture

| Requirement (source) | Status | Evidence / gap |
|---|---|---|
| Two FastAPI services, ARM64 Fargate, 0.5/1 vCPU and 1/2 GB (06 §3 #4–5) | Done locally | `modules/compute` `local.services`, `runtime_platform.cpu_architecture = "ARM64"`. |
| All §5.2 routes and status codes | Done locally, with gaps | Covered by `tests/services/`. Gaps API-1, API-3, API-4, API-5 and API-8 below. |
| JWT check: signature, `iss`, `exp`, `token_use`, `client_id` (06 §5.2) | Done (Owner 5) | `chopee.auth.JwtVerifier`, but it blocks the event loop when called (API-2). |
| One boto3 client per process, `max_pool_connections=64`, standard retries | Done | Both `create_app` factories. |
| Uvicorn 2 workers per vCPU | Done | `local.uvicorn_workers` = 1 / 2. |
| Checkout = one `GetItem` + one `SendMessage` | Done | But the `GetItem` is eventually consistent (API-1). |
| Immediate order-status reads use strong consistency (02 Persistence) | **Missing** | API-1. Also a listed Owner 2 gap in plan 05. |
| ALB SG: CloudFront prefix list + `operator_cidr` only; tasks only from the ALB | Done | `aws_vpc_security_group_ingress_rule.*`. |
| `X-Origin-Verify` on `/api/*` listener rules | Done, with a deliberate exception | `/api/webhooks/*` (priority 5) has no header check so `sim_gateway.py` can call the ALB directly. The exception is documented in 06 §6.2. |
| `/api/healthz` reachable through the edge (06 §5.2 table) | **Missing** | No listener rule matches it, so CloudFront → ALB returns the fixed 404 (API-8). The target-group health checks work. |
| Circuit breaker with rollback; min 2 tasks across 2 AZs | Done | `aws_ecs_service.svc`. |
| CPU 60% target tracking; optional scheduled pre-scale to 6 | Done, not tuned | Only CPU tracking, default cooldowns, and `prescale_at` defaults to `null` (API-6). |
| Per-service execution roles; key-scoped task roles | Done (Owner 5 SEC-4) | Pinned by `tests/infra/test_security_config.py`. |
| ECR repos, scan on push, `force_delete` | Done | `modules/registry`. Tags are mutable, and dependency versions float (API-7). |
| ARM64 images build cleanly via `scripts/push_images.sh` (plan 05 gap) | Done locally, unproven | Copy-only Dockerfiles plus aarch64 wheels. No recorded build/push transcript. |
| HCL regression tests for compute (listener rules, autoscaling, ARM64) | **Missing** | Only the security assertions in `test_security_config.py` exist (API-9). |
| X-Ray sidecar plus one end-to-end trace (06 M6) | Done locally | DynamoDB/SQS subsegments made inside `run_in_threadpool` may attach to the wrong request or be dropped (API-2). |
| 500 orders/s, p95 ≤ 200 ms, task-stop recovery (02 Validation, 06 M7) | **Not run** | Owner 2 operates the compute side of M6–M8 (Section "End-to-end cloud ownership"). |

**Verdict:** the code is functionally complete for the demo boundary, but not demo-ready. One correctness gap is already on the plan 05 list (API-1). Two latency risks threaten the < 200 ms burst target (API-2, API-6). Several contract edge cases remain (API-3 to API-5). None of the live acceptance has been run.

## Steps (plan first, then code)

### API-1 Strongly consistent order reads

- `services/checkout/app.py` `get_order()` passes `ConsistentRead=True`. It serves the idempotency check, `GET /api/orders/{id}`, the webhook and demo-pay order lookups.
- Rationale: the worker writes the order, and the gateway or storefront may read it within milliseconds. An eventually consistent read can return `404 unknown order` to a valid webhook, or allow a duplicate `SendMessage` after the order already exists. The cost is 1 RCU instead of 0.5 per read, which is negligible at demo volume.
- `GET /api/orders` (GSI1) stays eventually consistent. GSIs cannot be strongly consistent, and plan 02 accepts that for history.
- Test: a fake table that records the `get_item` kwargs, asserting `ConsistentRead is True` on every caller path.

### API-2 Keep the event loop free (JWT and tracing)

- In every `async def` route, call `verifier.subject()` through `run_in_threadpool` (checkout: `checkout`, `read_order`, `demo_pay`; catalog-cart: `put_item`, `merge`). Alternatively, warm the JWKS cache at startup (`verifier._keys()` inside a FastAPI `lifespan` hook, fail-static on error), so the first request on each new task never makes the blocking `urllib` fetch (3 s timeout) on the loop. Do both: warm-up at startup, and the threadpool hop for refreshes.
- X-Ray: `AsyncContext` resolves the segment from the loop's *current task*, which is not the request when code runs in a worker thread. Either run the boto3 calls on the loop thread with the request's segment passed explicitly (`xray_recorder.begin_subsegment` on the captured segment), or switch the recorder to the default thread-local context and begin the segment inside the threadpool call. Coordinate with Owner 6 (SRE-6 owns `chopee/tracing.py`).
- Tests: a verifier stub whose `subject()` sleeps; assert that two concurrent requests finish in about 1× the sleep, not 2×. A tracing test asserting that DynamoDB/SQS subsegments land under the request's own segment.

### API-3 Webhook and demo-pay enqueue fail fast

- Wrap `sqs.send_message` in `verify_and_enqueue` the same way as checkout: on any exception, log `enqueue_failed` (with `customerRef`, never `customerId`) and return `503` + `Retry-After: 1`. Today it surfaces as a 500, and the gateway sees no retry hint.
- Test: an SQS stub that raises → 503 with `Retry-After`, for both `/api/webhooks/payment` and `/api/demo/pay/{id}`.

### API-4 Demo pay only while pending

- `/api/demo/pay/{id}` returns `409 {"error":"order not pending"}` unless `status == PENDING_PAYMENT`. Each call mints a fresh `eventId`, so a second click on a `PAID` order today creates a `RECON#…/LATE_PAYMENT` item and increments `LatePayments`, which pollutes reconcile output and demo evidence. The public webhook keeps the current behaviour (late real payments must still be recorded).
- Coordinate with Owner 1: the storefront already hides the buttons after a terminal status, and should show the 409 message if it appears.

### API-5 Idempotency key reuse before the worker runs

- With `deduplication_scope = "messageGroup"`, the same `Idempotency-Key` sent by two customers before the order item exists is enqueued twice. Both get `202`, and the worker silently treats the second as a duplicate. The `409` contract only holds after the worker has run.
- Fix (cheap, still one write): before `SendMessage`, conditionally `PutItem` a claim `ORDER#{id}` / `CLAIM` with `customerId` and `ttl` (+1 h) under `attribute_not_exists(PK)`. On a condition failure, read the claim: same customer → keep today's behaviour; other customer → `409`. This needs `dynamodb:PutItem` on `ORDER#*` in the checkout task role (coordinate the policy change with Owner 5, and the item with Owner 4 for the plan 06 §5.1 table).
- Alternative if latency budget forbids the extra write: document the window as a known demo deviation in 06 §6.2. Decide after the API-10 latency measurement; record the decision here.

### API-6 Scale for a burst, not after it

- Add a second target-tracking policy on `ALBRequestCountPerTarget` for checkout (target about 150 req/s per task, below the plan 02 estimate of 200 req/s per vCPU). Set explicit `scale_out_cooldown = 30` and `scale_in_cooldown = 300` on both policies.
- Make the pre-scale impossible to forget: `scripts/run_demo.sh` (or the runbook in plan 04) fails before the load test unless the checkout running count is at least `checkout_burst_tasks`. Alternatively, run `aws application-autoscaling register-scalable-target --min-capacity 6` explicitly at least 5 minutes before the hold.
- Fargate quota check: max 10 checkout (10 vCPU) plus 10 catalog-cart (5 vCPU) = 15 vCPU, within the ≥ 16 preflight in 06 §7.2. Keep it that way if max capacity changes.
- Record the task spin-up latency (`RunTask` → healthy target) from ECS events during M6. This closes the plan 05 "monitor spin-up latency" item.

### API-7 Reproducible images

- Pin exact versions in `services/*/requirements.txt` (generate from the tested venv). `>=` lets a FastAPI/Starlette/boto3 release between M6 and M8 change the image that was tested.
- Pin the base image by digest (`python:3.12-slim@sha256:…`) through the `BASE_IMAGE` arg default.
- Add `USER 10001` to both Dockerfiles (no RUN step is needed; Fargate accepts a numeric UID). The app writes nothing to disk.
- Set `image_tag_mutability = "IMMUTABLE"` in `modules/registry`, and use the `run_id` as `image_tag`, so each run's task definition names exactly one image.

### API-8 Contract tidy-ups

- Add `/api/healthz` to the catalog-cart listener rule paths (any service may answer), so the §5.2 table holds through CloudFront and smoke checks can probe the edge.
- Remove the duplicate signature verification in the webhook route. Verify once, then annotate and enqueue, passing the parsed payload into the shared function.
- Remove the unused `COGNITO_ISSUER` environment variable, or use it in `JwtVerifier`.
- `render_cart` and `merge_carts` call `get_product()` once per line (`merge` does it twice per line). Use the cached `load_catalog()` map for price and existence (one cache hit instead of N `GetItem`s).
- Guard `load_catalog()` refresh with a `threading.Lock`, so concurrent cache misses in the threadpool do not each run the GSI query plus `BatchGetItem`.
- Expose `available` (cached, may lag 30 s) alongside `inStock` in `GET /api/catalog`. Owner 1 needs it for the `LIMITED-01` countdown (plan 05, Owner 1 gap 1). Update the 06 §5.2 response shape first.

### API-9 Compute regression tests

Add `tests/infra/test_compute.py` (parse HCL like `test_security_config.py`):

- Listener rule paths match 06 §5.2 exactly. Every rule except `webhook` has the `X-Origin-Verify` header condition. The webhook rule priority is lower than the service rules.
- Both task definitions use `ARM64`/`LINUX`. CPU/memory are 512/1024 and 1024/2048. The X-Ray sidecar is present on checkout only.
- Services have the circuit breaker with rollback, `assign_public_ip = true`, and `ignore_changes = [desired_count]`.
- Autoscaling: CPU target 60, the request-count policy from API-6, `max_capacity` ≤ 10.
- `modules/registry`: `force_delete = true`, `scan_on_push = true`, `IMMUTABLE`.

### API-10 Latency budget proof (local, before cloud)

- Add a `scripts/` micro-benchmark (or a pytest marker excluded by default) that runs the checkout app under Uvicorn with moto/stub clients and drives about 200 req/s per worker locally. Record the p95 of the handler cost without network. This gives a floor to compare against ALB `TargetResponseTime` in M7.

## End-to-end cloud ownership (Owner 2, per timed run)

Owner 2 runs and signs off on these steps of 06 §6.4. The deployment operator holds the state file; Owner 2 is present for every apply and destroy.

| Step | Owner 2 action | Pass criterion / evidence |
|---|---|---|
| Preflight (once, ≥ 1 week before M6) | Confirm the Fargate On-Demand vCPU quota (`L-3032A538`) ≥ 16. Confirm `docker buildx` can build `linux/arm64`. | Quota screenshot or CLI output; a `docker buildx ls` line showing `linux/arm64`. |
| Stage 1 | `terraform plan -target=module.registry … -out=tfplan` → `apply tfplan`. | Two ECR repos exist. |
| Images | `scripts/push_images.sh <run_id>`, then `aws ecr describe-images`. | Both tags present. Scan-on-push results reviewed (no CRITICAL findings, or the exceptions noted). |
| Stage 2 | Review the compute section of the full plan. | Only `ap-southeast-1` resources, two services, three listener rules plus the fixed-404 default action, autoscaling targets. |
| Service health | `aws ecs describe-services`: running = desired. Both target groups healthy. `curl {cloudfront}/api/healthz` (after API-8) and `curl {alb}/api/catalog` without the header → 404. | Transcript saved to `evidence/` (not `docs/`). |
| Smoke (M6) | Own the HTTP assertions in `scripts/smoke.py` (catalog, cart merge, checkout 202 → 200, order poll, webhook 401). | `smoke.py` exit 0. One checkout→worker trace in X-Ray. |
| Burst (M7) | Pre-scale to `checkout_burst_tasks` ≥ 5 minutes before the hold (API-6 gate). Watch CPU, request count and `TargetResponseTime` p95. Run `scripts/stop_checkout_task.sh` during the hold, coordinated with Owner 6. | ALB p95 during hold ≤ 200 ms (or the miss reported honestly), 5xx < 1%, the replacement task healthy, scale-out events captured. |
| Teardown | `terraform destroy -auto-approve`. Check with Owner 6's `verify_empty.sh` for ECS cluster/services/tasks, ALB/TGs, SGs, ECR repos/images, and `/ecs/chopee-*` log groups. | `verify_empty.sh` clean for every compute/registry resource. |

Cost note (02 Demo cost assumptions): ALB plus Fargate is about USD 1–2 per 5-hour run at 4 tasks rising to 8. Holding 6 checkout tasks for longer than the burst window is the main Owner 2 cost lever, so scale back down or destroy promptly.

## Cross-owner dependencies

- **Owner 1:** the `available` field (API-8) and the 409 handling on demo pay (API-4).
- **Owner 4:** the `CLAIM` item in 06 §5.1 (API-5, if adopted). `reconcile.py` must ignore `CLAIM` items.
- **Owner 5:** the task-role change for API-5. JWKS warm-up uses the existing fail-static verifier.
- **Owner 6:** X-Ray context fix (API-2). Smoke/load scripts and the task-stop drill.

## Definition of done

- This plan updated first. Each API-n lands with its tests. `pytest` is green, and `terraform fmt -check` and `validate` pass.
- Live acceptance (M6–M8) is recorded with evidence per the table above. Local tests are not live proof.
- Plan 05's Owner 2 bullet links here and records the local-completion date.

## Local completion (2026-11-03, live verification pending)

API-1 to API-10 are implemented and covered by `pytest` (full suite green). `terraform fmt -check` and `validate` pass. Decisions and notes:

- API-5: the `CLAIM` item was adopted (one conditional `PutItem` before `SendMessage`). `reconcile.py` already reads only `SK = META`, and a test pins that.
- API-2: `chopee.tracing` now uses a `contextvars`-backed X-Ray context instead of `AsyncContext`. anyio copies it into threadpool workers, so boto3 subsegments parent to their own request.
- API-7: images are pinned to `fastapi==0.162.0`, `starlette==1.7.0`, `uvicorn==0.54.0`, `pyjwt[crypto]==2.15.0`, `cryptography==50.0.1`, `boto3`/`botocore==1.43.123` and `aws-xray-sdk==2.16.0`. The base image is pinned by multi-arch digest, and both containers run as `USER 10001`. `image_tag` must be the `run_id` now that ECR tags are immutable.
- API-6: `scripts/run_demo.sh --then …` refuses to start the load step unless checkout `runningCount ≥ --burst-tasks` (default 6).
- API-10: `scripts/bench_checkout.py` is in place. A first run of 500 requests at concurrency 50 reported p95 172 ms, but that figure is dominated by in-process queueing, not handler cost. Re-run at lower concurrency (for example `--concurrency 5`) to record the handler floor before M7.
- Still open: all live acceptance in the end-to-end ownership table (M6–M8).
