# 06 — Demo Build Specification

This is the build entry point for the live demo. An agent or developer should be able to build the whole demo from this file plus [plan 03](03-data-cart-orders.md) (business rules) and [plan 04](04-operations.md) (alarms and runbook), without re-deriving decisions. The [proposal](../proposal.md) Section 3.2 sets the demo boundary; this file fixes how to build exactly that and nothing more.

## 1. Build principles

- **Build only what the demo shows.** Every component below maps to a rubric criterion in [plan 07](07-presentation-report.md#1-rubric-traceability). Anything in the enterprise target that is not in Section 3 of this file stays as diagram and prose only.
- **Reuse before writing.** Use the open-source pieces in Section 2. Write custom code only for the parts graders assess: the checkout/queue/worker flow, idempotency, stock reservation, payment state, events and alarms.
- **Python 3.12 everywhere, ARM64 everywhere.** Lambda on Graviton (`arm64`), Fargate with `runtime_platform.cpu_architecture = "ARM64"`. One language keeps the shared code in one place.
- **Local tests first, cloud only for timed runs.** Business logic is proven with `pytest` and `moto` before any `terraform apply`.
- **Everything in `ap-southeast-1`**, tagged `Project=chopee`, destroyed after each run.

## 2. Reuse decisions

| Need | Reuse | Why this and not a full platform |
|---|---|---|
| Storefront UX, guest-cart → login merge, product mock data | [aws-samples/aws-serverless-shopping-cart](https://github.com/aws-samples/aws-serverless-shopping-cart) (MIT-0): Vue/Amplify storefront, Python cart Lambdas, anonymous cart keyed by a UUID, cart migration on login that sums quantities | Closest match to FR1–FR2 and already Python + Cognito + DynamoDB. Port its cart and migration logic into the catalog/cart service and its product list into the seed data. Its Vue 2/Amplify build is old, so do not rebuild it: re-implement the same screens as a no-build static page (Section 5.6). Credit it in `README.md`. |
| Lambda logging, metrics, tracing, FIFO partial-batch handling | [Powertools for AWS Lambda (Python)](https://docs.powertools.aws.dev/lambda/python/latest/), consumed as the AWS-published public Lambda layer for `python3.12`/`arm64` in `ap-southeast-1` | `SqsFifoPartialProcessor` implements the "stop at first failure" FIFO rule from plan 02 for free. `Logger` gives structured JSON; `Metrics` emits EMF custom metrics without API calls; `Tracer` wraps X-Ray. Look up the current layer ARN on the Powertools docs at build time. |
| Fargate HTTP services | FastAPI + Uvicorn, PyJWT (`pyjwt[crypto]`) for Cognito JWKS verification, boto3 | Small, well-known, async-capable. |
| Network/ALB Terraform | Plain `aws_*` resources (preferred) or `terraform-aws-modules/vpc` and `terraform-aws-modules/alb` pinned to one major version | The demo VPC is two public subnets with no NAT; plain resources are about 40 lines and avoid module surprises. Either is acceptable. |
| Load generator | [k6](https://k6.io/) `ramping-arrival-rate` executor | Drives an exact orders/second rate, reports p95/p99 and status counts, single binary. |
| Local AWS emulation for tests | [moto](https://github.com/getmoto/moto) (`mock_aws`) | Supports DynamoDB transactions, Streams records, SQS FIFO and SNS well enough for unit/integration tests. LocalStack is optional, not required. |
| X-Ray on Fargate | `public.ecr.aws/xray/aws-xray-daemon` sidecar | Reachable from public subnets without NAT. The X-Ray SDKs are in maintenance mode but supported through the demo period; ADOT is the documented successor. |

**Rejected:** full commerce platforms (Saleor, Medusa, Vendure, PrestaShop, Magento, Spree) need PostgreSQL/MySQL, Redis and their own order pipeline. Adopting one would add a relational tier the demo deliberately removes, and the graded flows (FIFO checkout, atomic reservation, outbox events) would have to be rewritten inside someone else's codebase. AWS's polyglot `retail-store-sample-app` was rejected for the same reason: Java/Go/Node services with RDS, Redis and its own messaging. The proposal states this reuse choice in Section 3.2.

## 3. Demo component inventory (build exactly this)

| # | Component | Implementation | Proposal/requirement |
|---|---|---|---|
| 1 | Storefront | Static HTML/JS/CSS in S3, served by CloudFront with Origin Access Control | Tier 1, FR3 |
| 2 | Auth | Cognito user pool, **`user_pool_tier = "LITE"`**, public app client | FR1 |
| 3 | Ingress | CloudFront `/api/*` → ALB (HTTP origin), listener path rules to two target groups | Tier 1 |
| 4 | `catalog-cart` service | Fargate, FastAPI, 0.5 vCPU / 1 GB, min 2 tasks across 2 AZs | FR2, FR3 |
| 5 | `checkout` service | Fargate, FastAPI, 1 vCPU / 2 GB, min 2, pre-scaled to 6 for the burst; X-Ray sidecar | FR4, FR6, NFR1 |
| 6 | Order queue | `chopee-orders.fifo` high-throughput FIFO + `chopee-orders-dlq.fifo` | FR4, NFR2 |
| 7 | `order_worker` Lambda | Reserve stock, apply payment results, expire orders | FR5, FR6 |
| 8 | Expiry timers | EventBridge Scheduler one-time schedules in group `chopee-expiry` → FIFO | FR6 |
| 9 | Table | DynamoDB on-demand `chopee`, Streams `NEW_IMAGE`, PITR, TTL on `ttl` | FR2–FR7, NFR3 |
| 10 | `outbox_relay` Lambda | Streams (filtered to outbox items) → SNS `chopee-order-events` | FR7 |
| 11 | `notify_logistics`, `notify_customer` Lambdas | SNS subscribers with filter policies; log synthetic outcomes | FR7 |
| 12 | `report` Lambda | Daily Scheduler cron + manual invoke; Logs Insights → S3 reports bucket | FR9 (demo subset) |
| 13 | Observability | CloudWatch dashboard, alarms (plan 04), ops SNS topic with email subscription, X-Ray | NFR7 |
| 14 | Audit | One CloudTrail trail → deletable S3 audit bucket | FR8 |
| 15 | Secrets | SSM Parameter Store `SecureString` for the webhook HMAC secret and CloudFront origin header | NFR4 |
| 16 | Cost guard | AWS Budget (separate, persistent, free) — Section 6.3 | Governance |

**Do not build:** Redis, Aurora, RDS Proxy, WAF, Route 53, ACM certificates, NAT, private subnets, VPC endpoints, customer-managed KMS keys, Macie, Firehose, Glue, Athena, QuickSight, Object Lock, a real payment gateway, carrier APIs, an admin UI, search, product image upload, remote Terraform state, CI/CD pipelines, or sharded stock counters. These are design-only and must be described as such.

## 4. Repository layout

```
storefront/                 # static SPA; config.json is generated by Terraform at deploy time
  index.html  app.js  styles.css
shared/python/chopee/       # shared library, packaged as a Lambda layer and copied into both images
  keys.py  models.py  events.py  auth.py  signing.py  logging.py
services/
  catalog_cart/             # FastAPI app + Dockerfile (build context = repo root)
  checkout/                 # FastAPI app + Dockerfile (build context = repo root)
functions/
  order_worker/  outbox_relay/  notify_logistics/  notify_customer/  report/   # handler.py each
infra/
  budget/                   # one-time AWS Budget, applied once and kept (free); not part of teardown
  terraform/                # the ephemeral demo stack
    versions.tf  providers.tf  variables.tf  main.tf  outputs.tf
    envs/demo.tfvars.example
    modules/network  modules/registry  modules/data  modules/queues  modules/identity
    modules/compute  modules/functions  modules/events  modules/edge  modules/observe
scripts/
  push_images.sh  seed_catalog.py  create_test_users.py  sim_gateway.py  inject_poison.py
  smoke.py  reconcile.py  verify_empty.sh
loadtest/checkout_burst.js
tests/                      # pytest + moto; one file per handler/service
requirements-dev.txt  pytest.ini  Makefile (optional convenience targets)
```

`.gitignore` must exclude `infra/**/.terraform/`, state files, `tfplan`, `infra/terraform/envs/demo.tfvars`, `build/`, `*.zip`, `loadtest/tokens.json` and `evidence/`. Evidence (screenshots, k6 summaries) is kept outside the repo or in `evidence/` locally and goes into the final report, never under `docs/`.

## 5. Contracts

### 5.1 DynamoDB single table `chopee`

Keys: `PK` (S), `SK` (S). GSI `GSI1` on `GSI1PK`/`GSI1SK` (projection ALL). TTL attribute `ttl` (epoch seconds). Stream view `NEW_IMAGE`.

| Item | PK | SK | Key attributes | Notes |
|---|---|---|---|---|
| Product | `PRODUCT#{sku}` | `META` | `name, price (cents, N), currency="SGD", description, emoji` ; `GSI1PK="CATALOG"`, `GSI1SK=sku` | Catalog listing queries `GSI1PK=CATALOG`. |
| Stock | `PRODUCT#{sku}` | `STOCK` | `available (N)`, `initial (N)` | Authoritative. One item per SKU in the demo; sharded counters are design-only (load test spreads across ≥20 SKUs instead). |
| Cart line | `CART#{owner}` | `ITEM#{sku}` | `quantity`, `updatedAt`, `ttl` (guest: +24 h) | `owner` is `USER#{sub}` or `GUEST#{uuid}`. Application rejects guest carts older than 24 h; TTL is cleanup only. |
| Merge marker | `CART#USER#{sub}` | `MERGED#{guestId}` | `mergedAt` | Written in the same transaction as the merged lines with `attribute_not_exists(PK)`, so a retried merge adds nothing. |
| Order | `ORDER#{orderId}` | `META` | `customerId, status, reason, items[], total, currency, createdAt, expiresAt`; `GSI1PK=CUSTOMER#{sub}`, `GSI1SK=ORDER#{createdAt}` | `orderId` **is** the client's UUID v4 `Idempotency-Key`; the order item doubles as the durable idempotency record. |
| Payment ledger | `ORDER#{orderId}` | `PAYMENT#{gatewayEventId}` | `outcome, amount, currency, receivedAt` | `attribute_not_exists` makes gateway retries harmless. |
| Reconciliation | `ORDER#{orderId}` | `RECON#{gatewayEventId}` | `kind="LATE_PAYMENT"`, details | Late success after cancellation; refund is design-only. |
| Outbox event | `EVENT#{eventId}` | `EVENT` | `type, orderId, customerRef, status, occurredAt`, `ttl` (+1 day) | Written inside the same transaction as the state change. Streams filter selects these. |
| Consumer dedupe | `CONSUMED#{consumer}#{eventId}` | `CONSUMED` | `ttl` (+1 day) | Conditional put before acting. |

Order status values: `PENDING_PAYMENT`, `PAID`, `CANCELLED` (reason `PAYMENT_DECLINED` or `PAYMENT_TIMEOUT`), `REJECTED` (reason `OUT_OF_STOCK`). Before the worker runs there is no order item; the API reports that as `QUEUED`.

`customerRef` in events and logs is a pseudonym: the first 12 hex characters of `HMAC-SHA256(log_salt, sub)`. Never log email, tokens or full payloads.

### 5.2 HTTP API (all paths under `/api`, JSON, through CloudFront)

ALB listener rules: `/api/catalog*` and `/api/cart*` → `catalog-cart`; `/api/checkout*`, `/api/orders*`, `/api/webhooks/*`, `/api/demo/*` → `checkout`; default → fixed 404. Both target groups health-check `GET /api/healthz`. Authenticated routes require `Authorization: Bearer <Cognito access token>`; verify signature against the pool JWKS (cached), `iss`, `exp`, `token_use == "access"` and `client_id`. Customer identity is `sub`.

| Method & path | Auth | Request | Responses |
|---|---|---|---|
| `GET /api/healthz` | none | – | `200 {"ok":true}` |
| `GET /api/catalog` | none | – | `200 [{sku,name,price,currency,description,emoji,inStock}]` — served from a 30-second in-process cache (demo stand-in for Redis, FR3) |
| `GET /api/catalog/{sku}` | none | – | `200` product, `404` |
| `GET /api/cart` | JWT or `X-Guest-Id: <uuid>` | – | `200 {items:[{sku,quantity,price}], total}` |
| `PUT /api/cart/items/{sku}` | JWT or `X-Guest-Id` | `{quantity: 0..5}` (0 removes) | `200` cart, `400`, `404` unknown SKU |
| `POST /api/cart/merge` | JWT | `{guestId}` | `200` merged cart (idempotent per `guestId`); quantities summed and capped at 5, prices re-read from catalog |
| `POST /api/checkout` | JWT | header `Idempotency-Key: <uuid v4>`; body `{items:[{sku,quantity}]}` (1–10 lines, qty 1–5) | `202 {orderId,status:"QUEUED"}` after SQS confirms; `200 {orderId,status}` if the order already exists for this customer; `400` invalid; `401`; `409` key belongs to another customer; `503` + `Retry-After: 1` if SQS fails (fail fast, never hang) |
| `GET /api/orders/{orderId}` | JWT (owner only) | – | `200 {orderId,status,reason,items,total,createdAt,expiresAt}`; `404` if not yet processed or not owned (the storefront polls for up to 30 s) |
| `GET /api/orders` | JWT | – | `200` latest 20 orders via `GSI1` |
| `POST /api/webhooks/payment` | HMAC signature, no JWT | header `X-ChopeE-Signature: t=<unix>,v1=<hex>`; body `{eventId,orderId,outcome:"succeeded"|"declined",amount,currency,occurredAt}` | `200 {"received":true}` after enqueue; `401` bad/expired signature (also emits metric `WebhookSignatureFailures`); `404` unknown order; `422` amount/currency mismatch |
| `POST /api/demo/pay/{orderId}` | JWT (owner), only when `DEMO_GATEWAY=true` | `{outcome:"succeeded"|"declined"}` | Builds a gateway event, signs it with the shared secret and passes it to the **same** verify-and-enqueue function as the public webhook. Stand-in for the hosted payment page. |

Signature: `v1 = hex(HMAC_SHA256(secret, f"{t}.{raw_body}"))`; reject if `abs(now - t) > 300`. The checkout service reads the order to get `customerId`, so the payment message joins that customer's FIFO group.

Implementation notes: create one boto3 client per process with `botocore.config.Config(max_pool_connections=64, retries={"mode":"standard"})`; run Uvicorn with 2 workers per vCPU; keep the checkout handler to one `GetItem` (idempotency check) plus one `SendMessage`.

### 5.3 Queue messages (`chopee-orders.fifo`)

Queue settings: `fifo_queue=true`, `content_based_deduplication=true` (required by Scheduler FIFO targets), `deduplication_scope="messageGroup"`, `fifo_throughput_limit="perMessageGroupId"`, visibility timeout 180 s (6 × 30 s worker timeout), SSE-SQS, redrive to the DLQ with `maxReceiveCount=3`, DLQ retention 14 days.

| `type` | Producer | `MessageGroupId` | Deduplication | Body fields |
|---|---|---|---|---|
| `ORDER_PLACED` | checkout service | customer `sub` | explicit `orderId` | `orderId, customerId, items[{sku,quantity}], acceptedAt, traceId` |
| `PAYMENT_RESULT` | checkout service (webhook) | order's `customerId` | explicit gateway `eventId` | `orderId, customerId, eventId, outcome, amount, currency` |
| `ORDER_EXPIRE` | EventBridge Scheduler | order's `customerId` (Scheduler `SqsParameters.MessageGroupId`) | content-based (payload is unique per order) | `orderId, customerId, scheduledAt` |

Any other or malformed message (including `items` that fail `validate_lines`) must raise `InvalidMessage`, not be dropped, so the worker logs `poison_message` and it reaches the DLQ after three attempts. `scripts/inject_poison.py` uses this to demonstrate the DLQ alarm.

### 5.4 Worker state transitions (`order_worker`)

Event source mapping: batch size 10, `function_response_types=["ReportBatchItemFailures"]`, processed with Powertools `SqsFifoPartialProcessor(skip_group_on_error=True)`, so a failure only blocks the rest of its own message group and other customers in the batch are not redelivered. Timeout 30 s, memory 256 MB, reserved concurrency `var.worker_reserved_concurrency` (default 100, per the plan 02 capacity check). Each transition is one `TransactWriteItems`.

| Message | Transaction | On `TransactionCanceledException` |
|---|---|---|
| `ORDER_PLACED` | Put order `PENDING_PAYMENT` (`attribute_not_exists(PK)`); per line `available = available - :q` with `available >= :q`; Put outbox `OrderPendingPayment`. Price from catalog (cached 60 s). Then `CreateSchedule` `expire-{orderId}` at `now + EXPIRY_MINUTES` (default 15) with `ActionAfterCompletion=DELETE`. | Order condition failed → duplicate: ensure the schedule exists (`ConflictException` is fine) and succeed. Stock condition failed → Put order `REJECTED/OUT_OF_STOCK` + outbox `OrderRejected` (`attribute_not_exists`). Anything else (throttling, conflict) → raise to retry. |
| `PAYMENT_RESULT` succeeded | Update order `PAID` if `status = PENDING_PAYMENT AND total = :amount`; Put ledger `PAYMENT#{eventId}`; Put outbox `OrderPaid`. | Ledger exists → duplicate, succeed. Order not pending → Put `RECON#{eventId}` (`LATE_PAYMENT`), emit metric `LatePayments`, succeed. |
| `PAYMENT_RESULT` declined | Update order `CANCELLED/PAYMENT_DECLINED` if pending; per line `available = available + :q`; Put ledger; Put outbox `OrderCancelled`. | Not pending or ledger exists → no-op. |
| `ORDER_EXPIRE` | Update order `CANCELLED/PAYMENT_TIMEOUT` if pending; release stock; Put outbox `OrderCancelled`. | Not pending → no-op (already paid or cancelled). |

Stock is released exactly once because release only happens in the transaction that moves the order out of `PENDING_PAYMENT`. Emit EMF metrics `OrdersReserved`, `OrdersRejected`, `OrdersPaid`, `OrdersCancelled`.

`EXPIRY_MINUTES` is a deployment variable. Live runs keep 15; a shortened value used in rehearsal must be labelled as such in any evidence.

### 5.5 Events and consumers

- `outbox_relay`: Streams event source with filter `{"eventName":["INSERT"],"dynamodb":{"Keys":{"PK":{"S":[{"prefix":"EVENT#"}]}}}}`, batch 100, `ReportBatchItemFailures`, `bisect_batch_on_function_error=true`, maximum retry attempts 5, on-failure destination `chopee-notify-dlq`. Publishes to SNS `chopee-order-events` with message attribute `eventType`.
- `notify_logistics`: SNS filter `{"eventType":["OrderPaid"]}`; logs `fulfilment_requested`.
- `notify_customer`: SNS filter `{"eventType":["OrderPendingPayment","OrderPaid","OrderCancelled","OrderRejected"]}`; logs `customer_notified` (simulated email/push).
- Both consumers conditionally put `CONSUMED#…` first; a repeat event is logged as `duplicate_ignored`. Both subscriptions use `chopee-notify-dlq` (standard SQS) as redrive policy; Lambda async on-failure destination is the same queue.

### 5.6 Storefront

Single page, no build step: `index.html` + `app.js` + `styles.css`, using Alpine.js and Pico.css pinned from a CDN (or vendored). Screens, mirroring the AWS sample: product grid, cart drawer, sign-up/sign-in, order status, order history.

- Auth: call Cognito directly with `fetch` to `https://cognito-idp.ap-southeast-1.amazonaws.com/` (`SignUp`, `ConfirmSignUp`, `InitiateAuth` with `USER_PASSWORD_AUTH`, `REFRESH_TOKEN_AUTH`). No Hosted UI, so no callback URLs or domains. Keep tokens in memory/sessionStorage.
- Guest cart: generate a UUID in `localStorage` and send `X-Guest-Id`. After sign-in, call `/api/cart/merge` once, then drop the guest id.
- Checkout: generate the `Idempotency-Key` once per checkout attempt and reuse it on retry; poll `GET /api/orders/{id}` every second; when `PENDING_PAYMENT` show **Pay (simulated)** and **Decline (simulated)** buttons that call `/api/demo/pay/{id}`, plus a countdown to `expiresAt`.
- `config.json` (`apiBase`, `region`, `userPoolId`, `clientId`) is rendered by Terraform into the bucket. No secrets in the storefront.
- No binary assets: product visuals are emoji or inline SVG.

### 5.7 Report Lambda

Scheduler `cron(0 19 * * ? *)` (03:00 SGT) plus a manual invoke during the demo. Runs Logs Insights queries over the worker and checkout log groups for the last 24 h: orders by terminal status, rejected/late payments, webhook signature failures, checkout 5xx. Writes `reports/{yyyy}/{mm}/{dd}/{hhmm}.json` and `.csv` to the reports bucket. Contains only aggregates and `customerRef` pseudonyms (PII masking by construction).

## 6. Infrastructure (Terraform)

### 6.1 Providers and conventions

- `required_version >= 1.5`, `hashicorp/aws` pinned to a major version that supports `aws_cognito_user_pool.user_pool_tier`; commit `.terraform.lock.hcl`. Local state only.
- `provider "aws" { region = "ap-southeast-1"; default_tags { tags = { Project = "chopee", Run = var.run_id, Owner = var.owner } } }`. Name every resource with the `chopee-` prefix.
- Variables: `run_id`, `owner`, `alert_email`, `operator_cidr` (the operator's public IP `/32`), `expiry_minutes = 15`, `worker_reserved_concurrency = 100`, `checkout_min_tasks = 2`, `checkout_burst_tasks = 6`, `prescale_at` (optional RFC 3339 time for the scheduled scale-out), `image_tag`.
- Every S3 bucket `force_destroy = true`; every ECR repository `force_delete = true`; every log group created in Terraform with `retention_in_days = 1` before the function or service that writes to it.

### 6.2 Modules

| Module | Resources |
|---|---|
| `network` | VPC `10.20.0.0/16`, two public subnets in `ap-southeast-1a`/`1b`, IGW, route table. No NAT, no endpoints. Default NACL (custom NACLs are design-only). |
| `registry` | ECR repos `chopee-catalog-cart`, `chopee-checkout` (scan on push, `force_delete`). |
| `data` | DynamoDB table per Section 5.1, `billing_mode = "PAY_PER_REQUEST"`, PITR on, stream on, TTL on. |
| `queues` | FIFO + FIFO DLQ per Section 5.3; standard `chopee-notify-dlq`. |
| `identity` | Cognito user pool (`user_pool_tier = "LITE"`, email sign-in, auto-verify email) and public client (`ALLOW_USER_PASSWORD_AUTH`, `ALLOW_ADMIN_USER_PASSWORD_AUTH`, `ALLOW_REFRESH_TOKEN_AUTH`, access token validity 3 hours so pre-minted load-test tokens outlive the run). |
| `compute` | ALB SG ingress TCP 80 from the CloudFront origin-facing managed prefix list (`com.amazonaws.global.cloudfront.origin-facing`) and from `var.operator_cidr` (the prefix list counts as about 55 entries toward the 60-rule security group quota, so keep this group to those two rules). Listener rules additionally require header `X-Origin-Verify` (random value in SSM) for `/api/*`, so another CloudFront distribution cannot reach the ALB. Two `ip` target groups. ECS cluster, two ARM64 task definitions, two services with `assign_public_ip = true`, task SG ingress only from the ALB SG, `deployment_circuit_breaker { enable = true, rollback = true }`, target-tracking on CPU 60% (min `checkout_min_tasks`, max 10) and an optional `aws_appautoscaling_scheduled_action` to `checkout_burst_tasks`. Least-privilege task roles (checkout: `sqs:SendMessage` on the FIFO, `dynamodb:GetItem` on the table, `ssm:GetParameter` on its secret; catalog-cart: table read/write on `PRODUCT#`/`CART#` items via `dynamodb:LeadingKeys` where practical). |
| `functions` | Shared layer from `shared/` (`archive_file`), Powertools public layer, five functions per Section 5, `tracing_config.mode = "Active"`, event source mappings, Scheduler group `chopee-expiry`, a Scheduler execution role allowed `sqs:SendMessage` on the FIFO, the report schedule, and the worker's `scheduler:CreateSchedule` + `iam:PassRole`. |
| `events` | SNS `chopee-order-events` with the two filtered subscriptions; SNS `chopee-ops-alerts` with an email subscription to `var.alert_email`. |
| `edge` | Private S3 storefront bucket + OAC; CloudFront distribution (`PriceClass_200`, default certificate). Default behaviour → S3, managed `CachingOptimized`. `/api/*` → ALB origin, `http-only`, custom header `X-Origin-Verify`, managed `CachingDisabled` + `AllViewerExceptHostHeader` (with caching disabled this forwards the `Authorization` header, including on GET), all methods, viewer `redirect-to-https`. Storefront files and generated `config.json` uploaded with `aws_s3_object` and correct content types. |
| `observe` | Dashboard, alarms (plan 04 demo set), CloudTrail trail + audit bucket, reports bucket, SSM parameters (`random_password` for webhook secret, origin header, log salt). |

Outputs: `cloudfront_url`, `alb_dns_name`, `user_pool_id`, `client_id`, `queue_url`, `dlq_url`, `table_name`, `ecr_repos`, `reports_bucket`.

Known demo deviations to state in the report: CloudFront → ALB is HTTP because there is no custom domain or ACM certificate (target design: HTTPS with ACM on the ALB); the simulated gateway calls the ALB directly from `operator_cidr` (real gateways are allow-listed the same way); webhook and origin secrets sit in local Terraform state.

### 6.3 Budget root (`infra/budget/`)

One `aws_budgets_budget` (COST, USD 80, cumulative over the project dates) with notifications at 50%, 80% and 100% actual, plus 100% forecasted, to the team email. Apply once at project start and keep it; budgets are free and are not part of the ephemeral stack or the empty-state check.

### 6.4 Deploy sequence (one timed run)

1. `terraform -chdir=infra/terraform fmt -check && init && validate`.
2. Stage 1 (registry only): `plan -target=module.registry -var-file=envs/demo.tfvars -out=tfplan`, `apply tfplan`.
3. `scripts/push_images.sh <run_id>`: `docker buildx build --platform linux/arm64` for both services, push to ECR with tag `image_tag`.
4. Stage 2 (everything): `plan -var-file=envs/demo.tfvars -out=tfplan`, review, `apply tfplan`. Confirm the ops-alert email subscription (it is recreated every run).
5. `scripts/seed_catalog.py` (24 products × 2,000 stock, plus `LIMITED-01` with stock 50), `scripts/create_test_users.py --count 1000` (`AdminCreateUser` with `MessageAction=SUPPRESS`, `AdminSetUserPassword --permanent`, then `AdminInitiateAuth` at ≤20/s with back-off; writes `loadtest/tokens.json`).
6. `scripts/smoke.py` (Section 7 M6) must pass before anything is shown or load-tested.
7. Teardown: `terraform destroy -auto-approve -var-file=envs/demo.tfvars`, then `scripts/verify_empty.sh` (plan 04).

## 7. Build order and acceptance checks

Each milestone is one or more commits. Do not start a cloud milestone until the local ones pass.

| Milestone | Deliverable | Done when |
|---|---|---|
| M0 Skeleton | Layout from Section 4, `shared/` library (keys, models, signing, JWT verifier, pseudonymiser), `pytest` + `moto` harness | `pytest` runs green on an empty suite; `ruff`/`black` optional |
| M1 Worker | `order_worker` with Section 5.4 transitions | Tests prove: duplicate `ORDER_PLACED` creates one order; competing orders for `LIMITED-01` never drive `available` below 0; decline and expiry release stock once; success-vs-expiry race finalises once; late payment writes `RECON`; unknown message type raises |
| M2 Services | `catalog_cart` and `checkout` FastAPI apps | `TestClient` tests prove: guest cart → merge is idempotent; checkout returns 202 then 200 for the same key, 409 for another customer, 503 when SQS fails; webhook rejects bad and stale signatures and accepts a valid one once |
| M3 Events | `outbox_relay`, both consumers, `report` | Tests prove: only `EVENT#` inserts publish; consumers ignore repeated event IDs; report output contains no email or `sub` |
| M4 Storefront | Static SPA per Section 5.6 | Opens from `file://` or `python -m http.server` with a hand-written `config.json`; flows verified in the M6 smoke run |
| M5 Terraform | Modules per Section 6 | `terraform fmt -check` and `terraform validate` pass; `terraform plan` shows only `ap-southeast-1` resources plus the global CloudFront distribution |
| M6 First cloud run (smoke) | Deploy per 6.4, `scripts/smoke.py` | Script passes: sign-up/sign-in, guest cart merge, checkout → `PENDING_PAYMENT` → pay → `PAID`; decline → `CANCELLED` with stock restored; bad webhook signature → 401; poison message → DLQ alarm email received; both consumers logged their events; one end-to-end X-Ray trace visible; destroy and `verify_empty.sh` clean |
| M7 Load run | `loadtest/checkout_burst.js`, `scripts/reconcile.py` | Plan 04 Phase 4 targets recorded (pass or miss, reported honestly); reconcile shows every accepted order is `PAID`/`PENDING_PAYMENT`/`CANCELLED`/`REJECTED` or in the DLQ, no duplicates, no negative stock |
| M8 Dress rehearsal | Full [plan 07](07-presentation-report.md) script on a fresh stack; screen recording as backup | Timed under 20 minutes; evidence checklist complete; destroy clean |

Budget for this order: M6, M7, M8 and the final presentation are four runs at USD 8–12 each (USD 32–48), inside the USD 60 run budget. A failed run that must be repeated uses contingency.

### 7.1 Load test shape (`loadtest/checkout_burst.js`)

Three scenarios so the hold window is tagged: `ramp` (`ramping-arrival-rate`, 50 → 500 iterations/s over 30 s), `hold` (`constant-arrival-rate`, 500/s for 60 s, `startTime: 30s`) and `down` (`ramping-arrival-rate`, 500 → 0 over 15 s, `startTime: 90s`); `preAllocatedVUs` 300, `maxVUs` 1,000. Each iteration picks a random token from `tokens.json` (1,000 distinct users → ≥1,000 FIFO groups), a random SKU from the 24 normal SKUs, quantity 1, and a fresh UUID v4 key, then `POST {cloudfront_url}/api/checkout`. Checks `status == 202`. Thresholds report (not abort): `http_req_duration{scenario:hold} p(95) < 200`, `http_req_failed < 1%`. Export the summary JSON. The authoritative server-side latency is ALB `TargetResponseTime` p95 during the hold window, because client latency includes the operator's internet path. Pre-scale checkout to 6 tasks at least 5 minutes before the run.

### 7.1.1 Low-quota profile (Lambda concurrency 10)

The account's Lambda limit in `ap-southeast-1` is 10, so reserved concurrency is unavailable (`worker_reserved_concurrency = -1`) and the worker shares those 10 slots with the relay and both consumers. Run within the limit instead of requesting a quota:

- Set `worker_max_concurrency` (2–1000) to about 7. Without a cap the SQS poller can scale past the limit; throttled receives raise the receive count and, after `maxReceiveCount=3`, send healthy orders to the DLQ. Terraform rejects a value outside 2–1000, or above a positive `worker_reserved_concurrency`, at plan time.
- The checkout path (CloudFront → ALB → Fargate → SQS) uses no Lambda, so the full 500 orders/s burst still runs. Only the drain rate is limited, which is the point of the queue.
- Rate knobs: `-e PEAK_RATE=<orders/s>` scales the three scenarios (default 500) and `-e READ_RATE=<GET/s>` adds public catalog reads alongside (default off). Label any non-default value in the evidence.
- Contention: `k6 run -e BASE_URL=... loadtest/limited_contention.js` sends 300 single-unit orders for `LIMITED-01`; expect 50 reserved and 250 `REJECTED/OUT_OF_STOCK`.
- Task failure: `scripts/stop_checkout_task.sh` during the hold.

### 7.2 Account preflight (once, at least a week before M6)

- Lambda concurrency: `aws lambda get-account-settings --region ap-southeast-1`. New accounts start below the 1,000 default; request at least 1,000 via Service Quotas so the reserved 100 plus the other functions fit (Lambda keeps at least 100 unreserved).
- Fargate On-Demand vCPU quota (`L-3032A538`) ≥ 16.
- CloudFront: new accounts can be blocked from creating distributions until verified; create and delete a test distribution early or open a support case.
- EventBridge Scheduler `CreateSchedule` in Singapore defaults to 5,000 requests/s (checked 2026-10-16), above the 500/s needed.
- Docker `buildx` can build `linux/arm64` (native on Apple Silicon; QEMU on x86).
- Budget root applied and alert email confirmed.
