# Owner 5 — Security, identity & compliance hardening

Implementation plan for the Owner 5 checklist in [05-management.md](05-management.md). Scope: Cognito, the JWT verifier, webhook HMAC signing, IAM roles, SSM secrets, CloudTrail, and the PDPA and PCI DSS evidence.

## Context

A local audit on 2026-11-02 compared the code with the four Owner 5 checks. The baseline (Cognito Lite pool, `JwtVerifier`, `signing.verify`, SSM `SecureString` parameters, one CloudTrail trail) works, but each check has a gap:

1. **Cognito and JWKS.** `JwtVerifier` ([shared/python/chopee/auth.py](../../shared/python/chopee/auth.py)) caches the pool JWKS for one hour. When the cache expires and the refetch fails (a network blip or Cognito throttling), every authenticated request returns 401 until the next successful fetch. A token signed with a new `kid` (Cognito key rotation) is rejected until the TTL expires. No test pins the 3-hour token lifetime, the Lite tier or the public-client settings in [modules/identity](../../infra/terraform/modules/identity/main.tf).
2. **HMAC webhook.** `signing.verify` enforces the 300-second drift in both directions. However:
   - An unset `WEBHOOK_SECRET` becomes the empty string, and `HMAC("", ...)` is a key anyone can forge. The checkout service then accepts forged payment events instead of failing closed.
   - A non-ASCII `v1` value makes `hmac.compare_digest` raise `TypeError`, so the webhook returns 500 instead of 401.
   - [scripts/sim_gateway.py](../../scripts/sim_gateway.py) can only demonstrate a wrong secret. It cannot show a replayed (stale) or tampered request.
3. **PDPA logging.** Every log call in `services/` and `functions/` was reviewed (table below). No call site logs `sub`, email, tokens or payloads; customers appear only as `customerRef`. Two weaknesses remain. An unset `LOG_SALT` in checkout silently pseudonymises with an empty key. Nothing stops a future log line from adding `customerId`.
4. **Least privilege.**
   - Both ECS services share one execution role that can read every secret. `catalog-cart` is injected with `LOG_SALT`, which it never uses.
   - The checkout task role holds `ssm:GetParameter` for secrets that ECS already injects through the execution role. Its DynamoDB access is not scoped by key.
   - The `catalog-cart` task role holds X-Ray permissions, but the service has no tracing.
   - The `notify_*` consumers can `PutItem` anywhere in the table.
   - CloudTrail does not validate log files, and the audit bucket accepts plain-HTTP requests.
5. **PCI DSS.** Proposal Appendix D states the scope reduction in one sentence. The SAQ A boundary is not documented.

## Steps (plan first, then code)

### SEC-1 Cognito token lifetime and cached JWKS

- `JwtVerifier._keys()` becomes fail-static: when a refresh after the TTL fails, it keeps serving the cached keys. It raises only when no keys have ever been loaded.
- When a token has an unknown `kid`, the verifier forces one JWKS refresh. Refreshes are limited to one every `JWKS_MIN_REFRESH_SECONDS = 60`, so a flood of tokens with random `kid` values cannot turn into a flood of fetches.
- `algorithms=["RS256"]` stays the only accepted algorithm. Tests pin `alg: none` and HS256 tokens signed with the public key (algorithm confusion).
- Tests ([tests/shared/test_security.py](../../tests/shared/test_security.py)): one fetch across many verifications within the TTL; a refetch after the TTL; stale keys survive a failed refetch; key rotation is picked up; the refetch rate limit holds.
- Terraform regression tests ([tests/infra/test_security_config.py](../../tests/infra/test_security_config.py)) on `modules/identity`: `LITE` tier, access and ID tokens valid for 3 hours, refresh token for 1 day, no client secret, `prevent_user_existence_errors = "ENABLED"`, token revocation enabled, and only the three planned auth flows.

### SEC-2 HMAC webhook, 300-second drift

- `signing.sign` and `signing.verify` refuse an empty secret (`SignatureError("webhook secret not configured")`), so a missing secret fails closed with 401.
- `verify` compares bytes and treats a non-ASCII `v1` as a bad signature (401, not 500). Header parts are stripped, so `t=..., v1=...` parses.
- Boundary tests: `|now - t| = 300` is accepted; 301 seconds in the past or the future is rejected.
- `sim_gateway.py` gains `--stale` (signs with `t = now - 301`) and `--tamper` (signs, then changes `amount` in the sent body). Both expect 401, just like `--bad-signature`. The three attack flags are mutually exclusive. The exit status is now 0 when the response matches what was expected (200 for a valid event, 401 for an attack flag), so `--bad-signature` exits 0 on a correct rejection. The pure helpers `stale_now()` and `tamper()` are unit-tested.
- Checkout `create_app` fails at startup if `WEBHOOK_SECRET` or `LOG_SALT` is empty. The task then fails its health check, and the ECS deployment circuit breaker rolls back. It never serves with a forgeable key.

