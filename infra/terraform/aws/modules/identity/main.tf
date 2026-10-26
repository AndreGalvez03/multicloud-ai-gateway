variable "instance_arn" {
  type    = string
  default = null
}
variable "identity_store_id" {
  type    = string
  default = null
}
variable "team_group_names" { type = list(string) }
variable "log_group_arns" { type = list(string) }

data "aws_iam_policy_document" "team_read" {
  #checkov:skip=CKV_AWS_356: ListMetrics and budgets ViewBudget have no resource ARN. The Bedrock deny is intentionally account-wide.
  statement {
    sid    = "ReadGatewayOperations"
    effect = "Allow"
    actions = [
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "logs:FilterLogEvents",
      "logs:GetLogEvents",
      "logs:StartQuery",
      "logs:GetQueryResults",
    ]
    resources = concat(var.log_group_arns, [for arn in var.log_group_arns : "${arn}:*"])
  }

  statement {
    sid       = "ListMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:ListMetrics", "cloudwatch:GetMetricData", "cloudwatch:DescribeAlarms"]
    resources = ["*"]
  }

  statement {
    sid    = "ViewBudgets"
    effect = "Allow"
    actions = [
      "budgets:ViewBudget",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "DenyDirectModelInvoke"
    effect = "Deny"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = ["*"]
  }
}

resource "aws_ssoadmin_permission_set" "team" {
  count            = var.instance_arn == null ? 0 : 1
  name             = "AIGatewayRead"
  description      = "Read gateway logs, metrics, and budgets. Model invoke is denied."
  instance_arn     = var.instance_arn
  session_duration = "PT8H"
}

resource "aws_ssoadmin_permission_set_inline_policy" "team" {
  count              = var.instance_arn == null ? 0 : 1
  instance_arn       = var.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.team[0].arn
  inline_policy      = data.aws_iam_policy_document.team_read.json
}

resource "aws_identitystore_group" "team" {
  count             = var.identity_store_id == null ? 0 : length(var.team_group_names)
  identity_store_id = var.identity_store_id
  display_name      = var.team_group_names[count.index]
  description       = "Product team mapped to an AI Gateway virtual-key group"
}
