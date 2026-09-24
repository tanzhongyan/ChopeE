# 05 — Management

## Roles across 6 engineers

- Cloud solutions architect: well-architected narrative and presentation. DevOps and IaC engineer: Terraform modules plus remote state. Security and compliance specialist: IAM least privilege plus KMS plus WAF narrative plus PDPA checks. Backend serverless developer: Lambda handlers plus cart merge plus checkout. Data tier architect: single-table schema plus transaction scripts. Observability and SRE engineer: alarms plus logs plus X-Ray plus synthetic load.

## Five phases

- Phase 1 baseline and scope: lock scope, configure repo, set budget guardrail. Phase 2 IaC core and identity: queue skeleton plus identity plus store skeleton. Phase 3 microservices and workflow: handlers plus routes plus merge logic. Phase 4 observability, load, and audit: alarms plus tracing plus local-first validation plus encryption audit. Phase 5 presentation: rehearse plus slides plus live test run then destroy.

## Cadence and budget governance

- Trunk-based development: commit directly to `main`. No branches, no pull requests, no code reviews (no live production environment to protect).
- Short daily check-ins during build weeks; manual-apply gate means no infra changes without an approved `terraform plan` file. Every timed run is followed by immediate destroy; total spend stays at or under the USD 80 cap, which is the only cloud restriction.
