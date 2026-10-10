# ChopeE: Cloud-Native E-Commerce Platform Architecture Proposal

## 1. Business Context & Strategic Goals

ChopeE operates as an orange e-commerce platform headquartered in Singapore, catering to urban consumers aged 18 to 45 across APAC region with 1.5 million MAU. 80% of active shoppers reside in Singapore, while the remaining 20% are split evenly across Malaysia (6.67%), Thailand (6.67%), and Hong Kong (6.67%).

The platform experiences standard retail workloads throughout the year, but faces hyper-intense, time-limited traffic bursts during major regional shopping festivals (e.g., 9.9, 11.11, 12.12). During these peak events, concurrent checkout traffic surges up to 10,000 req/sec.

Operating traditional always-on infrastructure incurs massive idle costs as servers are overprovisioned, while underprovisioning causes platform crashes, inventory overselling, and lost customer trust. To resolve this, ChopeE adopts a cloud-native, serverless-first architecture governed by three core strategic goals:

- **Resilient performance and rapid recovery:** Protect revenue and customer trust by maintaining 99.9% checkout availability during flash-sale traffic, and recover quickly after infrastructure failures within the defined RTO while meeting the RPO targets for data loss.
- **Consumer Data Sovereignty and PDPA Compliance:** Keep customer data resident in Singapore and auditable, to meet PDPA obligations as a Singapore-registered platform.
- **Capital Efficiency via Serverless Economics:** Maximize operating margins by aligning infrastructure spend directly with real-time transaction volume

## 2. Core Use Cases & System Boundaries

### 2.1 System Boundaries & External Interfaces

The ChopeE platform boundary includes identity management, catalog discovery, shopping carts, order orchestration, and audit logging. External interfaces include:

- **Third-Party Payment Gateways:** Hosted sessions (Credit Cards, PayNow, FPX, PromptPay, FPS) using verified webhooks to keep PCI-DSS scope out of system boundaries.
- **Logistics Aggregators:** Event streams (Amazon SNS) sending fulfillment tasks to regional carriers upon payment confirmation.

### 2.2 Core Use Cases

- **Idempotent Checkout and Queue Decoupling:** API Gateway receives order payloads with UUID v4 tokens, validates requests, enqueues them into Amazon SQS FIFO, and returns an HTTP 202 Accepted response within 200 ms.
- **Atomic Inventory Reservation:** Downstream Lambda workers process SQS messages in batches and reserve inventory via conditional writes in DynamoDB (Stock>=requested_quantity).
- **Tokenized Payment Processing Design:** Workers mark orders PENDING_PAYMENT and create a payment gateway session. Verified webhooks handle responses: on success, ledgers update in Aurora PostgreSQL, status changes to PAID, and Amazon SNS notifies logistics. On failure or a 15-minute timeout, stock is released and the order is cancelled.

## 3. Enterprise Target Cloud Architecture & Resource Allocation

### 3.1 Resource Allocation Justification & Linkages

Three tiers separate presentation, application processing and persistence. Regional resources and customer data stay in Singapore; CloudFront caches public static assets only.

**Insert Figure 1 here: Enterprise target architecture, before the resource explanations.**

![Figure 1 — Enterprise target architecture](architecture/target_architecture.png)

