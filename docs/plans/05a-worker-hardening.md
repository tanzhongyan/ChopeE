# Owner 3 — Async worker & messaging hardening

Implementation plan for the Owner 3 checklist in [05-management.md](05-management.md).

## Context

The three Owner 3 checks each have a real gap in the current code:

1. **Poison logging.** `models.validate_lines()` ([shared/python/chopee/models.py](../../shared/python/chopee/models.py)) raises a plain `ValueError`. `record_handler` ([functions/order_worker/handler.py](../../functions/order_worker/handler.py)) only logs `poison_message` for `models.InvalidMessage`, so an `ORDER_PLACED` with bad `items` gets retried and reaches the DLQ without a log line. A non-dict line such as `items: [1]` hits `raw.get` and raises `AttributeError`, which is also missed.
2. **FIFO groups.** `SqsFifoPartialProcessor()` uses its default mode: after the first failure, every later record in the batch fails, including records from other customers' groups. Each of those failures increases their `ApproximateReceiveCount`. If a healthy message from customer B lands behind a poison message from customer A three times, it moves to the DLQ (`maxReceiveCount=3`). The only test (`test_fifo_batch_stops_after_first_failure` in [tests/functions/test_order_worker.py](../../tests/functions/test_order_worker.py)) puts every record in one group, so it cannot catch this. `sqs_event()` in [tests/functions/conftest.py](../../tests/functions/conftest.py) also hard-codes a single group.
3. **Concurrency cap.** `worker_max_concurrency` has no `validation` in either [infra/terraform/variables.tf](../../infra/terraform/variables.tf) or [modules/functions/variables.tf](../../infra/terraform/modules/functions/variables.tf). An out-of-range value (AWS allows 2–1000) only fails at `apply`. Nothing stops a cap that is above the worker's reserved concurrency, which brings back throttled receives. Only the tfvars example sets 7.

Goal: close all three gaps with small, idiomatic changes and tests that prove them.

## Steps (in AGENTS.md order: plan doc first, then code)

### 0. Plan docs first

- [06-demo-build.md](06-demo-build.md) §5.4: add that the worker uses `SqsFifoPartialProcessor(skip_group_on_error=True)`, so a failure only blocks the rest of *its own* message group.
- §5.3: note that invalid `items` are an `InvalidMessage`.
- §7.1.1: note that Terraform now rejects `worker_max_concurrency` outside 2–1000 or above a positive reserved concurrency.

### 1. `validate_lines` raises `InvalidMessage`

File: [shared/python/chopee/models.py](../../shared/python/chopee/models.py)

- Swap the three `raise ValueError(...)` for `raise InvalidMessage(...)`.
- Add a guard at the top of the loop: `if not isinstance(raw, dict): raise InvalidMessage("each line must be an object")`, so `AttributeError` can no longer escape.
- Widen the `InvalidMessage` docstring: "Raised for malformed input: unknown/invalid queue messages (→ DLQ) and invalid checkout lines (→ 400)."
- Checkout ([services/checkout/app.py](../../services/checkout/app.py), `/api/checkout`) keeps working because `InvalidMessage` subclasses `ValueError`. As a tidy-up, drop `AttributeError` from its `except` tuple, since it can no longer come from there.
- `handle_order_placed` in the worker: change the comment to `# InvalidMessage -> poison message`.

### 2. Per-group FIFO failure isolation

File: [functions/order_worker/handler.py](../../functions/order_worker/handler.py)

```python
processor = SqsFifoPartialProcessor(skip_group_on_error=True)  # a failure only blocks its own customer group
```

Powertools ≥3.0 is pinned in `requirements-dev.txt`, and the v3 layer supports this. Keep `raise_on_entire_batch_failure = False`. Update the module docstring with one sentence about group isolation.

### 3. Validate `worker_max_concurrency`

- [infra/terraform/variables.tf](../../infra/terraform/variables.tf) (root): add a `validation` block in the style of `operator_cidr`:

  ```hcl
  validation {
    condition     = var.worker_max_concurrency == null || (var.worker_max_concurrency >= 2 && var.worker_max_concurrency <= 1000)
    error_message = "worker_max_concurrency must be null or 2-1000; use about 7 when the account Lambda limit is 10."
  }
  ```

