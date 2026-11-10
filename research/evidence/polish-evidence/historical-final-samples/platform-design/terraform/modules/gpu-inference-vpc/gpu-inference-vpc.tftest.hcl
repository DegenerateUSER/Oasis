mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = jsonencode({ Version = "2012-10-17", Statement = [] }) }
  }
}

variables {
  name            = "test-gpu-vpc"
  vpc_cidr        = "10.20.0.0/16"
  azs             = ["us-east-1a", "us-east-1b"]
  private_subnets = ["10.20.0.0/20", "10.20.16.0/20"]
  intra_subnets   = ["10.20.32.0/20", "10.20.48.0/20"]
  cluster_name    = "test-gpu-cluster"
  tags = {
    Environment = "test"
    Team        = "gpu"
    ManagedBy   = "terraform"
  }
}

run "creates_vpc_module" {
  command = plan

  assert {
    condition     = module.vpc.name == "test-gpu-vpc"
    error_message = "VPC name should match input"
  }

  assert {
    condition     = module.vpc.vpc_cidr_block == "10.20.0.0/16"
    error_message = "VPC CIDR should match input"
  }
}

run "gpu_interconnect_security_group_created" {
  command = plan

  assert {
    condition     = aws_security_group.gpu_interconnect.name_prefix == "test-gpu-vpc-gpu-interconnect-"
    error_message = "GPU interconnect security group should be created"
  }
}
