# 04 — Operations

The [proposal Section 5](../proposal.md#5-monitoring-alerting--observability-operations) sets operational objectives. The thresholds below are initial implementation settings to tune during rehearsal.

## Monitoring

Operational health is managed through structured telemetry and automated threshold alerting. A CloudWatch dashboard shows request acceptance, terminal order outcomes, queue backlog, database contention and notification delivery. A dedicated operational SNS topic has a confirmed on-call subscriber, separate from the order-event consumers.

## Metrics, alarms and response

| Area | Initial alarm threshold | Response / demonstration evidence |
|---|---|---|
| Ingress health | ALB `HTTPCode_Target_5XX_Count / RequestCount >2%` over five minutes using metric math. Track 4xx separately; ordinary validation/authentication failures do not page. | Notify on-call; inspect task health, deployments and quotas. Show an induced failure and error-rate dashboard. |
| Checkout latency | ALB `TargetResponseTime` or custom acknowledgement p95 >200 ms for three consecutive one-minute periods; chart p99 and failed requests too. | Inspect Fargate task count/CPU and SQS calls; compare offered and accepted rates with the Phase 4 target. |
| Fargate health | Service CPU >70% or running tasks below desired for three consecutive one-minute periods. | Check scheduled pre-scaling ran before the burst; inspect task failures. |
| Queue health | `ApproximateAgeOfOldestMessage >60 seconds` for two consecutive one-minute periods; chart visible/in-flight counts. | Inspect worker concurrency, throttles, hot keys and failing groups; measure queue drain after recovery. |
| Order DLQ | `ApproximateNumberOfMessagesVisible >=1` in one one-minute period; source `maxReceiveCount=3`. | Page on-call; inspect/quarantine, fix, reconcile, then deliberately redrive. Show another customer's orders continuing. |
| Lambda health | `Errors >=1` or `Throttles >=1` for two consecutive one-minute periods; duration p95 >80% of configured timeout for three. | Inspect logs/dependencies and tune concurrency within database limits. Inject a failure and verify retries. |
| DynamoDB contention | `ThrottledRequests >=1` for two consecutive one-minute periods. Chart transaction conflicts and inventory rejections separately. | Investigate hot keys/load. Out-of-stock rejection is a business outcome, not an outage. Verify stock never becomes negative. |
| Outbox & notifications | Relay `IteratorAge >60 seconds` for two consecutive one-minute periods; SNS failed notifications >=1 or any relay/subscription DLQ visible count >=1 for one period. | Replay stable event IDs; verify both consumers record one logical outcome. Delivery alone does not prove fulfilment. |
| Enterprise database | Aurora `ACUUtilization >80%` or RDS Proxy `DatabaseConnectionsBorrowLatency >100,000 microseconds (100 ms)` for three consecutive one-minute periods; chart connections/replica lag. | Investigate queries/pooling/ACU limits. Design-only; the demo uses DynamoDB metrics. |

Tune thresholds during Phase 4. Missing data is non-breaching for idle event-driven metrics; the active test runner detects missing requests/completions. Target notification within five minutes of a sustained breach and measure actual alarm/SNS delivery time during rehearsal.

## Logs, traces and audit

Structured JSON logs carry `traceId`, `orderId`, `eventId`, outcome, attempt and elapsed milliseconds. Use a pseudonymous customer reference; exclude card data, tokens, secrets and full customer payloads. ALB access logs, Fargate logs and Lambda logs use short demo retention. In the target, application logs also reach the seven-year S3 archive through Firehose. Record enqueue, reservation, payment/cancellation and consumer completion to reconcile every accepted order to a terminal, pending or DLQ state.

Sample X-Ray traces and instrument AWS SDK calls. Propagate correlation through queue messages and outbox events; asynchronous work may produce linked traces rather than one uninterrupted trace. Counters/reconciliation cover all orders even when traces are sampled. CloudTrail management events capture infrastructure changes, while application audit events capture business activity. Seven-year Object Lock is enterprise-only; demo audit samples remain deletable. A scheduled report Lambda queries CloudWatch Logs Insights off-peak and writes a JSON/CSV summary (orders by outcome, error rate, queue age) to S3. In the target, the report reads logs from S3 instead, so flash-sale volume cannot overload it, and masks PII before writing.

## Phase 4 operational rehearsal

Complete the account preflight in [plan 06](06-demo-build.md#72-account-preflight-once-at-least-a-week-before-m6) first. Validate cart merge, idempotency, stock transactions, payment-state races, expiry and outbox replay locally first. Pre-scale Fargate and preflight ALB/SQS quotas, Lambda concurrency and DynamoDB ramp behaviour before the 500-orders/sec test in [proposal Section 3.3](../proposal.md#33-validation-scope); FIFO high-throughput mode alone cannot remove downstream bottlenecks.

Separately inject duplicate checkout/payment events, late payment, poison messages, subscriber failure and competing buyers of low stock. Demonstrate one logical order/reservation, non-negative inventory, stock release once, retained notification retries and a received DLQ alarm. Exercise the real 15-minute expiry; label any shortened rehearsal timer. PITR is enabled and recovery steps documented. An optional same-region restore test must fit the budget/time limit and remove restored tables/backups afterward; local fault injection does not prove AWS AZ failover.

Stop one checkout task during the burst and record that ECS replaces it while the ALB keeps serving. Save the load summary, dashboard captures, received-alarm timestamps and one correlated order trace; the full evidence list is in [plan 07](07-presentation-report.md#3-evidence-checklist-capture-during-m7m8-and-the-final-run). Record passed/missed targets. Destroy immediately after the run and verify empty state; check cumulative estimated and billed spend before another run.

## Budget and teardown

- USD 80 is the cumulative cap; plan USD 60 of runs and USD 20 contingency. Estimate USD 8–12/session, USD 32–48 for four sessions/month. Check estimated and billed spend before each run; stop on cap breach.
- A persistent AWS Budget (`infra/budget/`, free) emails the team at 50%, 80% and 100% actual and 100% forecast of USD 80. It is the only resource kept between runs.
- The ops-alert email subscription is recreated every run; confirm it right after apply, or alarms will not reach anyone.
- Deploy manually from the workstation: `terraform fmt -check`, `terraform init`, `terraform validate`, `terraform plan -out=tfplan`, then `terraform apply tfplan`. Use local state for the demo; no infrastructure GitHub Actions.
- At most five hours after creation, run `terraform destroy -auto-approve`. Demo S3 uses `force_destroy=true`, with no protected Object Lock versions.
- Verify with `scripts/verify_empty.sh`: `terraform state list` is empty; `aws resourcegroupstaggingapi get-resources --tag-filters Key=Project,Values=chopee` returns nothing in `ap-southeast-1` and (for CloudFront) `us-east-1`; and name-scoped checks for untagged leftovers such as Lambda-created log groups (`/aws/lambda/chopee-*`, `/ecs/chopee-*`), ECR repositories, the `chopee-expiry` schedule group and Cognito pools. Resources in scope: ALB and target groups, ECS clusters/services/tasks, ECR repositories/images, VPC and security groups, Cognito pools, Lambda functions/layers, FIFO/DLQs, DynamoDB/restored tables/backups, Streams consumers, SNS subscriptions/topics, EventBridge schedules, CloudFront distributions, S3 objects/versions/buckets, logs, alarms and trails. CloudFront is global; regional checks use `ap-southeast-1`.
- Include CloudFront disable/delete propagation in the five-hour lifecycle; begin teardown early enough to complete it. Confirm no retained project resources or ongoing billable storage before the next run.

## SRE contribution queue — local audit, 2026-10-26

This is a demo-only code/evidence audit, not a new AWS run. The existing Python 3.12 environment passed **113 baseline tests** before changes; after SRE-1 it passes **124 tests**. `terraform fmt -check -recursive` and `terraform validate` pass locally. No Terraform plan, deployment, fault injection, load test or AWS verification was performed. The pre-existing change to `infra/terraform/.terraform.lock.hcl` is outside this work.

Already implemented: six dashboard widgets, 13 alarm resource definitions expanding to 19 alarms with the five configured functions, ops SNS email wiring, Lambda active tracing and a checkout X-Ray sidecar, the k6 burst/contention scripts, smoke/poison/task-stop/cleanup tools, a Logs Insights report Lambda, and a separate budget root. Existence and configuration validity are not live acceptance checks.

Historical files in `evidence/m6-20261025/` are useful but incomplete:

- `k6-summary.json` records 41,905 HTTP 202 checks overall, 29,909 in the 60-second hold (~498.5 accepted/s), hold client p95 ~120.6 ms, and 92 dropped iterations overall. Do not round this into proof of the exact 500-accepted/s target. The saved ALB metrics/screenshots are separate server-side evidence, not the client latency measurement.
- `alarms.json` records an order-DLQ alarm, but `sns-subscriptions.json` records `PendingConfirmation`. Neither proves an email was received. `dlq-attributes.json` records four messages, not their identities.
- Saved reconciliation reports have `ok: true`, but also contain smoke orders and DLQ counts; count-only reconciliation does not identify every accepted checkout. The saved worker mapping is `Disabled`, so it cannot establish the current worker configuration.
- `xray-traces.json` has separate checkout/worker traces without order-ID annotations or checkout SDK subsegments. Current checkout source has no tracing SDK/middleware; merely running the sidecar is not end-to-end application instrumentation.
- No alarm inbox capture, task-stop/replacement timeline, destroy/empty-state transcript or actual-cost record was found in this evidence directory. Normal ECS start/stop events alone do not establish the intended chaos experiment.

### Resolution pass — 2026-10-31

Scope for this pass is **SRE-2, SRE-5, SRE-6 and SRE-7**. All four are local code and test changes; no paid deployment is part of the fix. Each item is closed only when its local regression tests pass and the configuration gates (`terraform fmt/validate/plan`, `pytest`) stay green. A live run is still required to capture the deployment evidence recorded in each row.

SRE-3, SRE-4 and SRE-8 remain open after this pass: SRE-3 and SRE-4 change runtime fault-injection and load-test evidence, and SRE-8 is entirely a live acceptance and cost record.

Work one row at a time. Paths below are repository-relative; cross-owner changes require coordination, not silent edits to their services.

| Task / real problem | Work type and exact files | Visible result and local test | Deployment / evidence still required |
|---|---|---|---|
| **SRE-1 (local implementation complete): bounded Scheduler cleanup wait.** At audit, `verify_empty.sh` treated an asynchronously deleting group as a permanent leftover and never checked its state. | Shell + pytest: `scripts/verify_empty.sh`, `tests/scripts/test_shell_and_loadtest.py`; this plan and `docs/plans/05-management.md`. | Query group names/states before the tagged-resource sweep. Retry only when every remaining group is `DELETING`: at most six polls with 2/4/8/16/30-second backoff (60 seconds of sleeps, plus API execution time). Print `WAIT`, then `ok` only after absence. Active/unknown groups, exhausted retries, API errors and other leftovers must remain failures. Stub AWS/Terraform/sleep in tests; no real waiting or deletion. | Local tests pass. After an approved operator-led destroy, capture the real verifier output; local stubs are not cleanup proof. This check never deletes resources or extends the five-hour lifecycle. |
| **SRE-2 (local implementation complete): prevent misleading cleanup success outside the Scheduler race.** A nonexistent `--tf-dir` skips state checking; the cluster-name filter uses `chopee-` although the cluster is named `chopee`; the report schedule lives in Scheduler's default group. | Shell + pytest: `scripts/verify_empty.sh`, `tests/scripts/test_shell_and_loadtest.py`. Configuration references (read/coordinate only): `infra/terraform/modules/compute/main.tf`, `infra/terraform/modules/functions/main.tf`. | Fail clearly for a bad state directory; detect exact demo cluster and named schedules even if tagging misses them. Add negative CLI tests and API-error tests. Empty local state must never be presented as proof this checkout owns the deployed stack. | Local regression tests; operator confirms account, run and authoritative local state before live read-only verification. Save state-list and resource-check output. |
| **SRE-3: trustworthy poison/DLQ verification and timing.** Smoke currently accepts any existing DLQ message as success; injection/presentation guidance understates the 180-second visibility/retry delay. | Python + pytest + runbook: `scripts/smoke.py`, `scripts/inject_poison.py`, `tests/scripts/test_python_scripts.py`, `docs/plans/07-presentation-report.md`. | Correlate the injected message rather than pass on depth alone; test that a pre-existing unrelated DLQ message cannot pass. Print separate automated, pending/manual and failed results. Explain retry/redrive time separately from alarm evaluation/email time; do not promise two minutes from injection. | Approved fault injection on the operator's deployed stack. Capture injected message identity/timestamp, matching DLQ evidence, alarm history, confirmed subscription and actual received email/time. Do not delete/redrive messages just to inspect them. |
| **SRE-4: make the 500/s result unambiguous.** Generic HTTP success and optional catalog reads are not accepted checkout throughput; drops can miss the offered rate even with zero HTTP failures. | JavaScript + local tests: `loadtest/checkout_burst.js`, `tests/scripts/test_shell_and_loadtest.py`; evidence procedure in `docs/plans/07-presentation-report.md`. | Add checkout-specific accepted/unexpected-status metrics, hold-window accepted rate and dropped-iteration reporting. Locally inspect scenarios and test metric handling without network traffic. Preserve the specified ramp/60-second hold/down shape. | Only run paid k6 load with approval and the operator. Record run ID, UTC hold boundaries, token/user count, six-task pre-scale, offered vs accepted throughput, drops, client p95/p99, aligned ALB p95/5xx and queue drain. Reconcile with the data owner using the correct accepted baseline and identified test poisons. |
| **SRE-5 (local implementation complete): improve useful monitoring, not widget count.** The dashboard lacks order-outcome/notification series; healthy targets are not ECS desired/running task counts. There are no observability configuration regression tests. | Terraform + pytest: `infra/terraform/modules/observe/dashboard.tf`, `alarms.tf`, `variables.tf`, new `tests/infra/test_observe.py`; coordinate wiring in `infra/terraform/main.tf` if needed. Read metric producers in `functions/order_worker/handler.py` and `services/checkout/app.py`. | Chart existing EMF outcomes with the correct case-sensitive namespace/dimensions, notification failures/DLQ and clear units/rates. Explicitly label healthy-target proxies; do not enable paid telemetry just to obtain task-count metrics. Add configuration assertions and check fmt/validate. | Configuration checks are local, not proof of arriving datapoints or SNS delivery. On an approved deployment capture populated widgets and verify alarm dimensions/actions/thresholds. ECS desired/running counts can be captured separately through the console/API. |
| **SRE-6 (local implementation complete): application trace correlation (cross-owner).** Sidecar/IAM/Lambda active mode exist, but SDK capture and correlation are missing in source. | Python/dependency changes with owners 2/3: `services/checkout/app.py`, `services/checkout/requirements.txt`, `functions/order_worker/handler.py`, `shared/python/chopee/models.py`, `requirements-dev.txt`, `tests/services/test_checkout.py`, `tests/functions/test_order_worker.py`. Terraform tracing settings already exist in compute/functions. | Instrument HTTP and AWS SDK calls; preserve queue trace context and safe order-ID correlation. Local tests assert propagation/annotations and exclude tokens/customer payloads; mock trace exporters. Do not treat a trace string in the body as an automatically linked X-Ray trace. | A fresh deployment/image is required. Save a sampled checkout trace, linked worker trace if asynchronous, and matching order-ID logs. Local trace tests and old trace files cannot prove this. |
| **SRE-7 (local implementation complete): demonstrate checkout-task recovery.** The stop script only requests a stop; it does not verify replacement or continuing traffic. | Shell + pytest: `scripts/stop_checkout_task.sh`, `tests/scripts/test_shell_and_loadtest.py`; procedure/evidence in `docs/plans/07-presentation-report.md`. | First add explicit target selection and local CLI safety tests so the wrong cluster/service cannot be stopped silently. A successful stop command alone must not print recovery success. | Separate explicit approval for the stop during the approved hold. Operator captures task ID/time, desired/running counts, replacement ECS events and ALB/k6 errors/latency through recovery. This is task recovery, not AZ failover. |
| **SRE-8: close live acceptance, evidence and cost records.** Definitions exist; current email delivery, report contents, budget dates/alerts, cleanup and cumulative spend are unverified. | Initially no code: inspect `infra/budget/main.tf`, `infra/budget/README.md`, `scripts/smoke.py`, `scripts/verify_empty.sh`; record results against `docs/plans/06-demo-build.md` M6–M8 and `docs/plans/07-presentation-report.md` Section 3. Keep artifacts in ignored `evidence/<run_id>/` or the team drive. | Mark each result as local automated test, configuration validation, live AWS test, or historical evidence. Record missing/failed targets rather than declaring the milestone complete from script exit status. Correct stale budget documentation only after operator confirmation. | Before any run, agree operator/account/region/state, check cumulative estimated and billed spend against USD 80, and schedule teardown completion within five hours. Confirm the budget's actual period/alerts; it is not a hard spending cutoff. Save screenshots/logs/email, destroy and verifier transcripts, then dated Cost Explorer/billing totals (including untagged/shared charges and reporting lag). Cleanup prevents future resource usage; it never erases charges already incurred. |

### SRE-1 local validation result

Plan updated before implementation. Four of the new regression cases failed against the original checker; all 11 new cases pass after the fix, covering deleting → absent (including tagged groups), still-deleting, empty, active/mixed/unknown/missing-state, API errors before/after waiting and unrelated leftovers.

```bash
# From the repository root. These tests use stub CLIs, not AWS.
.venv/bin/python -m pytest tests/scripts/test_shell_and_loadtest.py -k scheduler -ra
# 11 passed
.venv/bin/python -m pytest -ra
# 124 passed; 16 existing dependency/empty-EMF warnings
bash -n scripts/verify_empty.sh
git diff --check
```

Local syntax/diff checks pass. Terraform formatting and validation passed during the audit; this task changes no Terraform configuration. No direct live invocation of `verify_empty.sh` was made. The separately recorded SRE-2 gaps are now locally implemented. Live cleanup verification, screenshots/transcripts and actual-cost confirmation remain pending with the deployment operator.

### SRE-2/5/6/7 local validation result — 2026-10-31

All four are implemented and locally tested. No AWS deployment, fault injection or load run was performed.

- **SRE-2:** `verify_empty.sh` now exits 2 for a missing `--tf-dir`, matches the exact `/chopee` ECS cluster, and checks the default-group `chopee-report-daily` schedule. New stubbed tests cover the missing directory (no cloud call), a missing option value, exact cluster detection, the report schedule, a Scheduler API error and a generic AWS query error.
- **SRE-5:** the dashboard now charts `OrdersPaid`, `OrdersCancelled`, `OrdersRejected`, `LatePayments`, `NumberOfNotificationsFailed` and the notify DLQ; the Fargate widget is labelled a health proxy; the `ChopeE` EMF namespace is pinned in the function environment. `tests/infra/test_observe.py` parses the HCL widget body and asserts the dashboard/alarm contracts structurally.
- **SRE-6:** checkout adds `aws-xray-sdk`, a trace-header-aware ASGI middleware and `orderId` annotations (never `customerId`); the worker uses Powertools `Tracer`; order messages carry `AWSTraceHeader` built from the active checkout segment (not the raw inbound ALB header), and annotations run in the async request context rather than the threadpool. Tracing is disabled when no daemon is configured, so local tests do not open sockets. Fake-recorder tests cover configuration, annotations, header linking, status capture, disabled transparency and the environment gate. The webhook annotates only after signature verification, and runtime tracing failures are logged through the structured logger, including serialized exception details.
- **SRE-7:** `stop_checkout_task.sh` requires exact targets, then verifies desired/running counts, a new task ARN and the old task reaching `STOPPED` before printing `PASS`. Stubbed tests cover success, unknown cluster/service/task, each individual recovery gate (old task still running, no new task, running below desired), timeout, numeric flag validation, and ECS service/list-tasks/describe-tasks API errors.

Local gates:

```bash
.venv/bin/python -m pytest -q          # 169 passed
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform plan -var-file=envs/demo.tfvars
```

Live evidence still required per row: a real `verify_empty.sh` transcript, populated dashboard widgets, a sampled checkout-to-worker trace, and an ECS task replacement during the load run. Those are operator-led deliverables, not local test claims.
