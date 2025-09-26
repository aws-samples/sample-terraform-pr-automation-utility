# © 2025 Amazon Web Services, Inc. or its affiliates. All Rights Reserved.
# This AWS Content is provided subject to the terms of the AWS Customer Agreement available at
# http://aws.amazon.com/agreement or other written agreement between Customer and either
# Amazon Web Services, Inc. or Amazon Web Services EMEA SARL or both.

module "vpc" {
  # Use specific version with commit hash instead of just version tag
  # The commit hash ensures immutability and prevents supply chain attacks
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-vpc.git?ref=2e417ad2b05712302a31c1c5a0d7e3f42d8dd221" # v5.7.0

  name = "my-vpc"
  cidr = var.vpc_cidr

  azs             = ["us-west-2a", "us-west-2b", "us-west-2c"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

  enable_nat_gateway   = true
  enable_vpn_gateway   = true
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Security best practices
  manage_default_security_group   = true
  default_security_group_deny_all = true

  # Enable VPC flow logs for security monitoring
  enable_flow_log                      = true
  create_flow_log_cloudwatch_log_group = true
  create_flow_log_cloudwatch_iam_role  = true
  flow_log_max_aggregation_interval    = 60

  tags = {
    Terraform   = "true"
    Environment = "dev"
    ManagedBy   = "terraform-automation-tool"
  }
}
