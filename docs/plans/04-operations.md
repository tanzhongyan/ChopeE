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

Validate cart merge, idempotency, stock transactions, payment-state races, expiry and outbox replay locally first. Pre-scale Fargate and preflight ALB/SQS quotas, Lambda concurrency and DynamoDB ramp behaviour before the 500-orders/sec test in [proposal Section 3.3](../proposal.md#33-validation-scope); FIFO high-throughput mode alone cannot remove downstream bottlenecks.

Separately inject duplicate checkout/payment events, late payment, poison messages, subscriber failure and competing buyers of low stock. Demonstrate one logical order/reservation, non-negative inventory, stock release once, retained notification retries and a received DLQ alarm. Exercise the real 15-minute expiry; label any shortened rehearsal timer. PITR is enabled and recovery steps documented. An optional same-region restore test must fit the budget/time limit and remove restored tables/backups afterward; local fault injection does not prove AWS AZ failover.

Save the load summary, dashboard captures, received-alarm timestamps and one correlated order trace. Record passed/missed targets. Destroy immediately after the run and verify empty state; check cumulative estimated and billed spend before another run.

## Budget and teardown

- USD 80 is the cumulative cap; plan USD 60 of runs and USD 20 contingency. Estimate USD 8–12/session, USD 32–48 for four sessions/month. Check estimated and billed spend before each run; stop on cap breach.
- Deploy manually from the workstation: `terraform fmt -check`, `terraform init`, `terraform validate`, `terraform plan -out=tfplan`, then `terraform apply tfplan`. Use local state for the demo; no infrastructure GitHub Actions.
- At most five hours after creation, run `terraform destroy -auto-approve`. Demo S3 uses `force_destroy=true`, with no protected Object Lock versions.
- Verify empty Terraform state and absence of project-tagged/name-scoped resources: ALB and target groups, ECS clusters/services/tasks, VPC and security groups, Cognito pools, Lambda, FIFO/DLQs, DynamoDB/restored tables/backups, Streams consumers, SNS subscriptions/topics, EventBridge schedules, CloudFront distributions, S3 objects/versions/buckets, logs, alarms and trails. CloudFront is global; regional checks use `ap-southeast-1`.
- Include CloudFront disable/delete propagation in the five-hour lifecycle; begin teardown early enough to complete it. Confirm no retained project resources or ongoing billable storage before the next run.
