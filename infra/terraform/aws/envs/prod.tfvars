name                          = "aigw-prod"
aws_region                    = "us-east-1"
boundary                      = "us"
node_min                      = 2
node_desired                  = 3
node_max                      = 8
db_multi_az                   = true
enable_provisioned_throughput = false
monthly_bedrock_budget_usd    = "500"

# Set these in the organization management account. They are not secrets,
# but they are account-specific, so they stay out of the example values.
# identity_center_instance_arn = "arn:aws:sso:::instance/ssoins-example"
# identity_store_id            = "d-example"
