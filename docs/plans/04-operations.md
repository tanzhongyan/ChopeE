# 04 — Operations

## Alarms

- Api5xx: API Gateway 5xx over 2 percent of traffic across 5 minutes, notify SNS on-call.
- QueueAge: SQS ApproximateAgeOfOldestMessage over 60 seconds, notify on-call of downstream delay.
- LambdaHealth: worker errors or throttles above zero across 5 minutes, notify on-call.
- DbThrottles: store ThrottledRequests above zero across 5 minutes, scale keys or throughput narrative.

## Logging and tracing

- Structured JSON logs carry `traceId`, `orderId`, `idemKey`, `customerId`, latency milliseconds, and outcome. X-Ray propagates across API Gateway, ingest, SQS, worker, and DynamoDB.

## Budgets and teardown runbook

- Budget guardrail: total spend at or under the USD 80 cap, which is the only cloud restriction. Owner stops work on breach.
- Teardown: `terraform destroy -auto-approve`, then confirm empty state with `aws dynamodb list-tables`, `aws lambda list-functions`, `aws sqs list-queues`, and `aws apigateway get-rest-apis`, all scoped to `ap-southeast-1`.
