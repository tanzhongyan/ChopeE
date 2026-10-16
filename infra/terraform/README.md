# infra/terraform: ephemeral demo stack

Implements plan 06 Section 6 (M5). Local state only, `ap-southeast-1` only, destroyed after every run. Deploy sequence is plan 06 Section 6.4.

```
cp envs/demo.tfvars.example envs/demo.tfvars   # fill in; git-ignored
terraform fmt -check -recursive && terraform init && terraform validate
terraform plan  -target=module.registry -var-file=envs/demo.tfvars -out=tfplan && terraform apply tfplan
scripts/push_images.sh <run_id>
terraform plan -var-file=envs/demo.tfvars -out=tfplan && terraform apply tfplan
...
terraform destroy -auto-approve -var-file=envs/demo.tfvars
```

## Contracts this code assumes from other tracks

- Functions: `functions/<name>/handler.py` exposing `handler`, for `order_worker`, `outbox_relay`, `notify_logistics`, `notify_customer`, `report`. `terraform plan` fails on `archive_file` until those directories exist.
- Shared layer: zips `shared/` so imports resolve as `chopee.*` (`shared/python/chopee`).
- Services listen on **port 8080**, health check `GET /api/healthz`, run Uvicorn with `UVICORN_WORKERS`.
- Environment variables set by Terraform (code in the other tracks must read these names):
  - Services: `AWS_REGION`, `TABLE_NAME`, `USER_POOL_ID`, `COGNITO_CLIENT_ID`, `COGNITO_ISSUER`, `AWS_XRAY_DAEMON_ADDRESS`, `UVICORN_WORKERS`, secrets `LOG_SALT` (and `WEBHOOK_SECRET` for checkout). Checkout also gets `QUEUE_URL`, `DEMO_GATEWAY=true`, `WEBHOOK_SECRET_PARAM`.
  - `order_worker`: `TABLE_NAME`, `EXPIRY_MINUTES`, `SCHEDULE_GROUP`, `SCHEDULER_ROLE`, `ORDERS_QUEUE_ARN`, `LOG_SALT_PARAM`.
  - `outbox_relay`: `TOPIC_ARN`. Consumers: `TABLE_NAME`. `report`: `REPORTS_BUCKET`, `LOG_GROUPS` (comma separated).
  - All functions: `POWERTOOLS_SERVICE_NAME`, `LOG_LEVEL`.
- Storefront: files in `storefront/` are uploaded as-is; Terraform renders `config.json` (`apiBase="/api"`, same origin through CloudFront). A hand-written `storefront/config.json` is ignored on deploy.

## Deviations from plan 06 Section 6.2

- SSM parameters and the reports bucket live in `modules/data`, and the two order-event SNS subscriptions in `modules/functions`, to avoid circular module wiring. Same resources, different module.
- `/api/webhooks/*` has no `X-Origin-Verify` requirement on the ALB, because `sim_gateway.py` calls the ALB directly from `operator_cidr`. The HMAC signature and the ALB security group protect it.
- The Fargate "running tasks below desired" alarm is a `HealthyHostCount` alarm, because ECS running-task metrics need Container Insights. No alarm exists yet for `WebhookSignatureFailures` (custom EMF metric; namespace is decided by the service code).

## Needs operator input

- `powertools_layer_arn`: look up the current layer version (command in `envs/demo.tfvars.example`).
- Commit `.terraform.lock.hcl` after the first real `terraform init` against the registry.
