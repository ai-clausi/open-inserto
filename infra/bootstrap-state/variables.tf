variable "aws_region" {
  description = "AWS region for the OpenTofu state bucket."
  type        = string
}

variable "state_bucket_name" {
  description = "Globally unique S3 bucket name for OpenTofu remote state."
  type        = string
}

variable "tags" {
  description = "Tags applied to the OpenTofu state bucket."
  type        = map(string)
  default     = {}
}
