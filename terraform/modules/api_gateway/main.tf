locals {
  prefix = "inbox-aggregator"
}

resource "aws_api_gateway_rest_api" "main" {
  name        = "${local.prefix}-api"
  description = "API Gateway for Gmail Pub/Sub push + authenticated user API."

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = {
    Name = "${local.prefix}-api"
  }
}

# ──────────────────────────────────────────────
# Cognito authorizer — guards the authenticated user endpoints.
# ──────────────────────────────────────────────
resource "aws_api_gateway_authorizer" "cognito" {
  name            = "${local.prefix}-cognito"
  rest_api_id     = aws_api_gateway_rest_api.main.id
  type            = "COGNITO_USER_POOLS"
  provider_arns   = [var.cognito_user_pool_arn]
  identity_source = "method.request.header.Authorization"
}

# ──────────────────────────────────────────────
# /gmail-push — unauthenticated (Pub/Sub push; JWT validated in the Lambda)
# ──────────────────────────────────────────────
resource "aws_api_gateway_resource" "gmail_push" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_rest_api.main.root_resource_id
  path_part   = "gmail-push"
}

resource "aws_api_gateway_method" "gmail_push_post" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.gmail_push.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "gmail_push_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.gmail_push.id
  http_method             = aws_api_gateway_method.gmail_push_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.gmail_webhook_lambda_invoke_arn
}

# ──────────────────────────────────────────────
# /graphql — Cognito-authorized read API (POST), CORS preflight open
# ──────────────────────────────────────────────
resource "aws_api_gateway_resource" "graphql" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_rest_api.main.root_resource_id
  path_part   = "graphql"
}

resource "aws_api_gateway_method" "graphql_options" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.graphql.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "graphql_options_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.graphql.id
  http_method             = aws_api_gateway_method.graphql_options.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.graphql_lambda_invoke_arn
}

resource "aws_api_gateway_method" "graphql_post" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.graphql.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "graphql_post_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.graphql.id
  http_method             = aws_api_gateway_method.graphql_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.graphql_lambda_invoke_arn
}

# ──────────────────────────────────────────────
# /redeem — Cognito-authorized (POST), CORS preflight open
# ──────────────────────────────────────────────
resource "aws_api_gateway_resource" "redeem" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_rest_api.main.root_resource_id
  path_part   = "redeem"
}

resource "aws_api_gateway_method" "redeem_options" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.redeem.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "redeem_options_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.redeem.id
  http_method             = aws_api_gateway_method.redeem_options.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.redeem_lambda_invoke_arn
}

resource "aws_api_gateway_method" "redeem_post" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.redeem.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "redeem_post_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.redeem.id
  http_method             = aws_api_gateway_method.redeem_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.redeem_lambda_invoke_arn
}

# ──────────────────────────────────────────────
# /channels — Cognito-authorized (GET/POST/DELETE), CORS preflight open
# ──────────────────────────────────────────────
resource "aws_api_gateway_resource" "channels" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_rest_api.main.root_resource_id
  path_part   = "channels"
}

resource "aws_api_gateway_method" "channels_options" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.channels.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "channels_options_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.channels.id
  http_method             = aws_api_gateway_method.channels_options.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.channels_lambda_invoke_arn
}

resource "aws_api_gateway_method" "channels_method" {
  for_each      = toset(["GET", "POST", "DELETE"])
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.channels.id
  http_method   = each.value
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "channels_integration" {
  for_each                = aws_api_gateway_method.channels_method
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.channels.id
  http_method             = each.value.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.channels_lambda_invoke_arn
}

# ──────────────────────────────────────────────
# Lambda invoke permissions
# ──────────────────────────────────────────────
resource "aws_lambda_permission" "api_gateway_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.gmail_webhook_lambda_arn
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "graphql_lambda_invoke" {
  statement_id  = "AllowAPIGatewayInvokeGraphql"
  action        = "lambda:InvokeFunction"
  function_name = var.graphql_lambda_arn
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "redeem_lambda_invoke" {
  statement_id  = "AllowAPIGatewayInvokeRedeem"
  action        = "lambda:InvokeFunction"
  function_name = var.redeem_lambda_arn
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "channels_lambda_invoke" {
  statement_id  = "AllowAPIGatewayInvokeChannels"
  action        = "lambda:InvokeFunction"
  function_name = var.channels_lambda_arn
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*/*"
}

# ──────────────────────────────────────────────
# Deployment + stage
# ──────────────────────────────────────────────
resource "aws_api_gateway_deployment" "main" {
  rest_api_id = aws_api_gateway_rest_api.main.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.gmail_push.id,
      aws_api_gateway_method.gmail_push_post.id,
      aws_api_gateway_integration.gmail_push_lambda.id,
      aws_api_gateway_resource.graphql.id,
      aws_api_gateway_method.graphql_post.id,
      aws_api_gateway_integration.graphql_post_lambda.id,
      aws_api_gateway_resource.redeem.id,
      aws_api_gateway_method.redeem_post.id,
      aws_api_gateway_integration.redeem_post_lambda.id,
      aws_api_gateway_resource.channels.id,
      aws_api_gateway_authorizer.cognito.id,
      jsonencode({ for k, m in aws_api_gateway_method.channels_method : k => m.id }),
      jsonencode({ for k, i in aws_api_gateway_integration.channels_integration : k => i.id }),
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.main.id
  rest_api_id   = aws_api_gateway_rest_api.main.id
  stage_name    = var.environment

  tags = {
    Name = "${local.prefix}-api-${var.environment}"
  }
}
