# © 2025 Amazon Web Services, Inc. or its affiliates. All Rights Reserved.
# This AWS Content is provided subject to the terms of the AWS Customer Agreement available at
# http://aws.amazon.com/agreement or other written agreement between Customer and either
# Amazon Web Services, Inc. or Amazon Web Services EMEA SARL or both.

# Create KMS key for RDS encryption
resource "aws_kms_key" "rds" {
  description             = "KMS key for RDS encryption"
  deletion_window_in_days = 10
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Enable IAM User Permissions"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "Allow RDS service"
        Effect = "Allow"
        Principal = {
          Service = "rds.amazonaws.com"
        }
        Action = [
          "kms:Decrypt",
          "kms:CreateGrant",
          "kms:GenerateDataKey"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_kms_alias" "rds" {
  name          = "alias/rds-encryption"
  target_key_id = aws_kms_key.rds.key_id
}

# Create DB subnet group for multi-AZ
resource "aws_db_subnet_group" "main" {
  name       = "main-db-subnet-group"
  subnet_ids = var.subnet_ids # You'll need to define this variable

  tags = {
    Name = "Main DB subnet group"
  }
}

resource "aws_db_instance" "main" {
  allocated_storage = 20
  storage_type      = "gp3"               # Use gp3 for better performance
  storage_encrypted = true                # Enable encryption at rest
  kms_key_id        = aws_kms_key.rds.arn # Use KMS key for encryption

  engine                     = "postgres"
  engine_version             = "13.7"
  auto_minor_version_upgrade = true # Enable auto minor upgrades

  instance_class = "db.t3.micro"
  db_name        = "mydb"
  username       = "admin"
  password       = var.db_password

  # High Availability and Backup
  multi_az                = true # Enable Multi-AZ
  backup_retention_period = 30   # Keep backups for 30 days
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:00-sun:05:00"

  # Monitoring and Logging
  enabled_cloudwatch_logs_exports       = ["postgresql"]      # Enable logging
  performance_insights_enabled          = true                # Enable performance insights
  performance_insights_kms_key_id       = aws_kms_key.rds.arn # Encrypt performance insights
  performance_insights_retention_period = 7
  monitoring_interval                   = 60 # Enable enhanced monitoring
  monitoring_role_arn                   = aws_iam_role.rds_enhanced_monitoring.arn
  parameter_group_name                  = aws_db_parameter_group.postgres_logging.name

  # Security
  iam_database_authentication_enabled = true # Enable IAM auth
  deletion_protection                 = true # Enable deletion protection
  copy_tags_to_snapshot               = true # Copy tags to snapshots

  # Network
  db_subnet_group_name = aws_db_subnet_group.main.name
  publicly_accessible  = false

  # Final snapshot
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.db_name}-final-snapshot-${formatdate("YYYY-MM-DD-hhmm", timestamp())}"

  tags = {
    Name        = "main-database"
    Environment = "production"
  }
}

resource "aws_db_parameter_group" "postgres_logging" {
  name   = "postgres-logging-params"
  family = "postgres13"

  parameter {
    name  = "log_statement"
    value = "all" # Log all SQL statements
  }

  parameter {
    name  = "log_duration"
    value = "1"
  }

  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "100" # Log slow queries
  }

  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements,auto_explain"
  }
}

# IAM role for enhanced monitoring
resource "aws_iam_role" "rds_enhanced_monitoring" {
  name = "rds-enhanced-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "monitoring.rds.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "rds_enhanced_monitoring" {
  role       = aws_iam_role.rds_enhanced_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}