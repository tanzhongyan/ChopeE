# Proposal architecture diagrams

Canonical Eraser exports for [proposal Section 3](../proposal.md), reviewed on 2026-10-10:

| Figure | Proposal placement | Export | Editable Eraser canvas |
|---|---|---|---|
| 1 — Enterprise target | Section 3.1, before resource explanations | [Target PNG](target_architecture.png) | [Target](https://app.eraser.io/workspace/KOkL8luPYtTwgLwByHjm?diagram=W4fkxFui3FWLIoRCyORs&layout=canvas) |
| 2 — Demo | Section 3.2, before scope comparison | [Demo PNG](demo_architecture.png) | [Demo](https://app.eraser.io/workspace/KOkL8luPYtTwgLwByHjm?diagram=asx0hDIKDjpCdJKaE_oz&layout=canvas) |

The target includes enterprise private networking, Redis and Aurora/RDS Proxy. The demo retains CloudFront/S3 and the serverless checkout flow, replacing enterprise persistence/caching with DynamoDB and direct reads. Both show high-throughput FIFO, failure isolation, logistics/customer consumers and operational alerts.

Eraser handles diagram editing, layout and export. Re-export into these paths when topology changes; keep proposal and plans aligned. The user explicitly approved these two PNGs under `docs/architecture`, overriding the repository's general no-binaries-under-docs rule for these figures. The obsolete single architecture image and separate output directory are removed.
