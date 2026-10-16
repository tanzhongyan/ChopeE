# Budget root

Applied once per project and kept (budgets are free). Not part of the ephemeral stack or `verify_empty.sh`.

```
cp terraform.tfvars.example terraform.tfvars   # edit values
terraform init && terraform validate && terraform plan -out=tfplan && terraform apply tfplan
```

Not yet validated or applied: the Stage 0 session had no Terraform binary, registry access or working AWS keys.
