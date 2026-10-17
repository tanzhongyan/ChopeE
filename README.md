# ChopeE — Serverless Shopping Stack

Serverless shopping stack in `ap-southeast-1` under a USD 80 cap for active runs only. Local-first development; cloud resources only during test runs of at most five hours each.

Start here: `ARCHITECTURE.md` (what the stack is), `DEVELOPMENT.md` (how to change it), `CONTRIBUTING.md` (contribution rules). Agents read `AGENTS.md`; proposal lives in `docs/proposal.md`, area plans in `docs/plans/`.

## Layout

- `infra/terraform/` — the ephemeral Terraform stack; `infra/budget/` holds the persistent budget alert. Module layout: [plan 06 Section 6](docs/plans/06-demo-build.md#6-infrastructure-terraform).
- `storefront/`, `shared/`, `services/` (two Fargate services), `functions/` (Lambda handlers), `scripts/`, `loadtest/`, `tests/` — implemented per [plan 06 Section 4](docs/plans/06-demo-build.md#4-repository-layout).
- `docs/proposal.md` — proposal (overall direction and constraints).
- `docs/plans/` — area plans (01 scope, 02 architecture, 03 data/cart/orders, 04 operations, 05 management, 06 demo build, 07 presentation and report). Update the plan first, then the code. To build the demo, start at `docs/plans/06-demo-build.md`.
- `docs/architecture/` — target and demo diagrams plus README. Re-export the PNGs from Eraser when topology changes, and keep `docs/plans/02-architecture.md` in sync.

## How to develop

Follow `DEVELOPMENT.md`. Summary of the rules:

1. Read `docs/proposal.md` and the governing plan in `docs/plans/` before touching code. No code without a linked proposal or plan.
2. Commit directly to `main` (trunk-based, no branches or pull requests), one concern per commit.
3. Keep future modules and services clean and reusable (one concern per module, one handler per directory).
4. Do not run `terraform apply` unless a timed test run is active, and destroy immediately afterwards.

## Timed run

Two stages, because the container images must exist in ECR before the services start (detail: [plan 06 Section 6.4](docs/plans/06-demo-build.md#64-deploy-sequence-one-timed-run)).

```powershell
terraform -chdir=infra/terraform fmt -check
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform plan -target=module.registry -var-file=envs/demo.tfvars -out=tfplan
terraform -chdir=infra/terraform apply tfplan
./scripts/push_images.sh <run_id>
terraform -chdir=infra/terraform plan -var-file=envs/demo.tfvars -out=tfplan
terraform -chdir=infra/terraform apply tfplan
```

Then confirm the ops-alert email subscription, seed the catalog and test users, and run `scripts/smoke.py`.

## Teardown runbook

```powershell
terraform -chdir=infra/terraform destroy -auto-approve -var-file=envs/demo.tfvars
./scripts/verify_empty.sh
```

`verify_empty.sh` checks empty Terraform state, no resources tagged `Project=chopee` (regional and CloudFront), and name-scoped leftovers such as log groups, ECR repositories, Scheduler groups and Cognito pools ([plan 04](docs/plans/04-operations.md#budget-and-teardown)). The AWS Budget in `infra/budget/` is the only resource kept between runs.

Every timed run ends with destroy plus the empty-state checks. S3 buckets carry `force_destroy = true` so teardown never blocks on a non-empty bucket. The USD 80 cap is the only cloud restriction. Full workflow lives in `DEVELOPMENT.md`; architecture overview in `ARCHITECTURE.md`.

## Credits

The storefront screens and cart-merge logic are adapted from AWS's [serverless shopping cart sample](https://github.com/aws-samples/aws-serverless-shopping-cart) (MIT-0).

## Contributing

See `CONTRIBUTING.md`. Licensed under the MIT License — see `LICENSE`.
