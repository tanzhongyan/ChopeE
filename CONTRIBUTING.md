# Contributing to ChopeE

Thanks for contributing. This repo has one rule above all others: **local first, cloud only for timed runs.**

This is a school project. Trunk-based development: commit directly to `main`. No branches, no pull requests, no code reviews.

## Where things live (do not duplicate — link)

- `README.md` — project entry point. Start here.
- `ARCHITECTURE.md` — human-readable stack overview.
- `DEVELOPMENT.md` — local setup, trunk flow, Terraform sequence, verification.
- `docs/proposal.md` — proposal (overall direction and constraints).
- `docs/plans/` — area plans (01 scope, 02 architecture, 03 data/cart/orders, 04 operations, 05 management). Update the plan first, then the code.
- `AGENTS.md` — agent operating contract. Agents read this; humans normally do not need to.

## Ground rules

- Single region `ap-southeast-1` only. All state stays there.
- Total cloud spend at or under USD 80 for active runs. Stop work on breach of the cap. This is the only cloud restriction.
- Each deployment lives at most five hours, then `terraform destroy -auto-approve` immediately plus the empty-state checks in the `README.md` teardown runbook.
- Manual Terraform CLI only from the operator workstation. No CI or CD for infra.

## Workflow

1. Update the governing plan in `docs/plans/` (and `docs/proposal.md` if direction changes) before changing code.
2. Commit directly to `main`, one concern per commit.
3. Do not run `terraform apply` unless a timed test run is active, and destroy immediately afterwards.

## What to touch

- `infra/terraform/` — placeholder for the future Terraform stack (see `infra/terraform/.gitkeep` for the planned module layout: `edge`, `compute`, `database`, `queues`, `observe`). No `.tf` files yet.
- `services/cart`, `services/orders`, `services/inventory` — placeholders for future Lambda handlers (see each folder's `.gitkeep` for the planned contract). No handler code yet.
- `docs/architecture/` — regional diagrams. Re-export the PNGs from Eraser when topology changes, and keep `docs/plans/02-architecture.md` in sync.

## What not to do

- No binaries under `docs/`.
- No secrets in code, tfvars, or logs.
