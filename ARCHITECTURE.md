# Architecture

The [proposal](docs/proposal.md) defines the enterprise target and bounded demo. Working detail lives in plans [02](docs/plans/02-architecture.md) and [03](docs/plans/03-data-cart-orders.md).

## Demo stack

- CloudFront/S3 deliver static storefront assets; Cognito and API Gateway REST control customer API access.
- ARM64 Python 3.12 Lambda handles carts, checkout, orders and simulated payments without customer VPC attachment.
- High-throughput SQS FIFO sequences orders per customer; repeatedly failing messages move to a DLQ after three failed attempts.
- DynamoDB on-demand stores operational data and the demo ledger, with atomic stock reservation and durable idempotency.
- EventBridge drives 15-minute unpaid-order expiry; committed events reach SNS logistics and customer-notification logging consumers.
- CloudWatch, sampled X-Ray, CloudTrail audit samples and a separate operational SNS subscriber provide evidence and alerts.

The enterprise target adds WAF, private networking, Redis, Aurora/RDS Proxy, dedicated KMS keys and protected seven-year audit retention. Live payment settlement and carrier booking are designed rather than executed.

## Request flow

1. API Gateway validates the authenticated request; ingest validates checkout data.
2. Ingest enqueues into the customer FIFO, then returns HTTP 202 after queue confirmation.
3. A worker atomically reserves stock and writes order/idempotency records; simulated payment outcomes finalize or cancel once.
4. A committed-event relay publishes SNS events for both consumers. DLQ and service alarms notify on-call.

## Region and lifecycle

All regional state and storage stay in `ap-southeast-1`. CloudFront serves only public static content. The demo targets 500 accepted orders/second for 60 seconds and p95 acknowledgement <=200 ms. Each deployment lasts at most five hours, followed by complete teardown. USD 80 caps cumulative project spend.

## Figures

- [Enterprise target](docs/architecture/target_architecture.png)
- [Demo architecture](docs/architecture/demo_architecture.png)
- [Export registry and editable Eraser links](docs/architecture/README.md)
