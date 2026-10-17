# Development

Local setup and workflow for ChopeE contributors. Start with `README.md` for the
project overview, then follow this file to make a change.

## Prerequisites

- Terraform CLI `>= 1.5.0`, AWS CLI v2, Python 3.12, Docker with `buildx` able to build `linux/arm64`, k6.
- Local tests: `python -m pip install -r requirements-dev.txt` then `pytest` (moto emulates DynamoDB, SQS and SNS; no AWS account needed).
- AWS credentials for `ap-southeast-1` only during a timed run.

## Trunk flow

- Commit directly to `main`. No branches, no pull requests, no code reviews.
- One concern per commit. Update the governing plan in `docs/plans/` before changing code.

## Terraform sequence (manual CLI only)

The stack lives in `infra/terraform/`. The sequence is:

```powershell
terraform -chdir=infra/terraform fmt -check
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform plan -target=module.registry -var-file=envs/demo.tfvars -out=tfplan
terraform -chdir=infra/terraform apply tfplan
./scripts/push_images.sh <run_id>
terraform -chdir=infra/terraform plan -var-file=envs/demo.tfvars -out=tfplan
terraform -chdir=infra/terraform apply tfplan
terraform -chdir=infra/terraform destroy -auto-approve -var-file=envs/demo.tfvars
./scripts/verify_empty.sh
```

Full sequence, seeding and smoke test: `docs/plans/06-demo-build.md` Section 6.4. Build order: Section 7.

- Never run `apply` unless a timed run is active. Every run ends with `destroy`
  plus the empty-state checks in `README.md`.
- The USD 80 cap is the only cloud restriction.
