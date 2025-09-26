# © 2025 Amazon Web Services, Inc. or its affiliates. All Rights Reserved.
# This AWS Content is provided subject to the terms of the AWS Customer Agreement available at
# http://aws.amazon.com/agreement or other written agreement between Customer and either
# Amazon Web Services, Inc. or Amazon Web Services EMEA SARL or both.

resource "aws_security_group_rule" "all_worker_mgmt_ingress" {
  description       = "allow inbound traffic from eks"
  type              = "ingress"
  from_port         = 0
  to_port           = 65535
  protocol          = "tcp"
  cidr_blocks       = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
  security_group_id = "sg-12345"
}

# Create IAM role for EC2 instances
resource "aws_iam_role" "ec2_role" {
  name = "ec2-instance-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2_profile" {
  name = "ec2-instance-profile"
  role = aws_iam_role.ec2_role.name
}

resource "aws_instance" "this" {
  ami                  = "ami-12345"
  instance_type        = "t3.micro"
  iam_instance_profile = aws_iam_instance_profile.ec2_profile.name
  monitoring           = true # Enable detailed monitoring
  ebs_optimized        = true # Enable EBS optimization

  # Encrypt root block device
  root_block_device {
    encrypted             = true
    volume_type           = "gp3"
    volume_size           = 20
    delete_on_termination = true
  }

  instance_market_options {
    market_type = "spot"
    spot_options {
      max_price = "0.0031"
    }
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  tags = {
    Name        = "terraform-managed-instance"
    Environment = "dev"
  }
}

resource "aws_instance" "example" {
  ami                  = "ami-67890"
  instance_type        = "t3.small"
  iam_instance_profile = aws_iam_instance_profile.ec2_profile.name
  monitoring           = true # Enable detailed monitoring
  ebs_optimized        = true # Enable EBS optimization

  # Encrypt root block device
  root_block_device {
    encrypted             = true
    volume_type           = "gp3"
    volume_size           = 20
    delete_on_termination = true
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  lifecycle {
    precondition {
      condition     = data.aws_ami.example.architecture == "x86_64"
      error_message = "The selected AMI must be x86_64 architecture."
    }
  }

  tags = {
    Name        = "terraform-managed-example"
    Environment = "dev"
  }
}