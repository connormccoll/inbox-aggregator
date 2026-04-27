output "rest_api_id" {
  value = aws_api_gateway_rest_api.main.id
}

output "base_url" {
  value = aws_api_gateway_stage.prod.invoke_url
}

output "execution_arn" {
  value = aws_api_gateway_rest_api.main.execution_arn
}
