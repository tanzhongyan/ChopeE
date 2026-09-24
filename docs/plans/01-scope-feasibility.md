# 01 — Scope and Feasibility

## Geography and boundary

- Headquartered Singapore, serving Singapore 80 percent plus ASEAN spillover 20 percent cross-border from `ap-southeast-1`. No data replication outside the region.
- In scope: Cognito identity, catalog discovery, cart lifecycle, order processing, compliance logging. Tokenized interfaces only for payment settlement and logistics fulfilment.

## Goals G1 to G3

- G1 elastic flash-sale throughput: absorb 1500 TPS bursts, p95 under 1.5 s on checkout mutations, zero dropped valid requests via async 202-on-enqueue plus SQS FIFO buffering.
- G2 sovereignty and PDPA: 100 percent data in `ap-southeast-1`, AES-256 at rest, explicit consent timestamps, immutable 7-year audit trail to S3 Object Lock Governance Mode.
- G3 capital efficiency: spend at or under USD 80 for active runs only; zero idle cost. The USD 80 cap is the only cloud restriction.

## Feasibility and risks

- Fits time, budget, and skills: five bounded contexts, six roles, manual Terraform, local-first development with test runs only.
- Risks: Lambda cold starts (mitigate concurrency tuning on the worker); SQS poison messages (mitigate DLQ with maxReceiveCount 3 plus age alarm); oversell races (mitigate conditional writes plus idempotency guard); budget overrun (stop work on breach of the USD 80 cap).
