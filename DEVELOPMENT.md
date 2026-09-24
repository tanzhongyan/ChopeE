# Development

Local setup and workflow for ChopeE contributors. Start with `README.md` for the
project overview, then follow this file to make a change.

## Prerequisites

- Terraform CLI `>= 1.5.0`, AWS CLI v2, Python 3.12.
- AWS credentials for `ap-southeast-1` only during a timed run.

## Trunk flow

- Commit directly to `main`. No branches, no pull requests, no code reviews.
- One concern per commit. Update the governing plan in `docs/plans/` before changing code.

## Terraform sequence (manual CLI only, no code yet)

`infra/terraform/` currently holds only a `.gitkeep` placeholder describing the
planned module layout. When the stack lands, the sequence will be:

```powershell
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform plan -out=tfplan
terraform -chdir=infra/terraform apply tfplan
terraform -chdir=infra/terraform destroy -auto-approve
```

- Never run `apply` unless a timed run is active. Every run ends with `destroy`
  plus the empty-state checks in `README.md`.
- The USD 80 cap is the only cloud restriction.
