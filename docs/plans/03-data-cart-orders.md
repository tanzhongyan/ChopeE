# 03 — Data, Cart, and Orders

## Single-table key design

- Partition patterns: `USER#<userId>`, `CART#<userId>`, `GUEST#<uuid>` with 24-hour TTL, `INV#<sku>` with numeric `stock`, `ORDER#<orderId>`, `IDEM#<uuidv4>`, `CONSENT#<userId>`.
- GSI1 `gsi1pk = CUSTOMER#<customerId>`, `gsi1sk = ORDER#<createdAt>#<orderId>` for order-by-customer queries. PITR enabled.

## Anonymous-to-authenticated cart migration

- Guest adds land on `GUEST#<uuid>` with TTL 86400 seconds. On Cognito post-authentication the merge reads guest plus user carts, re-prices lines from the catalog snapshot, then runs one TransactWriteItems: Put merged lines, Delete guest key, Put consent and audit entries. Retry once on TransactionCanceledException, then surface a 409 for the client to retry login merge.

## Idempotent checkout

- Header `Idempotency-Key: <uuidv4>` required. Ingest maps it to `MessageDeduplicationId` and `IDEM#<key>`. The worker guards with `attribute_not_exists(pk)` on the idem item so duplicate deliveries commit exactly one order. Success returns `202 {orderId, status: ACCEPTED}`.

## Inventory conditional decrement

- Worker uses `UpdateItem` with `ConditionExpression = stock >= :qty`. Winners decrement; losers receive `409 CONFLICT` and an SNS fan-out event. Contention fallback is FIFO throttling plus one limited retry with jitter.
