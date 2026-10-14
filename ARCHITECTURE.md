# Architecture

The [proposal](docs/proposal.md) defines the enterprise target and bounded demo. Working detail lives in plans [02](docs/plans/02-architecture.md) and [03](docs/plans/03-data-cart-orders.md).

## Demo stack

- CloudFront/S3 deliver static storefront assets and route `/api/*` to an Application Load Balancer. Cognito signs customers in; the services check the token.
- Two ECS Fargate services run behind the ALB: catalog/cart and checkout/webhook. They have no 15-minute limit and scale out before a flash sale.
- One SQS FIFO queue orders each customer's messages. A DLQ takes a message after three failed attempts.
- One Lambda worker reserves stock, applies payment outcomes and expires unpaid orders. An outbox relay publishes committed events to SNS logistics and customer-notification consumers.
- DynamoDB on-demand holds catalog, carts, stock, orders, idempotency records and the demo ledger. It uses atomic stock reservation.
- EventBridge sends the 15-minute unpaid-order expiry into the same queue.
- CloudWatch, sampled X-Ray, a scheduled report to S3, CloudTrail audit samples and an operational SNS topic provide evidence and alerts.

The enterprise target adds WAF, Route 53, three AZs with private subnets and NAT, Redis, Aurora/RDS Proxy, dedicated KMS keys, Macie, and a seven-year audit archive with Glue/Athena/QuickSight analytics. Live payment settlement and carrier booking are designed rather than executed.

## Request flow

1. CloudFront routes the API call to the ALB. The checkout service checks the token and the checkout data.
2. The service enqueues into the customer FIFO, then returns HTTP 202 after queue confirmation.
3. The worker atomically reserves stock and writes order and idempotency records. Simulated payment outcomes finalize or cancel once.
4. The outbox relay publishes SNS events for both consumers. DLQ, queue-age and ALB alarms notify on-call.

## Region and lifecycle

All regional state and storage stay in `ap-southeast-1`. CloudFront serves only public static content. The demo targets 500 accepted orders/second for 60 seconds and p95 acknowledgement <=200 ms. Each deployment lasts at most five hours, followed by complete teardown. USD 80 caps cumulative project spend.

## Figures

- [Enterprise target](docs/architecture/target_architecture.png)
- [Demo architecture](docs/architecture/demo_architecture.png)
- [Export registry and editable Eraser links](docs/architecture/README.md)
