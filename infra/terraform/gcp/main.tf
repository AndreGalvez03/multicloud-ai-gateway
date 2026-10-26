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

resource "google_service_account_iam_member" "workload_identity" {
  service_account_id = google_service_account.gateway.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.namespace}/${var.k8s_service_account}]"
}

output "gateway_service_account" {
  value = google_service_account.gateway.email
}
