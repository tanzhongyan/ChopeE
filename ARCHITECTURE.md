# Architecture

Human-readable overview of the ChopeE stack. Proposal lives in
`docs/proposal.md`; working detail lives in `docs/plans/02-architecture.md`
and `docs/plans/03-data-cart-orders.md`.

## Stack

- API Gateway REST with Cognito JWT authorisation.
- SQS FIFO plus DLQ for order intake buffering.
- Lambda handlers, planned per service (`cart`, `orders`, `inventory`; placeholders only, no code yet).
- Persistent store for carts, orders, inventory, idempotency (implementation to follow the specs; USD 80 cap is the only cloud restriction).
- CloudWatch plus X-Ray for logs, alarms, and tracing.

## Region

Single region `ap-southeast-1` only. All state stays there.

## Request path

1. Client sends authenticated checkout to API Gateway.
2. Ingest Lambda validates JWT and returns `202 ACCEPTED`.
3. Ingest enqueues to SQS FIFO (`MessageGroupId = customerId`).
4. Processing Lambda drains the queue, conditionally writes DynamoDB, and
   publishes to SNS on contention.

## Diagrams

- PNG: `docs/architecture/Architecture.png` with notes in
  `docs/architecture/README.md`.
- Text equivalent: Mermaid block in `docs/plans/02-architecture.md`.
- Keep both in sync when the topology changes.
