# Proposal architecture diagrams

Canonical Eraser exports for [proposal Section 3](../proposal.md), reviewed on 2026-10-14 ("Second Cut"):

| Figure | Proposal placement | Export | Editable Eraser canvas |
|---|---|---|---|
| 1 — Enterprise target | Section 3.1, before resource explanations | [Target PNG](target_architecture.png) | [Target](https://app.eraser.io/workspace/KOkL8luPYtTwgLwByHjm?diagram=-IuP_kxw8phVSPXFq48JW&layout=canvas) |
| 2 — Demo | Section 3.2, before scope comparison | [Demo PNG](demo_architecture.png) | [Demo](https://app.eraser.io/workspace/KOkL8luPYtTwgLwByHjm?diagram=tBO0dUp-xK1KAJ8gYvZB&layout=canvas) |

The target adds WAF, three AZs with private subnets and NAT, Redis, Aurora/RDS Proxy, KMS, Macie and a seven-year audit archive with analytics. The demo keeps CloudFront/S3, the ALB with two Fargate services, one FIFO queue with one worker, the outbox relay and the two SNS consumers. It replaces enterprise persistence and caching with DynamoDB. Both show FIFO/DLQ, failure isolation and operational alerts.

Eraser handles diagram editing, layout and export. The demo was derived from the target's code. Re-export into these paths when topology changes; keep proposal and plans aligned. The user explicitly approved these two PNGs under `docs/architecture`, overriding the repository's general no-binaries-under-docs rule for these figures. Earlier "First Cut" canvases remain in Eraser for history only.
