# Open Inserto Infrastructure

This folder contains the OpenTofu setup for the small public AWS endpoint required by eBay Production access.

## Why This Exists

eBay requires a Marketplace Account Deletion Notification endpoint and a verification token before Production API access can be used. Open Inserto itself runs locally, so this endpoint is hosted separately as an AWS Lambda Function URL.

The endpoint handles:

- `GET ?challenge_code=...` for eBay endpoint verification
- `POST` account deletion notifications, currently logged to CloudWatch

## Structure

```text
infra/
  bootstrap-state/
    main.tf
    variables.tf
    outputs.tf
    terraform.tfvars.example

  ebay-account-deletion-lambda/
    backend.tf
    backend.hcl.example
    main.tf
    variables.tf
    outputs.tf
    terraform.tfvars.example
    lambda/
      handler.py
```

Local files that must not be committed:

- `infra/**/terraform.tfvars`
- `infra/**/backend.hcl`
- `infra/**/terraform.tfstate`
- `infra/**/lambda_package.zip`

## Bootstrap State

The `bootstrap-state` module creates the S3 bucket used as OpenTofu remote state. It intentionally uses local state because it creates the bucket that other modules use.

```bash
cd infra/bootstrap-state
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars
tofu init
tofu plan
tofu apply
```

The local `terraform.tfvars` should contain the real bucket name and tags, for example:

```hcl
aws_region        = "eu-west-1"
state_bucket_name = "your-project-opentofu-state"

tags = {
  Project     = "open-inserto"
  ManagedBy   = "OpenTofu"
  Environment = "shared"
}
```

## Account Deletion Lambda

The Lambda module uses the S3 state bucket created above.

```bash
cd infra/ebay-account-deletion-lambda
cp backend.hcl.example backend.hcl
cp terraform.tfvars.example terraform.tfvars
# edit backend.hcl and terraform.tfvars
tofu init -backend-config=backend.hcl
tofu plan
tofu apply
```

`backend.hcl` contains the real state bucket:

```hcl
bucket       = "your-project-opentofu-state"
key          = "ebay-account-deletion-lambda-prod/terraform.tfstate"
region       = "eu-west-1"
encrypt      = true
use_lockfile = true
```

`terraform.tfvars` contains the real verification token:

```hcl
aws_region   = "eu-west-1"
project_name = "open-inserto"
environment  = "prod"

verification_token = "REPLACE_WITH_REAL_SECRET"
```

## eBay Developer Portal Values

After `tofu apply`, use the output `function_url` as:

```text
Marketplace account deletion notification endpoint
```

Use the same local `verification_token` value as:

```text
Verification token
```

The Lambda reconstructs the endpoint URL from the incoming request, so no second apply is needed after the Function URL is known.
