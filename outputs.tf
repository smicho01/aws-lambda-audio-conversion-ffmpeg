output "source_bucket_name" {
  description = "The name of the source S3 bucket"
  value       = aws_s3_bucket.source_files_bucket.bucket
}

output "processed_bucket_name" {
  description = "The name of the processed S3 bucket"
  value       = aws_s3_bucket.processed_files_bucket.bucket
}

output "audio_processor_lambda_name" {
  description = "The name of the audio processor Lambda function"
  value       = aws_lambda_function.audio_processor.function_name
}