[Edit Figure 1 in Eraser](https://app.eraser.io/workspace/KOkL8luPYtTwgLwByHjm?diagram=W4fkxFui3FWLIoRCyORs&layout=canvas).

- **Presentation & Access — S3, CloudFront, WAF, API Gateway, Cognito:** CloudFront accelerates static storefront delivery. WAF filters web attacks; API Gateway validates requests and Cognito authenticates customers before application access.
- **Application & Caching — Lambda, private VPC, Redis:** Lambda scales processing with demand. Private subnets across three AZs isolate enterprise compute and databases. Redis accelerates hot catalog and promotion reads; DynamoDB retains durable carts and authoritative stock.
- **Order Processing — SQS FIFO, DLQ:** High-throughput FIFO absorbs checkout bursts while preserving each customer's order sequence. Requests receive HTTP 202 after queue acceptance. Repeatedly failing messages move to a DLQ after three failed processing attempts, triggering a CloudWatch alarm.
- **Persistence — DynamoDB, Aurora Serverless v2, RDS Proxy:** DynamoDB stores operational data and atomically reserves stock to prevent overselling. Aurora provides the relational payment ledger; RDS Proxy manages connections during traffic surges.
- **Payments & Notifications:** Hosted payments and verified webhooks are designed; live settlement is outside demo scope. Unpaid orders cancel after 15 minutes and release stock. SNS connects paid orders to a logistics consumer and order-status events to a customer-notification consumer.
- **Security & Operations — KMS, CloudWatch, X-Ray, CloudTrail, S3 Object Lock:** Encryption and least-privilege access protect data. Metrics, traces and audit records support incident response. Seven-year protected audit retention is an internal enterprise policy.

### 3.2 Live Demo Scope & Cost Reductions

The demo retains CloudFront/S3 storefront delivery, authentication, catalog/cart access, guest-cart merge, idempotent checkout, FIFO/DLQ, atomic stock reservation, simulated payment success/decline/expiry and both notification consumers. CloudWatch, sampled X-Ray and DynamoDB PITR support operational evidence. Enterprise services are simplified as follows.

**Insert Figure 2 here: Demo architecture, before the scope comparison.**

![Figure 2 — Demo architecture](architecture/demo_architecture.png)

[Edit Figure 2 in Eraser](https://app.eraser.io/workspace/KOkL8luPYtTwgLwByHjm?diagram=asx0hDIKDjpCdJKaE_oz&layout=canvas).

| Enterprise capability | Demo choice | Reason / boundary |
|---|---|---|
| Aurora + RDS Proxy | DynamoDB ledger records | Avoid a second database and its compute, proxy and storage charges; relational reporting and settlement reconciliation remain design-only. |
| Redis | Direct DynamoDB reads | Avoid cache nodes and configuration; backend cache performance remains design-only. |
| Private VPC connectivity | Lambda without VPC attachment | Avoid paid NAT/interface endpoints; retain authenticated service access. Private subnet isolation remains design-only. |
| WAF | Authentication, validation and API throttling | Simplify scope; web-attack protection remains design-only. Savings are small for short runs. |
| Dedicated KMS keys / protected audit archive | Service-supported encryption and deletable synthetic audit samples | Retain encryption and audit evidence; enterprise key governance and seven-year retention remain design-only. |
| External payment and carrier integrations | Simulated payment events and logging subscribers | Demonstrate order outcomes and notifications without live settlement, bookings or paid SMS. |

**Estimated demo cost:** USD 7–10 for one session; USD 28–40 for four sessions per month. Each session lasts at most five hours, includes one 60-second burst at 500 orders/second (30,000 orders), approximately 60,000 API requests and 1,000 test users, then full teardown. Estimates include bounded telemetry and modest storefront traffic, exclude tax, and assume no free allowances or credits. They are planning estimates, not measured bills.

| Example resource cost avoided | One five-hour session | Four sessions/month |
|---|---:|---:|
| WAF: one ACL, three basic rules, 60,000 requests | ~$0.09 | ~$0.36 |
| Redis: two small cache nodes | ~$0.24 | ~$0.96 |
| Aurora: writer + reader at 0.5 ACU each, compute only | ~$1.00 | ~$4.00 |

Aurora savings exclude proxy, storage/I/O and scaling. Small-node/minimum-capacity examples do not establish peak performance. WAF and Redis reductions primarily simplify the demo. [AWS WAF pricing](https://aws.amazon.com/waf/pricing/); other regional rates and calculation assumptions are recorded in the [architecture notes](plans/02-architecture.md#demo-cost-assumptions).

The **USD 80 cap covers all project runs**, not each month. Budget USD 60 for runs and reserve USD 20 for contingency. Destroy all demo resources and verify empty state after every session; use local Terraform state and deletable audit storage. Apply and teardown remain manual.

### 3.3 Validation Scope

Phase 4 targets **500 accepted checkout orders/second for 60 seconds**, p95 acknowledgement within 200 ms, no duplicate orders or overselling, and queue drain within five minutes. Demonstrate payment expiry, both notification consumers and a received DLQ alarm. This validates a bounded checkout workload; enterprise availability, recovery and production-scale capacity remain design objectives.

## 4. Disaster Recovery & Resiliency Strategy

The platform enforces Multi-AZ redundancy across three Availability Zones (ap-southeast-1a, 1b, 1c).

| Metric / Objective | Target SLA | Implementation Strategy |
|---|---|---|
| Recovery Point Objective (RPO) | ≤ 5 minutes | Continuous DynamoDB Point-in-Time Recovery (PITR); synchronous Multi-AZ storage mirroring and automated Aurora write-ahead log replication. |
| Recovery Time Objective (RTO) | ≤ 15 minutes | Multi-AZ Automated Failover within ap-southeast-1; Aurora Serverless v2 automated Multi-AZ Writer/Reader failover (< 60s), API Gateway/Lambda cross-AZ routing, and SQS queue buffering across 3 AZ. |
| Stateless Regional Redundancy | Cold-Boot / On-Demand | Stateless IaC recovery: Terraform templates and Lambda deployment packages are retained in the repository and, for the enterprise design, in ap-southeast-1 (Singapore). No cross-region mirroring or deployment. |

## 5. Monitoring, Alerting & Observability Operations

CloudWatch tracks service health and order outcomes; a dedicated SNS topic alerts a confirmed on-call subscriber, separate from customer and logistics notifications.

| Area | Alert / operational purpose |
|---|---|
| Ingress | Alert when API 5xx errors exceed 2% over five minutes; track checkout latency against the 200 ms target. |
| Compute & queues | Monitor Lambda errors/throttles; alert when the oldest queued order exceeds 60 seconds. |
| Failed orders | Alert whenever the order DLQ contains a message; inspect and reconcile before replay. |
| Persistence | Track DynamoDB throttling; enterprise monitoring also covers Aurora capacity and RDS Proxy connection pressure. |
| Notifications | Monitor delivery failures so logistics and customer updates are not silently lost. |

Structured logs and sampled X-Ray traces correlate checkout, stock reservation, payment outcomes and notifications without recording sensitive payloads. CloudTrail records infrastructure changes. Target alert delivery within five minutes of sustained breaches; demonstrate failure detection, notification receipt and recovery during rehearsal. Short-lived demo audit samples remain deletable; protected seven-year retention belongs to the enterprise design.

## 6. Cloud Governance & Operations

**Infrastructure as Code (IaC):** 100% of cloud resources are provisioned declaratively via modular HashiCorp Terraform. Direct modifications through the AWS Management Console are blocked by IAM guardrails. Remote state is maintained in an S3 bucket with DynamoDB state locking.

**Workload Distribution Across 6 Engineering Roles:**

- **Cloud Solutions Architect:** Overall Well-Architected design, tier mapping, and presentation delivery.
- **IaC Engineer:** Terraform modules and remote state management.
- **Security & Compliance Specialist:** IAM least-privilege policies, KMS key policies, WAF rules, and PDPA compliance validation.
- **Backend Serverless Developer:** Lambda microservices (Node.js/Python), cart migration logic, and checkout handlers.
- **Data Tier Architect:** DynamoDB schema design, secondary indexes, atomic transaction scripts, and Aurora configurations.
- **Observability & SRE Engineer:** CloudWatch alarms, structured logging standards, X-Ray tracing, and synthetic load testing.

## 7. Appendix

### A. Business requirements

| ID | Business requirement |
|---|---|
| BR1 | Serve customers across Asia-Pacific: 80% Singapore, 20% split evenly across Malaysia, Thailand and Hong Kong (given base requirement) |
| BR2 | Keep the shop available and responsive during flash sales (11.11, 12.12, CNY, Hari Raya), and recover quickly from failures |
| BR3 | Protect customer data and comply with Singapore's PDPA |
| BR4 | Keep costs proportional to traffic, with no paying for idle capacity on quiet days |
| BR5 | Let customers browse, add to cart, check out and pay online |

### B. Technical requirements

Functional requirements (what the system does):

| ID | Requirement | Traces to |
|---|---|---|
| FR1 | Users can register and log in (Cognito) | BR5 |
| FR2 | Guests can add to cart; the cart merges into their account on login without losing items | BR5 |
| FR3 | Customers can browse the catalog, with popular items served from cache | BR2, BR5 |
| FR4 | Checkout accepts orders with an idempotency token so duplicates are never created | BR2, BR5 |
| FR5 | Stock is reserved only if available, so nothing is oversold | BR2, BR5 |
| FR6 | Payment goes through a third-party gateway; unpaid orders cancel after 15 minutes | BR3, BR5 |
| FR7 | Customers get order confirmations and the logistics partner is notified | BR5 |
| FR8 | Every infrastructure change is logged for auditing | BR3 |

Non-functional requirements (how well it performs):

| ID | Requirement | Traces to |
|---|---|---|
| NFR1 | Checkout requests are acknowledged within 200 ms at peak by returning HTTP 202 Accepted, while downstream order and payment processing continues asynchronously. | BR2 |
| NFR2 | Handles at least 500 orders/second during flash sales | BR1, BR2 |
| NFR3 | Runs across 3 AZs; recovers within 15 min (RTO) with at most 5 min of data loss (RPO) | BR2 |
| NFR4 | All data encrypted in transit (TLS) and at rest (KMS); card data never stored | BR3 |
| NFR5 | Customer data stored in Singapore (ap-southeast-1) | BR3 |
| NFR6 | Compute scales to near zero when idle (Lambda, Aurora Serverless) | BR4 |
| NFR7 | Engineers alerted within 5 minutes of errors exceeding 2% or orders queuing over 60 s | BR2 |
| NFR8 | 100% of infrastructure defined in Terraform | BR2, BR3 |

### C. Calculations

**Baseline Assumptions & User Footprint**

Total Capacity: 1.5 Million MAU (Monthly Active Users)

Geographic Distribution:

- Singapore (Primary): 80% = 1,200,000 MAU
- APAC (MY / TH / HK): 20% = 300,000 MAU (100k each)

Engagement Ratio: 20% DAU/MAU

Daily Active Users (DAU) = 1,500,000 × 20% = 300,000 DAU

**Step-by-Step Back-of-the-Envelope Calculations**

Everyday Baseline & Off-Peak Traffic

- User Activity: 30 req/user/day
- Total Daily Volume: 300,000 × 30 = 9,000,000 req/day
- Baseline Average RPS = 9,000,000 requests / 86,400 seconds ≈ 100 RPS
- Off Peak Traffic (3AM–6AM) = 10% of Baseline = 10 RPS

Flash Sale Ingress Peak (11.11 / Midnight Sales)

- Flash Sale Concurrency: 30% of DAU log in concurrently within a 5 minute window.
- Concurrent Flash Users = 300,000 × 30% = 90,000 users
- Peak Activity: 30 req/user within 300 seconds.
- Peak Ingress RPS = 90,000 users × 30 requests / 300 seconds = 2,700,000 / 300 = 9,000 ≈ 10,000 Ingress RPS

Checkout Write Throughput (Order Transactions)

- E-Commerce Funnel Ratio: 20:1 read to write ratio (95% browsing/catalog reads, 5% order writes).
- Target Checkout Write TPS = 10,000 Ingress RPS / 20 = 500 Write TPS