### SEC-3 PDPA log audit

Audit of every log call site (2026-11-02):

| Source | Events | Customer identity | Verdict |
|---|---|---|---|
| `services/checkout/app.py` | `http_request`, `webhook_signature_failure`, `payment_event_accepted`, `enqueue_failed`, `order_transition` | `customerRef` only; the path holds `orderId`, never the query string or headers | OK |
| `services/catalog_cart/app.py` | `http_request`, `cart_merged` | none (line count only) | OK |
| `functions/order_worker/handler.py` | `order_transition`, `duplicate_ignored`, `late_payment`, `noop_*`, `poison_message` | none; `poison_message` logs `messageId`, not the body | OK |
| `functions/outbox_relay/handler.py` | `event_published`, `publish_failed` | none | OK |
| `functions/notify_*/handler.py` | `customer_notified`, `fulfilment_requested`, `duplicate_ignored` | `customerRef` from the event | OK |
| `functions/report/handler.py` | `report_written` | output limited to `ALLOWED_FIELDS` | OK |
| X-Ray annotations | `orderId`, HTTP status | none | OK |

Controls added:

- An AST regression test scans each `log.*(..., extra={"fields": ...})` call in `services/` and `functions/`. It fails if a field is named `customerId`, `sub`, `email`, `token`, `authorization`, `password`, `body` or `payload`.
- A runtime test ([tests/services/test_pdpa_logging.py](../../tests/services/test_pdpa_logging.py)) drives checkout, an order read, the webhook (valid and forged) and demo pay with a real bearer token. It asserts that no log record contains the token, the raw `sub` or the webhook body.
- `catalog-cart` no longer receives `LOG_SALT` (data minimisation: a secret it does not use).
- Retention is unchanged: service and function log groups keep logs for 1 day, carts and events expire by TTL, and everything is destroyed at teardown.

### SEC-4 IAM least privilege

[modules/compute](../../infra/terraform/modules/compute/main.tf):

- Per-service execution roles (`chopee-<service>-execution`). Each reads only the SSM parameters its own container injects: checkout reads the webhook secret and log salt; catalog-cart reads none. The `ssm_parameter_arns` module input is removed.
- Checkout task role: drop `ssm:GetParameter` and the unused `WEBHOOK_SECRET_PARAM` variable. `GetItem` is limited to `ORDER#*` leading keys and the GSI1 `Query` to `CUSTOMER#*`, using `dynamodb:LeadingKeys` like catalog-cart already does.
- X-Ray permissions go to checkout only.

[modules/functions](../../infra/terraform/modules/functions/main.tf): the `notify_*` consumer `PutItem` is limited to `CONSUMED#*` leading keys.

### SEC-5 CloudTrail integrity

[modules/observe/audit.tf](../../infra/terraform/modules/observe/audit.tf): `enable_log_file_validation = true` (SHA-256 digest files make tampering detectable), and the audit bucket policy denies requests where `aws:SecureTransport = false`. The bucket keeps `force_destroy = true` and no Object Lock, so teardown is unchanged.

### SEC-6 PCI DSS SAQ A boundary

| Element | In ChopeE | Why |
|---|---|---|
| Card number, CVV, expiry | Never | The enterprise flow redirects to the gateway's hosted payment page; the demo has no card fields at all (`/api/demo/pay` stands in for the hosted page) |
| Payment outcome webhook (`eventId`, `orderId`, `outcome`, `amount`, `currency`) | Yes | Contains no cardholder data; authenticated with HMAC-SHA256 and a 300-second replay window |
| Storefront page that links to the payment page | Yes | SAQ A still covers the integrity of the page that redirects (scripts served from S3 through CloudFront under Terraform control) |
| Gateway account and webhook secret | Yes | The secret is an SSM `SecureString` that only the checkout execution role can read |

This reduces scope to SAQ A eligibility. It does not by itself make the system compliant: the merchant still attests annually, and the enterprise design adds WAF and script-integrity controls on the redirecting page.

## Verification

- `pytest` passes locally (the new tests are in `tests/shared/test_security.py`, `tests/services/test_pdpa_logging.py` and `tests/infra/test_security_config.py`).
- `cd infra/terraform && terraform fmt -check -recursive && terraform init -backend=false && terraform validate`.
- At the next M6 smoke run (needs operator approval):
  - `GET /api/orders` and `GET /api/orders/{id}` return 200 under the scoped checkout role. This proves `LeadingKeys` on the GSI1 `Query`.
  - `sim_gateway.py --stale` and `--tamper` each return 401.
  - `aws cloudtrail get-trail-status` shows digest delivery.
- Commit directly to `main` per AGENTS.md.
