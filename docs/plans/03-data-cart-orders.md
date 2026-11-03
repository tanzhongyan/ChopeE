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

### Role 4 reconciliation increment — 2026-11-03

Extend `scripts/reconcile.py` and its tests in `tests/scripts/test_python_scripts.py` to report: a `PAID` order without a successful `PAYMENT#` ledger, a successful ledger without an order, any `RECON#` record with `kind=LATE_PAYMENT`, and more orders than the supplied accepted count. The worker has no reconciliation-resolution field, so every recorded late payment remains a discrepancy requiring manual follow-up. Preserve inventory conservation, negative-stock checks, CLI arguments and report fields. Validate locally in the existing `chopee` environment; no AWS calls or worker changes.

Accepted-count comparisons remain aggregate checks over the same test population. DLQ depth is not a count of distinct accepted checkouts; identity-based accounting requires Role 6's accepted-order evidence and is outside this increment.

### Safe catalog seeding — 2026-11-03

Keep product metadata refreshable, but create each `STOCK` record only when its key does not exist, using a conditional `PutItem`. Skip only `ConditionalCheckFailedException`; other database errors must still fail the run. Reruns preserve the entire existing stock record, including `available` and `initial`. Keep CLI arguments and `--dry-run` unchanged; the normal completion count reports records actually written. Verify fresh seeding, repeated seeding, stock preservation after a simulated purchase (including sold-out stock), error propagation and dry-run behaviour locally with Moto in the existing `chopee` environment. No real AWS calls or changes to worker, checkout, frontend or API code.

### Role 4 concurrency and idempotency verification — 2026-11-03

Add one parametrized regression in `tests/functions/test_order_worker.py`: 60 distinct one-unit orders against 50 units, delivered once or twice, with 12 worker requests overlapping at reservation transaction entry. Require 50 reserved units, 10 out-of-stock orders, one order/outbox event per distinct order, zero final stock and non-negative committed stock after every transaction. Keep production worker logic unchanged.

Moto is not concurrency-safe ([FAQ](https://docs.getmoto.org/en/latest/docs/faq.html)); execute its actual conditional transactions on the main test thread. Preload catalog/salt, stub Scheduler setup, propagate worker exceptions and bound waits. This assumes a serializable storage boundary; real DynamoDB conflicts/retries, Lambda/SQS delivery, payment/expiry overlap and load performance remain live-test work. The existing stock-contention and payment/expiry tests use sequential calls.

Local validation: `python -m pytest -p no:cacheprovider -o addopts='' -q tests/functions tests/services tests/scripts/test_python_scripts.py` passed **128 tests**, including both new cases, using Moto/fake credentials without live AWS calls.
