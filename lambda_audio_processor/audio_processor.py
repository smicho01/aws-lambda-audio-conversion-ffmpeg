import os
import boto3
import subprocess
import json
import re

s3 = boto3.client('s3')
ffmpeg_bin = "/opt/bin/ffmpeg"  # Path to FFmpeg from Lambda layer

def check_file_integrity(file_path, ffmpeg_bin):
    """
    Fast integrity checks for compressed audio file using compatible FFmpeg commands
    Returns: (is_valid, info_dict)
    """
    try:
        # 1. Basic file size check
        file_size = os.path.getsize(file_path)
        if file_size < 1024:  # Less than 1KB is suspicious
            return False, {"error": "File too small", "size": file_size}
        
        # 2. Simple FFmpeg test - try to read the file and get basic info
        # This is compatible with older FFmpeg versions
        probe_cmd = [
            ffmpeg_bin, 
            "-i", file_path,
            "-f", "null", 
            "-"
        ]
        
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=300)  # 5 minutes
        
        # FFmpeg returns info in stderr, even on success
        stderr_output = result.stderr # stderr - ffmpeg uses that to output all informational messages [progress, metadata, warnings, and errors] (not using stdout for that, stdout is for media data)
        
        # Basic validation: check if FFmpeg could read the file
        if "Invalid data found" in stderr_output or "No such file" in stderr_output:
            return False, {"error": "File seems to be corrupted or unreadable", "ffmpeg_output": stderr_output}
        
        # 3. Extract basic info from stderr output (FFmpeg puts metadata here)
        duration = 0
        bit_rate = 0
        sample_rate = 0
        
        # Parse duration (format: Duration: HH:MM:SS.ss)
        
        duration_match = re.search(r'Duration: (\d+):(\d+):(\d+\.?\d*)', stderr_output)
        if duration_match:
            hours, minutes, seconds = duration_match.groups()
            duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        
        # Parse bitrate (format: bitrate: 64 kb/s)
        bitrate_match = re.search(r'bitrate: (\d+) kb/s', stderr_output)
        if bitrate_match:
            bit_rate = int(bitrate_match.group(1)) * 1000  # Convert to bps
        
        # Parse sample rate (format: 22050 Hz)
        samplerate_match = re.search(r'(\d+) Hz', stderr_output)
        if samplerate_match:
            sample_rate = int(samplerate_match.group(1))
        
        # Check if it mentions mono/stereo
        is_mono = "mono" in stderr_output.lower() or "1 channels" in stderr_output
        
        # 4. Validation checks
        checks = {
            'has_duration': duration > 0.1,  # must be at least 0.1 seconds long
             #'reasonable_duration': duration < 7200,  # Less than 2 hours (sanity check)
            'has_sample_rate': sample_rate > 0, # Must have sample rate. Catches: Files where FFmpeg couldn't read audio properties, corrupted headers
            'reasonable_bitrate': bit_rate == 0 or 30000 <= bit_rate <= 80000,  # Allow 0 if not detected
            'file_size_reasonable': file_size > 1000,  # At least 1KB
            'no_errors_in_output': "error" not in stderr_output.lower() and "invalid" not in stderr_output.lower()
        }
        
        all_passed = all(checks.values())
        
        info = {
            'duration': duration,
            'bit_rate': bit_rate,
            'sample_rate': sample_rate,
            'is_mono': is_mono,
            'file_size': file_size,
            'checks': checks,
            'ffmpeg_output_sample': stderr_output[:200] + "..." if len(stderr_output) > 200 else stderr_output
        }
        
        return all_passed, info
        
    except subprocess.TimeoutExpired:
        return False, {"error": "Integrity check timeout"}
    except Exception as e:
        return False, {"error": f"Integrity check failed: {str(e)}"}

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
            "-b:a", "64k", # 64k - very good for speech
            "-ar", "22050", # 22kHz sample rates (speech does not need 44kHz)
            "-ac", "1", # mono audio (interviews rarely need stereo)
            "-af", "highpass=f=80,lowpass=f=8000", # remove freq. outside speech range
            tmp_output
        ]
        subprocess.run(cmd, check=True)

        # ✅ NEW: Integrity check
        print("Checking file integrity...")
        is_valid, integrity_info = check_file_integrity(tmp_output, ffmpeg_bin)
        
        # Structured logging for CloudWatch
        log_data = {
            "event": "integrity_check",
            "file": src_key,
            "is_valid": is_valid,
            "integrity_info": integrity_info
        }
        print(f"INTEGRITY_CHECK: {json.dumps(log_data)}")
        
        if not is_valid:
            error_msg = f"File integrity check failed: {integrity_info}"
            print(f"❌ INTEGRITY_FAILURE: {json.dumps({'file': src_key, 'error': integrity_info})}")
            return {
                "statusCode": 500,
                "error": error_msg
            }
        
        print(f"✅ INTEGRITY_SUCCESS: File {src_key} passed all checks")
        print(f"  Duration: {integrity_info['duration']:.2f}s")
        print(f"  Bitrate: {integrity_info['bit_rate']} bps")
        print(f"  File size: {integrity_info['file_size']} bytes")

        dst_bucket = os.environ['PROCESSED_BUCKET']
        dst_key = f"{base_name}.mp3"

        print(f"Uploading {tmp_output} to {dst_bucket}/{dst_key}...")
        s3.upload_file(tmp_output, dst_bucket, dst_key)

        return {
            "statusCode": 200,
            "body": f"Converted {src_key} and uploaded {dst_key}",
            "integrity_info": integrity_info
        }

    except Exception as e:
        print(f"ERROR: {e}")
        return {
            "statusCode": 500,
            "error": str(e)
        }