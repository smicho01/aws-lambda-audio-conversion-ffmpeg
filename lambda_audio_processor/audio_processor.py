import os
import boto3
import subprocess

s3 = boto3.client('s3')
ffmpeg_bin = "/opt/bin/ffmpeg"  # Path to FFmpeg from Lambda layer

def lambda_handler(event, context):
    try:
        record = event['Records'][0]
        src_bucket = record['s3']['bucket']['name']
        src_key = record['s3']['object']['key']
        base_name, ext = os.path.splitext(os.path.basename(src_key))

        if ext.lower() not in [".wav", ".ogg"]:
            print(f"❌ Unsupported file extension: {ext}")
            return {
                "statusCode": 400,
                "error": f"Unsupported file extension: {ext}"
            }

        tmp_input = f'/tmp/{base_name}{ext}'
        tmp_output = f'/tmp/{base_name}.mp3'

        print(f"Downloading {src_key} from {src_bucket}...")
        s3.download_file(src_bucket, src_key, tmp_input)

        # ✅ Add this diagnostic
        print("FFmpeg version check...")
        try:
            out = subprocess.run([ffmpeg_bin, "-version"], capture_output=True, text=True)
            print(out.stdout)
        except Exception as ve:
            print("❌ FFmpeg version check failed:", ve)

        print(f"Converting {tmp_input} to MP3...")
        cmd = [
            ffmpeg_bin, "-y",
            "-i", tmp_input,
            "-codec:a", "libmp3lame",
            "-qscale:a", "3", # Adjust quality as needed 0 best (245-320 kbps?) 9-worst (65-120 kbps?)
            tmp_output
        ]
        subprocess.run(cmd, check=True)

        dst_bucket = os.environ['PROCESSED_BUCKET']
        dst_key = f"{base_name}.mp3"

        print(f"Uploading {tmp_output} to {dst_bucket}/{dst_key}...")
        s3.upload_file(tmp_output, dst_bucket, dst_key)

        return {
            "statusCode": 200,
            "body": f"Converted {src_key} and uploaded {dst_key}"
        }

    except Exception as e:
        print(f"ERROR: {e}")
        return {
            "statusCode": 500,
            "error": str(e)
        }
