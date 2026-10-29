terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
}

# Single EC2 instance on purpose: the service stores SQLite on local disk, which
# only one writer may use. Moving to ECS/Fargate goes hand in hand with moving
# to Postgres (RDS); SQLite on a network filesystem (EFS) risks corruption.

data "aws_vpc" "default" {
  default = true
}

# Not every availability zone offers every instance type.
data "aws_ec2_instance_type_offerings" "app" {
  location_type = "availability-zone"

  filter {
    name   = "instance-type"
    values = [var.instance_type]
  }
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  filter {
    name   = "availability-zone"
    values = data.aws_ec2_instance_type_offerings.app.locations
  }
}

data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# The API key lives encrypted in SSM Parameter Store; the instance reads it at
# boot, so it never appears in the user data.
resource "aws_ssm_parameter" "api_key" {
  name  = "/${var.name}/api-key"
  type  = "SecureString"
  value = var.api_key
}

resource "aws_iam_role" "app" {
  name = var.name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Least privilege: the instance may read its own API key and nothing else. No
# SSH and no Session Manager; boot problems show up in the console output.
resource "aws_iam_role_policy" "read_api_key" {
  name = "read-api-key"
  role = aws_iam_role.app.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "ssm:GetParameter"
      Resource = aws_ssm_parameter.api_key.arn
    }]
  })
}

resource "aws_iam_instance_profile" "app" {
  name = var.name
  role = aws_iam_role.app.name
}

resource "aws_security_group" "app" {
  name        = var.name
  description = "Credit evaluation API"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP API"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  egress {
    description = "Packages, Git, image build and the SSM API"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "app" {
  ami                         = data.aws_ssm_parameter.al2023_ami.value
  instance_type               = var.instance_type
  subnet_id                   = sort(data.aws_subnets.default.ids)[0] # stable across plans
  vpc_security_group_ids      = [aws_security_group.app.id]
  iam_instance_profile        = aws_iam_instance_profile.app.name
  associate_public_ip_address = true

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    region        = var.region
    repo_url      = var.repo_url
    git_ref       = var.git_ref
    api_key_param = aws_ssm_parameter.api_key.name
  })
  user_data_replace_on_change = true

  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1          # containers cannot reach the instance credentials
  }

  root_block_device {
    encrypted = true
  }

  tags = {
    Name = var.name
  }

  # SQLite lives on this instance's disk: a newer AMI must not replace it on the
  # next apply. Roll the AMI on purpose, after a backup.
  lifecycle {
    ignore_changes = [ami]
  }
}
