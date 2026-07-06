#!/bin/bash
set -e

# Detect OS and architecture
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

if [ "$ARCH" = "x86_64" ]; then
  ARCH="amd64"
elif [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then
  ARCH="arm64"
fi

BINARY_NAME="oasis-${OS}-${ARCH}"
RELEASE_URL=$(curl -s https://api.github.com/repos/DegenerateUSER/Oasis/releases/latest | grep "browser_download_url.*${BINARY_NAME}.tar.gz" | cut -d : -f 2,3 | tr -d '\" ')

if [ -z "$RELEASE_URL" ]; then
  echo "Error: Could not find latest release binary matching ${BINARY_NAME}.tar.gz"
  exit 1
fi

echo "Downloading Oasis binary from $RELEASE_URL..."
curl -L -o oasis.tar.gz "$RELEASE_URL"

echo "Extracting..."
tar -xzf oasis.tar.gz

echo "Installing to /usr/local/bin/oasis..."
sudo mv "$BINARY_NAME" /usr/local/bin/oasis
chmod +x /usr/local/bin/oasis

rm oasis.tar.gz
echo "Oasis installed successfully! Run 'oasis --help' to verify usage."
