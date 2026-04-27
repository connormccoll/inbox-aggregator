locals {
  prefix = "inbox-aggregator"
}

resource "aws_api_gateway_rest_api" "main" {
  name        = "${local.prefix}-api"
  description = "API Gateway for Gmail Pub/Sub push notifications."

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = {
    Name = "${local.prefix}-api"
  }
}

# /gmail-push resource
resource "aws_api_gateway_resource" "gmail_push" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_rest_api.main.root_resource_id
  path_part   = "gmail-push"
}

# POST method — no auth (Pub/Sub push delivers JWTs we validate in the Lambda)
resource "aws_api_gateway_method" "gmail_push_post" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.gmail_push.id
  http_method   = "POST"
  authorization = "NONE"
}

# Lambda proxy integration
resource "aws_api_gateway_integration" "gmail_push_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.gmail_push.id
  http_method             = aws_api_gateway_method.gmail_push_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.gmail_webhook_lambda_invoke_arn
}

# Deployment
resource "aws_api_gateway_deployment" "main" {
  rest_api_id = aws_api_gateway_rest_api.main.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.gmail_push.id,
      aws_api_gateway_method.gmail_push_post.id,
      aws_api_gateway_integration.gmail_push_lambda.id,
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

# Grant API Gateway permission to invoke the Lambda
resource "aws_lambda_permission" "api_gateway_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.gmail_webhook_lambda_arn
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*/*"
}
