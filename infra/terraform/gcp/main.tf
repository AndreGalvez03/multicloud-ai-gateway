terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  description = "GCP project that hosts the Vertex AI calls for this boundary."
  type        = string
}

variable "region" {
  description = "Vertex AI region. Use an EU region for an EU boundary."
  type        = string
  default     = "europe-west1"
}

variable "namespace" {
  type    = string
  default = "aigw"
}

variable "k8s_service_account" {
  type    = string
  default = "ai-gateway"
}

variable "eks_oidc_issuer" {
  description = "EKS OIDC issuer URL, including https://. This is not a GKE pool."
  type        = string
}

data "google_project" "this" {
  project_id = var.project_id
}

resource "google_project_service" "vertex" {
  service            = "aiplatform.googleapis.com"
  disable_on_destroy = false
}

resource "google_service_account" "gateway" {
  account_id   = "ai-gateway"
  display_name = "AI Gateway runtime"
  description  = "Workload identity for Vertex AI. No downloaded key."
}

resource "google_project_iam_member" "vertex_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.gateway.email}"
}

resource "google_iam_workload_identity_pool" "eks" {
  workload_identity_pool_id = "aigw-eks"
  display_name              = "EKS AI gateway"
  description               = "Trusts the EKS cluster that runs the gateway. No downloaded key."
}

resource "google_iam_workload_identity_pool_provider" "eks" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.eks.workload_identity_pool_id
  workload_identity_pool_provider_id = "eks-oidc"
  display_name                       = "EKS"
  attribute_mapping = {
    "google.subject" = "assertion.sub"
  }
  attribute_condition = "assertion.sub==\"system:serviceaccount:${var.namespace}:${var.k8s_service_account}\""
  oidc {
    issuer_uri = var.eks_oidc_issuer
  }
}

resource "google_service_account_iam_member" "workload_identity" {
  service_account_id = google_service_account.gateway.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/projects/${data.google_project.this.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.eks.workload_identity_pool_id}/subject/system:serviceaccount:${var.namespace}:${var.k8s_service_account}"
}

output "gateway_service_account" {
  value = google_service_account.gateway.email
}

output "workload_identity_credential_config" {
  description = "External-account config for the gateway pod. The token file is the EKS projected service account token."
  value = jsonencode({
    type                              = "external_account"
    audience                          = "//iam.googleapis.com/projects/${data.google_project.this.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.eks.workload_identity_pool_id}/providers/${google_iam_workload_identity_pool_provider.eks.workload_identity_pool_provider_id}"
    subject_token_type                = "urn:ietf:params:oauth:token-type:jwt"
    token_url                         = "https://sts.googleapis.com/v1/token"
    service_account_impersonation_url = "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${google_service_account.gateway.email}:generateAccessToken"
    credential_source = {
      file = "/var/run/secrets/eks.amazonaws.com/serviceaccount/token"
    }
  })
}
