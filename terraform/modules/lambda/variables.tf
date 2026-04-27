variable "function_name" {
  description = "Name of the Lambda function."
  type        = string
}

variable "handler" {
  description = "Lambda handler (e.g. handler.lambda_handler)."
  type        = string
  default     = "handler.lambda_handler"
}

variable "source_dir" {
  description = "Path to the Lambda source directory to zip."
  type        = string
}

variable "environment_variables" {
  description = "Environment variables for the Lambda function."
  type        = map(string)
  default     = {}
}

variable "timeout" {
  description = "Lambda timeout in seconds."
  type        = number
  default     = 30
}

variable "memory_size" {
  description = "Lambda memory in MB."
  type        = number
  default     = 256
}

variable "layer_arns" {
  description = "List of Lambda Layer ARNs to attach."
  type        = list(string)
  default     = []
}

variable "extra_policy_arns" {
  description = "Additional IAM policy ARNs to attach to the Lambda execution role."
  type        = list(string)
  default     = []
}

variable "inline_policies" {
  description = "Map of inline IAM policies (name → JSON document) to attach."
  type        = map(string)
  default     = {}
}
