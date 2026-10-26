data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

module "network" {
  source = "./modules/network"

  name                 = var.name
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  private_subnet_cidrs = var.private_subnet_cidrs
  public_subnet_cidrs  = var.public_subnet_cidrs
}

module "eks" {
  source = "./modules/eks"

  name                = var.name
  cluster_version     = var.cluster_version
  private_subnet_ids  = module.network.private_subnet_ids
  cluster_subnet_ids  = module.network.private_subnet_ids
  kms_key_arn         = module.network.kms_key_arn
  log_retention_days  = 365
  node_instance_types = var.node_instance_types
  node_min            = var.node_min
  node_desired        = var.node_desired
  node_max            = var.node_max
}

module "data" {
  source = "./modules/data"

  name                      = var.name
  vpc_id                    = module.network.vpc_id
  subnet_ids                = module.network.private_subnet_ids
  allowed_security_group_id = module.eks.cluster_security_group_id
  kms_key_arn               = module.network.kms_key_arn
  instance_class            = var.db_instance_class
  multi_az                  = var.db_multi_az
}

module "bedrock" {
  source = "./modules/bedrock"

  name                          = var.name
  enabled                       = var.enable_bedrock
  enable_provisioned_throughput = var.enable_provisioned_throughput
  model_ids                     = var.bedrock_model_ids
  region                        = data.aws_region.current.name
  account_id                    = data.aws_caller_identity.current.account_id
  oidc_provider_arn             = module.eks.oidc_provider_arn
  oidc_host                     = module.eks.oidc_host
  kms_key_arn                   = module.network.kms_key_arn
  log_retention_days            = 365
}

module "observability" {
  source = "./modules/observability"

  name               = var.name
  kms_key_arn        = module.network.kms_key_arn
  log_retention_days = 365
  monthly_budget_usd = var.monthly_bedrock_budget_usd
  budget_alert_email = var.budget_alert_email
  platform_log_group = "/aigw/${var.name}/platform"
}

module "identity" {
  source = "./modules/identity"

  instance_arn      = var.identity_center_instance_arn
  identity_store_id = var.identity_store_id
  team_group_names  = var.team_group_names
  log_group_arns    = module.observability.log_group_arns
}
