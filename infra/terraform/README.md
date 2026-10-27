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
- The gateway pod uses IRSA (`system:serviceaccount:aigw:ai-gateway`) to invoke the listed foundation models and to read one Secrets Manager secret. That token's audience is `sts.amazonaws.com`. GCP allows `aigw-eks` and Azure expects `api://AzureADTokenExchange`, so the chart projects one service account token per audience and points `GOOGLE_APPLICATION_CREDENTIALS` and `AZURE_FEDERATED_TOKEN_FILE` at those files. The secret resource has no `secret_string`. A rotation Lambda is account-specific and is intentionally not bundled.
- Third-party API keys are injected with External Secrets. The remote key is `${name}/providers` (output `providers_secret_name`). `deploy/helm/aigw/values-prod.yaml` and `deploy/examples/external-secret.yaml` both use `aigw-prod/providers`. The example is not part of the Helm chart, because the CRD is not installed by this repo.
- EU traffic is a separate stack. See [ADR 0005](../../docs/adr/0005-data-residency.md). `boundary = "eu"` should run with `enable_bedrock = false` so prompts are not handled by a US-region cluster.

## Checkov exceptions

Checkov reports seven skipped checks. Each `#checkov:skip` sits on the resource it refers to:

- `CKV_AWS_356`, `CKV_AWS_111`, and `CKV_AWS_109` on the KMS key policy. The root statement has to be `kms:*` on `*`. Application roles are not granted that.
- `CKV_AWS_356` on the Identity Center read policy. `cloudwatch:ListMetrics` and `budgets:ViewBudget` have no resource ARN, and the Bedrock deny is account-wide.
- `CKV2_AWS_57` on the Secrets Manager secret. Rotation is a Lambda in the target account. Terraform does not store the secret value.
- `CKV_AZURE_112` on the Key Vault key. This example uses a software RSA key. An HSM key is an organization decision.
- `CKV_AZURE_189` on the Key Vault. Public network access is an expression: off when `key_vault_ip_rules` is empty, on when those rules need a public path. Checkov only accepts a literal `false`.
