variable "aws_region" {
  description = "Region for this gateway boundary. An EU boundary is a separate stack."
  type        = string
  default     = "us-east-1"
}

variable "name" {
  description = "Short name used in resource names."
  type        = string
  default     = "aigw"
}

variable "boundary" {
  description = "Data boundary this stack serves: us or eu. EU stacks should set enable_bedrock to false."
  type        = string
  default     = "us"

  validation {
    condition     = contains(["us", "eu"], var.boundary)
    error_message = "boundary must be us or eu."
  }
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "private_subnet_cidrs" {
  type    = list(string)
  default = ["10.40.1.0/24", "10.40.2.0/24"]
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.40.101.0/24", "10.40.102.0/24"]
}

variable "availability_zones" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b"]
}

variable "cluster_version" {
  type    = string
  default = "1.31"
}

variable "node_instance_types" {
  description = "Graviton instances. The gateway is not GPU-bound; model calls go to Bedrock or another provider."
  type        = list(string)
  default     = ["m7g.large"]
}

variable "node_min" {
  type    = number
  default = 2
}

variable "node_desired" {
  type    = number
  default = 2
}

variable "node_max" {
  type    = number
  default = 6
}

variable "enable_bedrock" {
  description = "Attach Amazon Bedrock invoke permissions and optional provisioned throughput."
  type        = bool
  default     = true
}

variable "enable_provisioned_throughput" {
  description = "Purchase one Bedrock provisioned throughput unit. Leave false until the commitment is approved."
  type        = bool
  default     = false
}

variable "bedrock_model_ids" {
  description = "Foundation models the gateway role may invoke. Keep this list tight."
  type        = list(string)
  default = [
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "amazon.titan-embed-text-v2:0",
  ]
}

variable "monthly_bedrock_budget_usd" {
  type    = string
  default = "500"
}

variable "budget_alert_email" {
  description = "Mailbox that receives AWS Budgets notifications. Not a credential."
  type        = string
  default     = "platform-alerts@example.com"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "db_multi_az" {
  type    = bool
  default = true
}

variable "identity_center_instance_arn" {
  description = "IAM Identity Center instance ARN. Set only in the organization management account."
  type        = string
  default     = null
}

variable "identity_store_id" {
  description = "Identity Store ID for the team groups. Set with the instance ARN."
  type        = string
  default     = null
}

variable "team_group_names" {
  type    = list(string)
  default = ["ai-team-payments", "ai-team-growth", "ai-team-platform"]
}
