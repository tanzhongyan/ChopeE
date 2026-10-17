# Contributing to ChopeE

Thanks for contributing. This repo has one rule above all others: **local first, cloud only for timed runs.**

This is a school project. Trunk-based development: commit directly to `main`. No branches, no pull requests, no code reviews.

## Where things live (do not duplicate — link)

- `README.md` — project entry point. Start here.
- `ARCHITECTURE.md` — human-readable stack overview.
- `DEVELOPMENT.md` — local setup, trunk flow, Terraform sequence, verification.
- `docs/proposal.md` — proposal (overall direction and constraints).
- `docs/plans/` — area plans (01 scope, 02 architecture, 03 data/cart/orders, 04 operations, 05 management, 06 demo build, 07 presentation and report). Update the plan first, then the code.
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

- `infra/terraform/` — placeholder for the ephemeral Terraform stack; module layout in `docs/plans/06-demo-build.md` Section 6. No `.tf` files yet.
- `storefront/`, `shared/`, `services/`, `functions/`, `scripts/`, `loadtest/`, `tests/` — application code, laid out as in `docs/plans/06-demo-build.md` Section 4. Contracts live in that plan's Section 5.
- `docs/architecture/` — regional diagrams. Re-export the PNGs from Eraser when topology changes, and keep `docs/plans/02-architecture.md` in sync.

## What not to do

- No binaries under `docs/`.
- No secrets in code, tfvars, or logs. `envs/demo.tfvars` (operator IP and alert email) and `loadtest/tokens.json` stay local.
- Do not build enterprise-only components (Redis, Aurora, WAF, NAT and the rest of the "Do not build" list in plan 06).
