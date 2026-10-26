plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.38.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}

plugin "azurerm" {
  enabled = true
  version = "0.28.0"
  source  = "github.com/terraform-linters/tflint-ruleset-azurerm"
}

plugin "google" {
  enabled = true
  version = "0.33.0"
  source  = "github.com/terraform-linters/tflint-ruleset-google"
}

rule "terraform_unused_declarations" {
  enabled = true
}

rule "terraform_typed_variables" {
  enabled = true
}

rule "terraform_required_version" {
  enabled = true
}
