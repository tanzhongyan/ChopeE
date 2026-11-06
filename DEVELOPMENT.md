# Development

Local setup and workflow for ChopeE contributors. Start with `README.md` for the
project overview, then follow this file to make a change.

## Prerequisites

- Terraform CLI `>= 1.5.0`, AWS CLI v2, Python 3.12, Docker with `buildx` able to build `linux/arm64`, k6.
- Local tests: `python -m pip install -r requirements-dev.txt` then `pytest` (moto emulates DynamoDB, SQS and SNS; no AWS account needed).
- AWS credentials for `ap-southeast-1` only during a timed run.

## Deploying from another account or workstation

Use a fresh checkout and select the team's AWS profile through `AWS_PROFILE`.
Check `aws sts get-caller-identity` before planning or applying. Keep credentials
in the AWS CLI configuration, outside the repository; do not reuse another
account's Terraform state, saved plans, generated storefront config or tokens.

Create a fresh Python 3.12 virtual environment after moving/cloning the project;
virtualenv launchers can contain absolute paths. Install dependencies with
`python -m pip install -r requirements-dev.txt`. Set `PYTHON` to that environment's
Python executable when running the scripts. Image builds use `PYTHON -m pip` by
default; `PIP` remains an optional override for a custom installer executable.

Copy `infra/terraform/envs/demo.tfvars.example` to the ignored `demo.tfvars` and
fill in the team's owner label, alert email, current public IPv4 `/32`, run/image
tag and regional Powertools layer version. The layer ARN's publisher account is
AWS's public layer owner, not the account receiving the deployment. Check the
new account's Lambda/Fargate quotas and CloudFront eligibility using plan 06
Section 7.2. Choose worker concurrency from those limits rather than copying
another account's settings. Set up and verify the separate budget root too.

Use the same image tag for `push_images.sh` and Terraform's `image_tag`;
`run_demo.sh` sets both from `--run-id`. Confirm the alarm-email subscription
after each deployment. Personal variables, state, build artifacts, test tokens
and run evidence stay ignored by Git.

The cleanup checker cross-checks recognized stale tag records against their
service APIs. Confirmed missing resources and inactive ECS records are reported
as metadata, not active leftovers. Unknown resource types, live resources and
lookup/permission errors still fail verification; the checker never deletes.

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
