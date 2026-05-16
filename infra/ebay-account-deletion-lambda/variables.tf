variable "aws_region" {
  description = "AWS region for the Lambda Function URL endpoint."
  type        = string
  default     = "eu-west-1"
}

variable "project_name" {
  description = "Short project name used for AWS resource names."
  type        = string
  default     = "open-inserto"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "prod"
}

variable "verification_token" {
  description = "Secret token configured in the eBay Developer Portal."
  type        = string
  sensitive   = true
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
  default     = 30
}
