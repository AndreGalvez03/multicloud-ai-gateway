terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.14"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = true
    }
  }
  subscription_id = var.subscription_id
}

provider "azuread" {}

data "azurerm_client_config" "current" {}

variable "subscription_id" {
  description = "Azure subscription for the AI Foundry account. Supplied at plan time, not committed."
  type        = string
}

variable "name" {
  type    = string
  default = "aigw"
}

variable "location" {
  description = "EU region for teams whose residency tag is eu."
  type        = string
  default     = "westeurope"
}

variable "eks_oidc_issuer" {
  description = "EKS OIDC issuer URL, including https://, for the gateway federated credential."
  type        = string
}

variable "key_vault_ip_rules" {
  description = "CIDRs allowed through the Key Vault firewall. Public access stays off when this is empty, so only the private endpoint works. A non-empty list turns public access on and these rules are the allow list."
  type        = list(string)
  default     = []
}

resource "azurerm_resource_group" "ai" {
  name     = "${var.name}-rg"
  location = var.location
}

resource "azurerm_virtual_network" "ai" {
  name                = "${var.name}-vnet"
  address_space       = ["10.50.0.0/16"]
  location            = azurerm_resource_group.ai.location
  resource_group_name = azurerm_resource_group.ai.name
}

resource "azurerm_network_security_group" "endpoints" {
  name                = "${var.name}-endpoints"
  location            = azurerm_resource_group.ai.location
  resource_group_name = azurerm_resource_group.ai.name

  security_rule {
    name                       = "https-from-vnet"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "VirtualNetwork"
  }
}

resource "azurerm_subnet" "endpoints" {
  name                 = "private-endpoints"
  resource_group_name  = azurerm_resource_group.ai.name
  virtual_network_name = azurerm_virtual_network.ai.name
  address_prefixes     = ["10.50.1.0/24"]
}

resource "azurerm_subnet_network_security_group_association" "endpoints" {
  subnet_id                 = azurerm_subnet.endpoints.id
  network_security_group_id = azurerm_network_security_group.endpoints.id
}

resource "azurerm_key_vault" "ai" {
  #checkov:skip=CKV_AZURE_189: Public access is on only when key_vault_ip_rules is non-empty, so those firewall rules apply. The default list is empty and public access stays off.
  name                          = "${replace(var.name, "-", "")}kv"
  location                      = azurerm_resource_group.ai.location
  resource_group_name           = azurerm_resource_group.ai.name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  purge_protection_enabled      = true
  soft_delete_retention_days    = 90
  public_network_access_enabled = length(var.key_vault_ip_rules) > 0
  rbac_authorization_enabled    = true

  network_acls {
    default_action = "Deny"
    bypass         = "AzureServices"
    ip_rules       = var.key_vault_ip_rules
  }
}

resource "azurerm_private_endpoint" "vault" {
  name                = "${var.name}-vault"
  location            = azurerm_resource_group.ai.location
  resource_group_name = azurerm_resource_group.ai.name
  subnet_id           = azurerm_subnet.endpoints.id

  private_service_connection {
    name                           = "vault"
    private_connection_resource_id = azurerm_key_vault.ai.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "vault"
    private_dns_zone_ids = [azurerm_private_dns_zone.vault.id]
  }
}

