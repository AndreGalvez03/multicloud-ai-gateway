variable "name" { type = string }
variable "enabled" { type = bool }
variable "enable_provisioned_throughput" { type = bool }
variable "model_ids" { type = list(string) }
variable "region" { type = string }
variable "account_id" { type = string }
variable "oidc_provider_arn" { type = string }
variable "oidc_host" { type = string }
variable "kms_key_arn" { type = string }
variable "log_retention_days" { type = number }

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_host}:sub"
      values   = ["system:serviceaccount:aigw:ai-gateway"]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "gateway" {
  name               = "${var.name}-gateway"
  assume_role_policy = data.aws_iam_policy_document.trust.json
}

resource "aws_secretsmanager_secret" "providers" {
  #checkov:skip=CKV2_AWS_57: Rotation is a Lambda in the target account. Terraform does not store the secret value.
  name                    = "${var.name}/providers"
  description             = "Third-party model provider credentials. Value is set out of band."
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = 7
}

data "aws_iam_policy_document" "gateway" {
  statement {
    sid    = "ReadThirdPartyCredentials"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = [aws_secretsmanager_secret.providers.arn]
  }

  dynamic "statement" {
    for_each = var.enabled ? [1] : []
    content {
      sid    = "InvokeApprovedBedrockModels"
      effect = "Allow"
      actions = [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
      ]
      resources = concat(
        [for model in var.model_ids : "arn:aws:bedrock:${var.region}::foundation-model/${model}"],
        ["arn:aws:bedrock:${var.region}:${var.account_id}:provisioned-model/*"],
      )
    }
  }
}

resource "aws_iam_role_policy" "gateway" {
  name   = "gateway"
  role   = aws_iam_role.gateway.id
  policy = data.aws_iam_policy_document.gateway.json
}

resource "aws_cloudwatch_log_group" "bedrock" {
  count             = var.enabled ? 1 : 0
  name              = "/aws/bedrock/${var.name}/invocations"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
}

data "aws_iam_policy_document" "bedrock_logs_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "bedrock_logs" {
  count              = var.enabled ? 1 : 0
  name               = "${var.name}-bedrock-logs"
  assume_role_policy = data.aws_iam_policy_document.bedrock_logs_trust.json
}

resource "aws_iam_role_policy" "bedrock_logs" {
  count = var.enabled ? 1 : 0
  name  = "write"
  role  = aws_iam_role.bedrock_logs[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "WriteInvocationLogs"
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${aws_cloudwatch_log_group.bedrock[0].arn}:*"
    }]
  })
}

resource "aws_bedrock_model_invocation_logging_configuration" "this" {
  count = var.enabled ? 1 : 0

  logging_config {
    embedding_data_delivery_enabled = false
    image_data_delivery_enabled     = false
    text_data_delivery_enabled      = false
    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.bedrock[0].name
      role_arn       = aws_iam_role.bedrock_logs[0].arn
    }
  }
}

resource "aws_bedrock_provisioned_model_throughput" "claude" {
  count                  = var.enabled && var.enable_provisioned_throughput ? 1 : 0
  provisioned_model_name = "${var.name}-claude-sonnet"
  model_arn              = "arn:aws:bedrock:${var.region}::foundation-model/${var.model_ids[0]}"
  commitment_duration    = "OneMonth"
  model_units            = 1
}

output "gateway_role_arn" { value = aws_iam_role.gateway.arn }
output "providers_secret_arn" { value = aws_secretsmanager_secret.providers.arn }
