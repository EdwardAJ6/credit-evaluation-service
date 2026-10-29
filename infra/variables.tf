variable "region" {
  description = "AWS region to deploy to."
  type        = string
  default     = "us-east-1"
}

variable "name" {
  description = "Name used for every resource."
  type        = string
  default     = "credit-evaluation-service"
}

variable "instance_type" {
  description = "EC2 instance type."
  type        = string
  default     = "t3.micro"
}

variable "allowed_cidrs" {
  description = "CIDR blocks allowed to call the API on port 80 (e.g. the calling systems' IPs)."
  type        = list(string)
}

variable "api_key" {
  description = "Shared API key the callers send in the X-API-Key header."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.api_key) >= 32
    error_message = "Use at least 32 characters, e.g. the output of `openssl rand -hex 32`."
  }
}

variable "repo_url" {
  description = "Public Git repository the instance builds the image from."
  type        = string
  default     = "https://github.com/EdwardAJ6/credit-evaluation-service.git"
}

variable "git_ref" {
  description = "Branch or tag to deploy."
  type        = string
  default     = "main"
}