resource "azurerm_role_assignment" "deployer_keys" {
  scope                = azurerm_key_vault.ai.id
  role_definition_name = "Key Vault Crypto Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_key_vault_key" "foundry" {
  #checkov:skip=CKV_AZURE_112: A Premium HSM key is an organization decision. This example uses a software RSA key in a private vault.
  name         = "foundry"
  key_vault_id = azurerm_key_vault.ai.id
  key_type     = "RSA"
  key_size     = 2048
  key_opts     = ["wrapKey", "unwrapKey"]

  expiration_date = "2027-12-31T00:00:00Z"

  rotation_policy {
    automatic {
      time_before_expiry = "P30D"
    }
    expire_after         = "P12M"
    notify_before_expiry = "P30D"
  }

  depends_on = [azurerm_role_assignment.deployer_keys]
}

resource "azurerm_cognitive_account" "foundry" {
  name                          = "${var.name}-foundry"
  location                      = azurerm_resource_group.ai.location
  resource_group_name           = azurerm_resource_group.ai.name
  kind                          = "AIServices"
  sku_name                      = "S0"
  custom_subdomain_name         = "${var.name}-foundry"
  public_network_access_enabled = false
  local_auth_enabled            = false

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_role_assignment" "foundry_key" {
  scope                = azurerm_key_vault.ai.id
  role_definition_name = "Key Vault Crypto Service Encryption User"
  principal_id         = azurerm_cognitive_account.foundry.identity[0].principal_id
}

resource "azurerm_cognitive_account_customer_managed_key" "foundry" {
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  key_vault_key_id     = azurerm_key_vault_key.foundry.id

  depends_on = [azurerm_role_assignment.foundry_key]
}

resource "azurerm_cognitive_deployment" "gpt" {
  name                 = "gpt-4o-mini"
  cognitive_account_id = azurerm_cognitive_account.foundry.id

  model {
    format  = "OpenAI"
    name    = "gpt-4o-mini"
    version = "2024-07-18"
  }

  sku {
    name     = "Standard"
    capacity = 10
  }
}

resource "azurerm_private_endpoint" "foundry" {
  name                = "${var.name}-foundry"
  location            = azurerm_resource_group.ai.location
  resource_group_name = azurerm_resource_group.ai.name
  subnet_id           = azurerm_subnet.endpoints.id

  private_service_connection {
    name                           = "foundry"
    private_connection_resource_id = azurerm_cognitive_account.foundry.id
    subresource_names              = ["account"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name = "foundry"
    private_dns_zone_ids = [
      azurerm_private_dns_zone.openai.id,
      azurerm_private_dns_zone.cognitive.id,
    ]
  }
}

resource "azuread_group" "payments" {
  display_name     = "ai-team-payments"
  security_enabled = true
  description      = "Product team allowed to use the EU deployment through the gateway."
}

resource "azurerm_user_assigned_identity" "gateway" {
  name                = "${var.name}-gateway"
  location            = azurerm_resource_group.ai.location
  resource_group_name = azurerm_resource_group.ai.name
}

resource "azurerm_federated_identity_credential" "eks" {
  name                = "eks"
  resource_group_name = azurerm_resource_group.ai.name
  parent_id           = azurerm_user_assigned_identity.gateway.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = var.eks_oidc_issuer
  subject             = "system:serviceaccount:aigw:ai-gateway"
}

resource "azurerm_role_assignment" "gateway_openai" {
  scope                = azurerm_cognitive_account.foundry.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.gateway.principal_id
}

resource "azurerm_private_dns_zone" "openai" {
  name                = "privatelink.openai.azure.com"
  resource_group_name = azurerm_resource_group.ai.name
}

resource "azurerm_private_dns_zone" "cognitive" {
  name                = "privatelink.cognitiveservices.azure.com"
  resource_group_name = azurerm_resource_group.ai.name
}

resource "azurerm_private_dns_zone" "vault" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = azurerm_resource_group.ai.name
}

resource "azurerm_private_dns_zone_virtual_network_link" "cognitive" {
  name                  = "cognitive"
  resource_group_name   = azurerm_resource_group.ai.name
  private_dns_zone_name = azurerm_private_dns_zone.cognitive.name
  virtual_network_id    = azurerm_virtual_network.ai.id
}

resource "azurerm_private_dns_zone_virtual_network_link" "openai" {
  name                  = "openai"
  resource_group_name   = azurerm_resource_group.ai.name
  private_dns_zone_name = azurerm_private_dns_zone.openai.name
  virtual_network_id    = azurerm_virtual_network.ai.id
}

resource "azurerm_private_dns_zone_virtual_network_link" "vault" {
  name                  = "vault"
  resource_group_name   = azurerm_resource_group.ai.name
  private_dns_zone_name = azurerm_private_dns_zone.vault.name
  virtual_network_id    = azurerm_virtual_network.ai.id
}

resource "azurerm_role_assignment" "payments" {
  scope                = azurerm_cognitive_account.foundry.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azuread_group.payments.object_id
}

output "foundry_endpoint" {
  value = azurerm_cognitive_account.foundry.endpoint
}

output "gateway_client_id" {
  description = "Chart value workloadIdentity.azureClientId. The federated token audience is api://AzureADTokenExchange."
  value       = azurerm_user_assigned_identity.gateway.client_id
}

output "tenant_id" {
  description = "Chart value workloadIdentity.azureTenantId."
  value       = data.azurerm_client_config.current.tenant_id
}

output "payments_group_id" {
  value = azuread_group.payments.object_id
}
