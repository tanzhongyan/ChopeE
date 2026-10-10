# 02 — Architecture

Aligned with the current proposal on 2026-10-10. The [proposal](../proposal.md) is the scope authority. The full design is documented; only its explicitly bounded demo is provisioned.

### 3.1 Resource Allocation Justification & Linkages

The architecture separates presentation/ingress, application processing, and persistence into three tiers. Security and observability support all three. All regional resources and customer data remain in `ap-southeast-1`; CloudFront caches only public static assets, while customer-specific APIs use the regional endpoint without edge caching.

**Insert Figure 1 here, before the resource explanations: Full enterprise target architecture.** Private subnets and enterprise services are designed here but not provisioned for the demo.

![Figure 1 — Full enterprise target architecture, rendered by Eraser](../architecture/target_architecture.png)

**Edge & Ingress (S3, CloudFront, WAF, API Gateway, Cognito):** CloudFront serves images, CSS, and JavaScript bundles from a private S3 origin using Origin Access Control. AWS WAF protects the regional REST API against common Layer-7 attacks and rate-based abuse. API Gateway validates schemas and uses a Cognito User Pool authorizer before invoking Lambda. Native Lambda integration works with VPC-attached functions; this path does not require a VPC Link. HTTPS is enforced, with TLS 1.3 for supported viewer connections and supported TLS on internal connections.

**Compute & Private Networking (Lambda, VPC, ElastiCache Redis):** Lambda ARM64 functions run without public IPs in private subnets across three AZs. Security groups restrict database/cache access, NACLs provide subnet perimeter controls, and route tables use free S3/DynamoDB gateway endpoints plus paid interface endpoints for required services such as SQS, SNS, Secrets Manager, and telemetry. Those managed services remain regional services outside the subnet boundary. Controlled NAT egress supports external payment calls in the full design. VPC/subnets themselves have no usage charge; NAT and interface endpoints add cost.

Catalog reads and cart updates use separate routes from checkout writes. ElastiCache caches hot catalog items and promotions with invalidation or short expiry. Durable carts remain in DynamoDB, and Cognito tokens avoid a mandatory Redis session store. CloudFront and Redis cache different workloads: static edge caching does not replace backend caching, and cached stock is never authoritative for checkout.

**Queue Decoupling (SQS FIFO + DLQ):** Ingest Lambda derives `MessageGroupId` from the authenticated customer identity and uses the UUID token as `MessageDeduplicationId`. It returns `202 Accepted` only after SQS confirms enqueue. Enable high-throughput FIFO with `DeduplicationScope=messageGroup` and `FifoThroughputLimit=perMessageGroupId`. Normal FIFO supports 300 non-batched API transactions/second; batching and high-throughput mode raise capacity. Singapore currently supports up to 9,000 non-batched transactions/second per action in high-throughput mode, subject to account quotas and sufficient customer groups. There is no separate activation fee; normal request charges apply. Each customer's messages stay sequential while other customers progress in parallel.

Limit worker concurrency to protect the store. Visibility timeout is at least six times the worker timeout plus any batching window. Partial batch responses preserve FIFO order by stopping at the first failure and retrying failed/unprocessed messages. A FIFO DLQ isolates repeatedly failing messages with `maxReceiveCount=3`; its CloudWatch alarm pages on-call. Other customer groups continue during retries; later messages in the failing group progress after isolation. Operators reconcile the affected order before redrive because moving it to the DLQ breaks the original sequence.

**Persistence & Connection Management (DynamoDB, Aurora Serverless v2, RDS Proxy):** DynamoDB on-demand holds profiles, carts, catalog, inventory, order state, and idempotency records. One `TransactWriteItems` conditionally reserves stock and writes the order, idempotency record, and outbox event together. Keyed catalog reads and order-history GSIs support read traffic; immediate order-status reads use the base table with strong consistency. Guest-cart expiry is enforced by the application because TTL deletion is asynchronous.

Aurora PostgreSQL provides a relational payment ledger for reconciliation/reporting. A writer and failover reader span AZs; the initial range is 0.5–16 ACUs per instance. RDS Proxy pools Lambda connections. Supported Aurora versions can pause at 0 ACUs, but storage charges remain and RDS Proxy prevents auto-pause. The demo therefore replaces this tier for cost and scope reasons, rather than claiming Aurora cannot fit within USD 80.

A DynamoDB Streams-triggered outbox relay processes committed events, applies idempotent ledger records to Aurora, and publishes notifications to SNS. Retries and reconciliation handle partial progress; a DynamoDB update and Aurora write are not one atomic transaction. In the demo, ledger entries join the DynamoDB transaction, avoiding a second database.

**Payment & Notification Linkage:** Real payment settlement is designed, not implemented. The full flow reserves inventory, records `PENDING_PAYMENT`, and creates a hosted gateway session with an order-based idempotency key. A dedicated webhook Lambda verifies provider signature, timestamp, event ID, amount, currency, and order reference before enqueueing a payment event into the customer FIFO. Provider authentication replaces Cognito on this webhook route. An EventBridge scheduled expiry Lambda queries a due-time index and enqueues cancellation commands after 15 minutes; TTL is not the timer. Conditional state transitions prevent both success and cancellation finalizing an order and release stock once. Late payment enters refund/reconciliation handling. Gateway calls have timeouts and bounded retries. Hosted payments reduce card-data exposure without establishing PCI-DSS compliance by themselves.

SNS has explicit subscriptions: a logistics Lambda consumes `OrderPaid` fulfilment events, and a customer-notification Lambda consumes order-status events. Stable event IDs make both consumers idempotent; subscription DLQs retain delivery failures. Demo consumers record synthetic fulfilment and confirmation outcomes. Operational alarms use a separate SNS topic with a confirmed on-call subscriber.

