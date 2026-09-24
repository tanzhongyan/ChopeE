# AGENTS.md — ChopeE Operating Contract

This file is the agent operating contract. Humans: start with `README.md` and `CONTRIBUTING.md`; come here only if you are operating an agent.

## Stack and region

- Serverless stack: API Gateway REST plus Cognito JWT, SQS FIFO plus DLQ, Lambda ARM64 Graviton2 Python 3.12, DynamoDB on-demand single table, CloudWatch plus X-Ray.
- Single region `ap-southeast-1` only. No multi-region deployment. All state and storage stay in `ap-southeast-1`.

## Budget guardrails

- Total cloud spend strictly at or under USD 80 for active runs only. Stop work on breach of the cap.
- The USD 80 cap is the only cloud restriction. Any AWS service is allowed if the run stays under it.

## Ephemeral lifecycle

- The stack lives at most five hours per test run or evaluation, then `terraform destroy -auto-approve` immediately.
- S3 buckets use `force_destroy = true` so teardown never blocks on a non-empty bucket.

## Manual Terraform only

- Operator runs `terraform fmt -check`, `terraform init`, `terraform validate`, `terraform plan -out=tfplan`, `terraform apply tfplan`, `terraform destroy -auto-approve` from the workstation. No GitHub Actions workflows for infra.

## Doc locations

- Agent behaviour: this file is the only agent contract. A sibling workflow checkout next to the repo (for example `../docs/`) is optional context only — never required, never committed here. On conflict, this file wins.
- Proposal: `docs/proposal.md`. Area plans: `docs/plans/01-scope-feasibility.md` through `05-management.md`.

## Forbidden patterns

- No binaries under `docs/`.
- Never create `docs/superpowers/` or `docs/specs/`. Enforced via both paths in `.gitignore`; Superpowers skills (`brainstorming`, `writing-plans`) default to `docs/superpowers/`, so always override their output paths to `docs/proposal.md` or `docs/plans/`.

## Definition of done

- Plan updated first (`docs/plans/`), placeholder or code follows.
- Every run ends with `terraform destroy -auto-approve` and empty-state verification.
- Trunk-based development: commit directly to `main`. No branches, no pull requests, no code reviews (no live production environment to protect).
