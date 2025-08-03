terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.region
}

resource "aws_s3_bucket" "ffmpeg_layer_bucket" {
  bucket = "my-ffmpeg-layer-${var.environment}"

  tags = {
    Environment = var.environment
    Purpose     = "FFmpeg Lambda Layer"
  }
}

resource "aws_s3_object" "ffmpeg_layer_zip" {
  bucket = aws_s3_bucket.ffmpeg_layer_bucket.id
  key    = var.layer_s3_key
  source = "${path.module}/${var.layer_s3_key}"
  etag   = filemd5("${path.module}/${var.layer_s3_key}")
}

resource "aws_s3_bucket" "source_files_bucket" {
  bucket = "process-audio-files-source-${var.environment}"

  tags = {
    Environment  = var.environment
    Project      = "HappyFiles"
    Confidential = "true"
  }
}

resource "aws_s3_bucket" "processed_files_bucket" {
  bucket = "process-audio-files-processed-${var.environment}"

  tags = {
    Environment  = var.environment
    Project      = "HappyFiles"
    Confidential = "true"
  }
}

resource "aws_s3_bucket_versioning" "source_versioning" {
  bucket = aws_s3_bucket.source_files_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "processed_versioning" {
  bucket = aws_s3_bucket.processed_files_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "source_encryption" {
  bucket = aws_s3_bucket.source_files_bucket.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "processed_encryption" {
  bucket = aws_s3_bucket.processed_files_bucket.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "archive_file" "audio_processor_zip" {
  type        = "zip"
  source_dir  = "${path.module}/lambda_audio_processor"
  output_path = "${path.module}/lambda_audio_processor.zip"
}

resource "aws_iam_role" "audio_processor_role" {
  name = "audio_processor_lambda_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action = "sts:AssumeRole",
      Effect = "Allow",
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "audio_processor_policy" {
  name = "audio_processor_policy"
  role = aws_iam_role.audio_processor_role.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = ["s3:GetObject", "s3:GetObjectVersion"],
        Resource = "${aws_s3_bucket.source_files_bucket.arn}/*"
      },
      {
        Effect = "Allow",
        Action = ["s3:PutObject", "s3:PutObjectAcl"],
        Resource = "${aws_s3_bucket.processed_files_bucket.arn}/*"
      },
      {
        Effect = "Allow",
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

resource "aws_lambda_layer_version" "ffmpeg" {
  layer_name          = "ffmpeg"
  s3_bucket           = aws_s3_bucket.ffmpeg_layer_bucket.id
  s3_key              = var.layer_s3_key
  compatible_runtimes = ["python3.11"]
  description         = "FFmpeg static binary for Lambda"

  depends_on = [aws_s3_object.ffmpeg_layer_zip]
}

resource "aws_lambda_function" "audio_processor" {
  function_name     = "audio_processor"
  role              = aws_iam_role.audio_processor_role.arn
  handler           = "audio_processor.lambda_handler"
  runtime           = "python3.11"
  timeout           = 300
  memory_size       = 2048
  filename          = data.archive_file.audio_processor_zip.output_path
  source_code_hash  = data.archive_file.audio_processor_zip.output_base64sha256
  layers            = [aws_lambda_layer_version.ffmpeg.arn]

   ephemeral_storage {
    size = 4048  # 4GB of ephemeral storage
  }

  environment {
    variables = {
      SOURCE_BUCKET    = aws_s3_bucket.source_files_bucket.bucket
      PROCESSED_BUCKET = aws_s3_bucket.processed_files_bucket.bucket
    }
  }

  depends_on = [
    aws_s3_bucket.source_files_bucket,
    aws_s3_bucket.processed_files_bucket
  ]
}

resource "aws_lambda_permission" "s3_invoke_audio_processor" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.audio_processor.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.source_files_bucket.arn
}

resource "aws_s3_bucket_notification" "source_bucket_notification" {
  bucket = aws_s3_bucket.source_files_bucket.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.audio_processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = ".wav"
  }

  lambda_function {
    lambda_function_arn = aws_lambda_function.audio_processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = ".ogg"
  }

  depends_on = [aws_lambda_permission.s3_invoke_audio_processor]
}