**Security & Audit (KMS, CloudTrail, S3):** The full design uses customer-managed KMS keys, least-privilege IAM, encrypted databases/queues, and seven-year S3 Object Lock Governance retention as an internal policy. CloudTrail management events audit infrastructure activity; application code records business audit events separately. Backups remain in Singapore. Availability, RTO, and RPO are design objectives, not short-demo guarantees. PITR recovery includes restoration to a new table and switching application access; Multi-AZ operation does not prove recovery from deletion or a regional outage.


## Diagram creation

- Both figures were created directly through Eraser MCP's manual diagram tool, which does not run Eraser AI. Eraser performs layout, rendering and PNG export.
- The proposal embeds Eraser-exported images from `docs/architecture/` and links to their editable canvases. See [the diagram registry](../architecture/README.md).
- No local drawing scripts, SVG generator or locally authored raster renderer is used.
- Budget reductions and validation: proposal Sections 3.2–3.3. Operational thresholds: proposal Section 5.

## Technical verification references

Official documentation checked on 2026-10-10:

- [FIFO throughput quotas](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html) and [high-throughput settings](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/enable-high-throughput-fifo.html).
- [Lambda SQS configuration](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-configure.html) and [FIFO partial-batch failure handling](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-errorhandling.html).
- [Aurora pause limitations, including RDS Proxy](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2-auto-pause.html).
- [Free gateway endpoints](https://docs.aws.amazon.com/vpc/latest/privatelink/gateway-endpoints.html) and [paid interface endpoints](https://docs.aws.amazon.com/vpc/latest/privatelink/create-interface-endpoint.html).
- [ElastiCache pricing](https://aws.amazon.com/elasticache/pricing/) and [CloudFront pricing options](https://aws.amazon.com/cloudfront/faqs/).
- [Object Lock deletion restrictions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html).

These verify service behaviour, not an account-specific price quote or measured demo outcome. Recheck quotas and the planned Singapore cost estimate before apply.

## Demo scope

Retain CloudFront/S3 in the demo for static storefront delivery, FIFO/DLQ, two SNS consumers, essential CloudWatch alarms, sampled X-Ray and PITR. Enterprise-only: Aurora/Proxy, Redis, private VPC connectivity, WAF, dedicated keys and protected seven-year archive. Use the [demo export](../architecture/demo_architecture.png) and [target export](../architecture/target_architecture.png) as the canonical figures. Eraser remains the diagram editor.

## Validation boundaries

The three tiers, Terraform lifecycle, request-to-notification trace, failure alarms, resource-reduction table and cost record provide evidence for the seven evaluation criteria. The six roles in Section 6 own the work.

**Phase 4 includes a checkout-only test of 500 orders/second for 60 seconds after warm-up**, ramped gradually across at least 1,000 authenticated customer groups with unique tokens and sufficient stock. Record offered/accepted rates, p95/p99 acknowledgement latency, 429/5xx rates, queue age, terminal completion and drain time. Acceptance targets are 500 accepted orders/sec during the burst, p95 acknowledgement ≤200 ms, no unexplained loss/duplicate commits/oversells, and drain within five minutes afterward. Report missed targets openly; duplicates and hot-item contention use separate tests.

For sizing, interpret the 10,000 req/sec peak as total ingress, with Appendix C's read/write approximation yielding 500 checkout writes/sec. The demo does not prove 10,000 checkouts/sec, 1.5 million users, continuous 99.9% availability, or enterprise failover targets. A `202` proves queue acceptance, not completed payment; a later stock failure is reported through order status/events. Real settlement, private networking, Aurora reconciliation, production CDN performance and Multi-AZ failover exercises remain design-only. The demo includes functional CloudFront/S3 delivery.


### Demo cost assumptions

Singapore, USD before tax; 5 hours/session, 4 sessions/month, full teardown. One 60-second 500-orders/sec burst (30,000 orders), 60,000 REST API requests, 1,000 Cognito Lite users per recreated pool, 150,000 ARM64 Lambda calls at 256 MB/200 ms, 600,000 DynamoDB write units (including transactional amplification), 60,000 read units, 120,000 FIFO calls, 30,000 SNS publications, <=1 GB static transfer and bounded telemetry. No free allowances or credits assumed in the base estimate. Approximate transaction subtotal USD 1; allow USD 1–3 for telemetry/storage/transfer and USD 5.50 for Cognito, round to USD 7–10/session. These are modeled quantities, not measurements. Confirm actual request amplification and duration before apply.

WAF example: one ACL + three basic rules, 60,000 inspected requests: (USD 8/730)*5 + USD 0.60*0.06 = USD 0.091/session. Redis example: 2 cache.t4g.micro nodes * USD 0.024 * 5h = USD 0.24. Aurora minimum compute example: writer + reader, 0.5 ACU each * USD 0.20 * 5h = USD 1; excludes proxy/storage/I/O and scaling. These small configurations do not prove 500-orders/sec capacity.

Rates checked 2026-10-10: [WAF](https://aws.amazon.com/waf/pricing/), [Cognito](https://aws.amazon.com/cognito/pricing/), [API Gateway](https://aws.amazon.com/api-gateway/pricing/), [Lambda](https://aws.amazon.com/lambda/pricing/), [Singapore DynamoDB catalog](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonDynamoDB/current/ap-southeast-1/index.json), [Singapore ElastiCache catalog](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonElastiCache/current/ap-southeast-1/index.json), [Singapore RDS catalog](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/ap-southeast-1/index.json).
