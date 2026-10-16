# 03 — Data, Cart, and Orders

Implement the [proposal](../proposal.md) demo flow using DynamoDB on-demand. Key schema, API, message and state-transition contracts are in [plan 06 Section 5](06-demo-build.md#5-contracts); this plan carries the business rules they implement. In the enterprise target, Aurora holds slow-changing data (catalog, profiles, payment ledger) and DynamoDB holds fast-changing data (carts, sessions, stock, orders). Aurora is not a demo dependency.

## Data and cart lifecycle

- Store profiles, catalog, carts, inventory, orders, idempotency records, demo ledger entries and committed notification events in one table. Enable PITR; keep all data in Singapore.
- Use customer-scoped keys and an order-history index. Keyed catalog reads replace Redis in the demo; authoritative inventory is never taken from a cache.
- Guest carts use opaque identifiers and a 24-hour application expiry; TTL provides eventual cleanup, not precise expiry enforcement.
- An authenticated cart-merge route validates guest ownership, combines items deterministically, re-prices from the catalog and atomically records the merge. Retrying the same merge must not add quantities twice. Stock is reserved only at checkout.

## Checkout and inventory

- Require a UUID v4 idempotency token; it becomes the order ID, so the order item is the durable idempotency record. Validate authenticated ownership and request data, check whether the order already exists, then enqueue into high-throughput FIFO; derive the customer group from identity. A replayed token returns the existing order with 200; a token owned by another customer returns 409.
- Return HTTP 202 only after confirmed enqueue. Acceptance means the request is queued, not that inventory or payment has succeeded.
- The worker atomically records idempotency, stock reservation, order state and the committed event. Conditional stock checks prevent overselling; durable idempotency handles duplicates beyond SQS's deduplication window.
- One worker handles order, payment-outcome and expiry messages from the same customer FIFO group, so they run in order. In the target, split a hot SKU's stock into sharded counters, because one item cannot take 500 writes/second. The demo keeps one stock item per SKU, spreads the burst across at least 20 SKUs and proves contention correctness with a 50-unit item under competing buyers.
- Report insufficient stock through order status and customer events. An asynchronous worker cannot change the original accepted HTTP response to 409.

## Simulated payments and notification flow

- Reserved orders become `PENDING_PAYMENT`. Simulate success, decline and expiry; conditional transitions finalize once and release stock once.
- After reserving stock, the worker creates a one-time EventBridge Scheduler schedule that sends an expiry message into the customer's FIFO group 15 minutes later. TTL is not the payment timer. Duplicate and late outcomes cannot double-finalize; a late success is recorded as a reconciliation item for refund handling.
- Successful demo payment writes DynamoDB ledger records. A Streams/outbox relay publishes committed order events with stable event IDs.
- SNS explicitly subscribes logistics and customer-notification Lambda consumers. Both log synthetic outcomes and handle retries idempotently; operational alerts use a separate SNS topic.
- The relay publishes from DynamoDB Streams, so a worker failure after commit cannot lose an event. Consumers ignore repeated event IDs.
- Enterprise hosted sessions, verified webhooks, Aurora reconciliation and real carrier booking remain documented designs. In the demo, a test script posts signed webhooks to the ALB (including duplicates and a bad signature), and the storefront's **Pay/Decline (simulated)** buttons call a demo-only route that signs an event and passes it through the same verification code. No card data is stored.

## Verification

Verify repeat checkout/merge, duplicate payment events, success-versus-expiry races, decline/15-minute stock release, low-stock contention and notification retries locally. In the bounded cloud run, reconcile accepted orders to terminal, pending or DLQ outcomes and prove no duplicate commits or negative inventory. See [operations](04-operations.md) for alarms and failure rehearsal.
