# ChopeE — Serverless Shopping Stack

Serverless shopping stack in `ap-southeast-1` under a USD 80 cap for active runs only. Local-first development; cloud resources only during test runs of at most five hours each.

Start here: `ARCHITECTURE.md` (what the stack is), `DEVELOPMENT.md` (how to change it), `CONTRIBUTING.md` (contribution rules). Agents read `AGENTS.md`; proposal lives in `docs/proposal.md`, area plans in `docs/plans/`.

## Layout

- `infra/terraform/` — placeholder for the future Terraform stack. Planned modules: `edge`, `queues`, `compute`, `database`, `observe` (see `infra/terraform/.gitkeep`). No `.tf` files yet.
- `services/` — placeholders for future Fargate services and Lambda workers (`cart`, `orders`, `inventory`). Each folder holds a `.gitkeep` describing the planned handler contract. No handler code yet.
- `docs/proposal.md` — proposal (overall direction and constraints).
- `docs/plans/` — area plans (01 scope, 02 architecture, 03 data/cart/orders, 04 operations, 05 management). Update the plan first, then the code.
- `docs/architecture/` — target and demo diagrams plus README. Re-export the PNGs from Eraser when topology changes, and keep `docs/plans/02-architecture.md` in sync.

## How to develop

Follow `DEVELOPMENT.md`. Summary of the rules:

1. Read `docs/proposal.md` and the governing plan in `docs/plans/` before touching code. No code without a linked proposal or plan.
2. Commit directly to `main` (trunk-based, no branches or pull requests), one concern per commit.
3. Keep future modules and services clean and reusable (one concern per module, one handler per directory).
4. Do not run `terraform apply` unless a timed test run is active, and destroy immediately afterwards.

## Timed run

```powershell
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform plan -out=tfplan -var-file=envs/default.tfvars
terraform -chdir=infra/terraform apply tfplan
```

## Teardown runbook

```powershell
terraform -chdir=infra/terraform destroy -auto-approve -var-file=envs/default.tfvars
aws dynamodb list-tables --region ap-southeast-1
aws lambda list-functions --region ap-southeast-1
aws sqs list-queues --region ap-southeast-1
```

Every timed run ends with destroy plus the empty-state checks. S3 buckets carry `force_destroy = true` so teardown never blocks on a non-empty bucket. The USD 80 cap is the only cloud restriction. Full workflow lives in `DEVELOPMENT.md`; architecture overview in `ARCHITECTURE.md`.

## Contributing

See `CONTRIBUTING.md`. Licensed under the MIT License — see `LICENSE`.