- [infra/terraform/modules/functions/main.tf](../../infra/terraform/modules/functions/main.tf) `aws_lambda_event_source_mapping.worker`: add a `lifecycle { precondition { ... } }` that fails when `worker_reserved_concurrency > 0` and the cap is above it. A cross-variable check belongs on the resource; this works on any Terraform version.
- Keep the default as `null` (account-agnostic). [envs/demo.tfvars.example](../../infra/terraform/envs/demo.tfvars.example) already sets `7` with the `-1` reserved note.

### 4. Tests

- [tests/functions/conftest.py](../../tests/functions/conftest.py) `sqs_event`: add `groups: list[str] | None = None` (one group per body, falling back to `group`). Existing callers don't change.
- [tests/functions/test_order_worker.py](../../tests/functions/test_order_worker.py):
  - Keep `test_fifo_batch_stops_after_first_failure`: in a single group, later records still fail (m1, m2).
  - New `test_fifo_failure_does_not_stall_other_groups`: groups `[a, a, b, a]` with bodies `[placed o1, BAD, placed o2(cust b), placed o3]`. Expect failures `m1, m3` only, with `o2` persisted as `PENDING_PAYMENT`.
  - New `test_invalid_items_log_poison_message(w, capsys)`: `placed()` with `items=[{"sku":"SKU-A","quantity":9}]`. Expect a batch failure and a JSON log line whose `message == "poison_message"`, using the same capsys/JSON pattern as `test_pseudonym_and_logger`.
- [tests/shared/test_lib.py](../../tests/shared/test_lib.py) `test_validate_lines`: assert `models.InvalidMessage` (not just `ValueError`) and add `[1]` / `["x"]` non-dict cases.
- [tests/services/test_checkout.py](../../tests/services/test_checkout.py): make sure an existing invalid-items → 400 test exists. If not, add one with a non-dict line.

### 5. Storefront integration fixes

The worker is asynchronous, so the storefront must follow it. File: [storefront/app.js](../../storefront/app.js)

- Keep polling through `PENDING_PAYMENT` so paid, declined and expired orders appear without a refresh. Re-render only when the status changes, and ignore polls from an earlier `trackOrder`.
- Clear `checkoutKey` and `chopee.localCart` when checkout is accepted.
- Limit local orders and stock to the offline preview (`isOfflinePreview`). A deployed stack shows the error instead.
- Tests: [tests/scripts/storefront_flow.test.js](../../tests/scripts/storefront_flow.test.js) drives the real `app.js` with a stub DOM, fake clock and fake API.

Real stock counts need `GET /api/catalog` to return them. That is the Owner 1 task in plan 05, so a deployed storefront shows in stock or sold out until then.

### 6. Expiry cannot be missed

File: [functions/order_worker/handler.py](../../functions/order_worker/handler.py)

- Create the schedule before the reservation transaction. Reserved stock then always has an expiry, and repeated `CreateSchedule` failures send the message to the DLQ with no stock held.
- An `ORDER_EXPIRE` for an order that does not exist is a no-op, because the schedule can now outlive an order that never reserved. A decline for an unknown order is still poison.
- Trade-offs: a rejected order leaves one schedule that fires and no-ops. If the reservation is retried, the order can expire up to a few minutes before its displayed `expiresAt`, because the first schedule stands.

## Verification

- `ruff check .` and `pytest` both pass locally.
- `cd infra/terraform && terraform fmt -check && terraform init -backend=false && terraform validate`.
- Negative check: `terraform plan -var-file=envs/demo.tfvars -var worker_max_concurrency=1` fails on the validation message. `-var worker_reserved_concurrency=5 -var worker_max_concurrency=7` fails on the precondition. No apply is needed, so there is no cloud spend.
- Optional, during the next M6/M7 run: `scripts/inject_poison.py` produces a `poison_message` line in CloudWatch, and healthy orders from other customers in the same batch are not redelivered (DLQ depth = 1).
- Commit directly to `main` per AGENTS.md.
