# Terraform

Three roots, none of which is applied from this repository or from CI.

| Root | What it describes |
| --- | --- |
| `aws/` | The platform: VPC, private EKS, RDS Postgres, Bedrock invoke via IRSA, Secrets Manager, CloudWatch, AWS Budgets, IAM Identity Center permission set. |
| `gcp/` | Vertex AI API, a gateway service account, and a Workload Identity pool that trusts the EKS issuer. |
| `azure/` | An EU AI Services account (private endpoint, local auth off, customer-managed key), a `gpt-4o-mini` deployment, and an Entra ID group. |

## Layout per environment

Shared modules live under `aws/modules`. Environment values are tfvars, not copied roots:

```
infra/terraform/aws/envs/dev.tfvars
infra/terraform/aws/envs/prod.tfvars
```

Remote state is an S3 backend with `use_lockfile = true` (Terraform 1.11). `aws/backend.hcl.example` fills in the bucket, key, region, and KMS key. The root has an empty `backend "s3"` block, so `terraform init -backend=false` still works with no AWS account. To use the remote backend later:

```bash
cd infra/terraform/aws
terraform init -backend-config=backend.hcl
# prod uses the same file with key = "aws/prod/terraform.tfstate"
terraform plan -var-file=envs/dev.tfvars
```

GCP and Azure roots take `project_id` and `subscription_id` as required variables. They have no defaults, so a plan cannot accidentally target an example project.

## Validate, do not apply

```bash
make tf-validate
```

That is `terraform fmt` plus `init -backend=false` and `validate` in each root. CI runs the same commands, then tflint and checkov. Nothing here calls `terraform apply`.

## Identity and secrets

- Humans get an IAM Identity Center permission set (`AIGatewayRead`) that can read logs and budgets and is explicitly denied `bedrock:InvokeModel`. The set and the team groups are created only when `identity_center_instance_arn` and `identity_store_id` are set.
- The gateway pod uses IRSA (`system:serviceaccount:aigw:ai-gateway`) to invoke the listed foundation models and to read one Secrets Manager secret. The secret resource has no `secret_string`. A rotation Lambda is account-specific and is intentionally not bundled.
- Third-party API keys are injected with External Secrets. `deploy/examples/external-secret.yaml` is the contract; it is not part of the Helm chart, because the CRD is not installed by this repo.
- EU traffic is a separate stack. See [ADR 0005](../../docs/adr/0005-data-residency.md). `boundary = "eu"` should run with `enable_bedrock = false` so prompts are not handled by a US-region cluster.

## Checkov exceptions

Six checks are skipped on the resource they actually refer to, with the reason in a `#checkov:skip` comment:

- The KMS key policy root statement must use `kms:*` on `*`. Application roles do not.
- The Identity Center read policy uses `cloudwatch:ListMetrics` and `budgets:ViewBudget`, which have no resource ARN, and an account-wide Bedrock deny.
- Secrets Manager rotation is a Lambda in the target account. Terraform does not store the secret value.
- The Azure key is a software RSA key in a private Premium-capable vault. An HSM key is an organization decision, not something this example should pretend to buy.
