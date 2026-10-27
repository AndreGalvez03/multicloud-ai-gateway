output "cluster_name" {
  value = module.eks.cluster_name
}

output "gateway_role_arn" {
  description = "IRSA role the platform service account assumes. Bedrock uses this role; there is no static key."
  value       = module.bedrock.gateway_role_arn
}

output "providers_secret_arn" {
  description = "Secrets Manager secret for third-party provider credentials. The value is not set by Terraform."
  value       = module.bedrock.providers_secret_arn
}

output "providers_secret_name" {
  description = "Set the chart secretsManagerSecret and the ExternalSecret remote key to this. It is $${var.name}/providers."
  value       = module.bedrock.providers_secret_name
}

output "vpc_id" {
  value = module.network.vpc_id
}

output "database_endpoint" {
  value = module.data.endpoint
}
