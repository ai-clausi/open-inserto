output "state_bucket_name" {
  value = aws_s3_bucket.tofu_state.bucket
}

output "state_bucket_region" {
  value = var.aws_region
}
