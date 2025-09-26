# © 2025 Amazon Web Services, Inc. or its affiliates. All Rights Reserved.
# This AWS Content is provided subject to the terms of the AWS Customer Agreement available at
# http://aws.amazon.com/agreement or other written agreement between Customer and either
# Amazon Web Services, Inc. or Amazon Web Services EMEA SARL or both.

variable "cluster_version" {
  description = "EKS cluster version"
  type        = string
  default     = "1.27"
}

variable "node_group_instance_types" {
  description = "Instance types for node groups"
  type        = list(string)
  default     = ["t3.medium", "t3.large"]
}