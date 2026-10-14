# 03 — Data, Cart, and Orders

Implement the [proposal](../proposal.md) demo flow using DynamoDB on-demand. In the enterprise target, Aurora holds slow-changing data (catalog, profiles, payment ledger) and DynamoDB holds fast-changing data (carts, sessions, stock, orders). Aurora is not a demo dependency.

## Data and cart lifecycle

- Store profiles, catalog, carts, inventory, orders, idempotency records, demo ledger entries and committed notification events in one table. Enable PITR; keep all data in Singapore.
- Use customer-scoped keys and an order-history index. Keyed catalog reads replace Redis in the demo; authoritative inventory is never taken from a cache.
- Guest carts use opaque identifiers and a 24-hour application expiry; TTL provides eventual cleanup, not precise expiry enforcement.
- An authenticated cart-merge route validates guest ownership, combines items deterministically, re-prices from the catalog and atomically records the merge. Retrying the same merge must not add quantities twice. Stock is reserved only at checkout.

## Checkout and inventory

- Require a UUID v4 idempotency token. Validate authenticated ownership and request data before enqueueing into high-throughput FIFO; derive the customer group from identity.
- Return HTTP 202 only after confirmed enqueue. Acceptance means the request is queued, not that inventory or payment has succeeded.
- The worker atomically records idempotency, stock reservation, order state and the committed event. Conditional stock checks prevent overselling; durable idempotency handles duplicates beyond SQS's deduplication window.
- One worker handles order, payment-outcome and expiry messages from the same customer FIFO group, so they run in order. For a hot SKU, split stock into sharded counters; one item cannot take 500 writes/second.
- Report insufficient stock through order status and customer events. An asynchronous worker cannot change the original accepted HTTP response to 409.

## Simulated payments and notification flow

- Reserved orders become `PENDING_PAYMENT`. Simulate success, decline and expiry; conditional transitions finalize once and release stock once.
- EventBridge-driven due-time checks trigger cancellation after 15 minutes. TTL is not the payment timer. Duplicate and late outcomes cannot double-finalize; late success requires reconciliation.
- Successful demo payment writes DynamoDB ledger records. A Streams/outbox relay publishes committed order events with stable event IDs.
- SNS explicitly subscribes logistics and customer-notification Lambda consumers. Both log synthetic outcomes and handle retries idempotently; operational alerts use a separate SNS topic.
- The relay publishes from DynamoDB Streams, so a worker failure after commit cannot lose an event. Consumers ignore repeated event IDs.
- Enterprise hosted sessions, verified webhooks, Aurora reconciliation and real carrier booking remain documented designs. In the demo, a test script posts the simulated webhook to the ALB, and the checkout service verifies its signature. No card data is stored.

## Verification

Verify repeat checkout/merge, duplicate payment events, success-versus-expiry races, decline/15-minute stock release, low-stock contention and notification retries locally. In the bounded cloud run, reconcile accepted orders to terminal, pending or DLQ outcomes and prove no duplicate commits or negative inventory. See [operations](04-operations.md) for alarms and failure rehearsal.
