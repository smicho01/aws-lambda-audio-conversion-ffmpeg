#!/bin/bash

set -euo pipefail

echo "- Cleaning previous artifacts..."
rm -rf ffmpeg-release-* ffmpeg-layer ffmpeg-python311.zip

echo "- Building in Amazon Linux 2 Docker..."

docker run --rm -v "$PWD":/build -w /build amazonlinux:2 bash -c '
  set -euo pipefail

  yum install -y curl tar xz zip > /dev/null

  echo "- Downloading FFmpeg..."
  curl -sLO https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz

  echo "- Extracting FFmpeg..."
  tar -xf ffmpeg-release-amd64-static.tar.xz

  echo "- Preparing Lambda layer..."
  mkdir -p ffmpeg-layer/bin
  cp ffmpeg-*-static/ffmpeg ffmpeg-layer/bin/
  chmod +x ffmpeg-layer/bin/ffmpeg

  echo "- Creating zip archive..."
  cd ffmpeg-layer
  zip -r ../ffmpeg-python311.zip .
'

echo "- ffmpeg-python311.zip built successfully"
