variable "name" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "allowed_security_group_id" { type = string }
variable "kms_key_arn" { type = string }
variable "instance_class" { type = string }
variable "multi_az" { type = bool }

resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-usage"
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "db" {
  name        = "${var.name}-postgres"
  description = "Postgres from the EKS cluster security group"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Postgres from EKS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.allowed_security_group_id]
  }
}

resource "aws_db_parameter_group" "this" {
  name   = "${var.name}-pg16"
  family = "postgres16"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}

data "aws_iam_policy_document" "monitoring" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["monitoring.rds.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "monitoring" {
  name               = "${var.name}-rds-monitoring"
  assume_role_policy = data.aws_iam_policy_document.monitoring.json
}

resource "aws_iam_role_policy_attachment" "monitoring" {
  role       = aws_iam_role.monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

resource "aws_db_instance" "usage" {
  identifier                          = "${var.name}-usage"
  engine                              = "postgres"
  engine_version                      = "16.8"
  instance_class                      = var.instance_class
  allocated_storage                   = 20
  max_allocated_storage               = 100
  storage_type                        = "gp3"
  storage_encrypted                   = true
  kms_key_id                          = var.kms_key_arn
  db_name                             = "aigw"
  username                            = "aigw"
  manage_master_user_password         = true
  db_subnet_group_name                = aws_db_subnet_group.this.name
  vpc_security_group_ids              = [aws_security_group.db.id]
  parameter_group_name                = aws_db_parameter_group.this.name
  publicly_accessible                 = false
  multi_az                            = var.multi_az
  backup_retention_period             = 14
  deletion_protection                 = true
  copy_tags_to_snapshot               = true
  iam_database_authentication_enabled = true
  performance_insights_enabled        = true
  performance_insights_kms_key_id     = var.kms_key_arn
  enabled_cloudwatch_logs_exports     = ["postgresql", "upgrade"]
  auto_minor_version_upgrade          = true
  monitoring_interval                 = 60
  monitoring_role_arn                 = aws_iam_role.monitoring.arn
  skip_final_snapshot                 = false
  final_snapshot_identifier           = "${var.name}-usage-final"
}

output "endpoint" { value = aws_db_instance.usage.address }
