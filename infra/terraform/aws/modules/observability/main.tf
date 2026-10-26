variable "name" { type = string }
variable "kms_key_arn" { type = string }
variable "log_retention_days" { type = number }
variable "monthly_budget_usd" { type = string }
variable "budget_alert_email" { type = string }
variable "platform_log_group" { type = string }

data "aws_caller_identity" "current" {}

resource "aws_cloudwatch_log_group" "platform" {
  name              = var.platform_log_group
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
}

resource "aws_cloudwatch_log_group" "gateway" {
  name              = "/aigw/${var.name}/gateway"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
}

resource "aws_sns_topic" "alerts" {
  name              = "${var.name}-alerts"
  kms_master_key_id = var.kms_key_arn
}

data "aws_iam_policy_document" "sns" {
  statement {
    sid    = "AllowBudgetsAndCloudWatch"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com", "cloudwatch.amazonaws.com"]
    }
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "alerts" {
  arn    = aws_sns_topic.alerts.arn
  policy = data.aws_iam_policy_document.sns.json
}

resource "aws_cloudwatch_log_metric_filter" "rate_limited" {
  name           = "${var.name}-rate-limited"
  log_group_name = aws_cloudwatch_log_group.platform.name
  pattern        = "{ $.event = \"rate_limited\" }"

  metric_transformation {
    name      = "RateLimited"
    namespace = "AIGW"
    value     = "1"
    unit      = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "budget_blocked" {
  name           = "${var.name}-budget-blocked"
  log_group_name = aws_cloudwatch_log_group.platform.name
  pattern        = "{ $.event = \"budget_blocked\" }"

  metric_transformation {
    name      = "BudgetBlocked"
    namespace = "AIGW"
    value     = "1"
    unit      = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "rate_limited" {
  alarm_name          = "${var.name}-rate-limited"
  alarm_description   = "Teams are receiving HTTP 429 from the gateway"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "RateLimited"
  namespace           = "AIGW"
  period              = 60
  statistic           = "Sum"
  threshold           = 30
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "bedrock_throttle" {
  alarm_name          = "${var.name}-bedrock-throttles"
  alarm_description   = "Bedrock invocation throttles. See docs/runbooks/bedrock-throttling.md."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  metric_name         = "InvocationThrottles"
  namespace           = "AWS/Bedrock"
  period              = 60
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "budget_blocked" {
  alarm_name          = "${var.name}-budget-blocked"
  alarm_description   = "A team was refused because a monthly budget was exhausted"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "BudgetBlocked"
  namespace           = "AIGW"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_budgets_budget" "bedrock" {
  name         = "${var.name}-bedrock-monthly"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  time_period_start = "2026-01-01_00:00"

  cost_filter {
    name   = "Service"
    values = ["Amazon Bedrock"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
    subscriber_sns_topic_arns  = [aws_sns_topic.alerts.arn]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
    subscriber_sns_topic_arns  = [aws_sns_topic.alerts.arn]
  }
}

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = "${var.name}-ai-gateway"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title   = "Gateway 429s"
          region  = data.aws_region.current.name
          metrics = [["AIGW", "RateLimited"]]
          stat    = "Sum"
          period  = 60
        }
      },
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title   = "Budget refusals"
          region  = data.aws_region.current.name
          metrics = [["AIGW", "BudgetBlocked"]]
          stat    = "Sum"
          period  = 300
        }
      }
    ]
  })
}

data "aws_region" "current" {}

output "log_group_arns" {
  value = [
    aws_cloudwatch_log_group.platform.arn,
    aws_cloudwatch_log_group.gateway.arn,
  ]
}
