variable "region" {
  description = "AWS region"
  type        = string
  default     = "eu-west-2"
}

variable "environment" {
  description = "Environment tag (e.g., dev, staging, production)"
  type        = string
  default     = "production"
}

variable "layer_s3_key" {
  description = "S3 key for FFmpeg layer zip"
  type        = string
  default     = "ffmpeg-python311.zip"
}
