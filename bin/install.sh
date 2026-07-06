#!/bin/bash
set -e

REPO="DegenerateUSER/Oasis"
INSTALL_DIR="/usr/local/bin"

echo "🌿 Installing Oasis..."

# ── Detect OS ─────────────────────────────────────────────────────────────────
OS=$(uname -s)

# ── Helper: fetch latest release JSON once ─────────────────────────────────
RELEASE_JSON=$(curl -sf "https://api.github.com/repos/$REPO/releases/latest")
if [ -z "$RELEASE_JSON" ]; then
  echo "❌ Error: Could not reach GitHub API. Check your internet connection."
  exit 1
fi

get_url() {
  echo "$RELEASE_JSON" | grep '"browser_download_url"' | grep "$1" | cut -d '"' -f 4 | head -1
}

# ═══════════════════════════════════════════════════════════════════════════════
# macOS — prefer .pkg installer, fallback to raw binary
# ═══════════════════════════════════════════════════════════════════════════════
if [ "$OS" = "Darwin" ]; then
  PKG_URL=$(get_url "oasis-macos-arm64.pkg")

  if [ -n "$PKG_URL" ]; then
    echo "📦 Downloading macOS installer package (.pkg)..."
    curl -L --progress-bar -o /tmp/oasis.pkg "$PKG_URL"
    echo "🔧 Installing (you may be prompted for your password)..."
    sudo installer -pkg /tmp/oasis.pkg -target /
    rm -f /tmp/oasis.pkg
    echo ""
    echo "✅ Oasis installed successfully!"
    echo "   Run: oasis --help"
    exit 0
  fi

  # Fallback to raw binary
  echo "📦 Downloading macOS binary (fallback)..."
  BINARY_URL=$(get_url "oasis-darwin-arm64.tar.gz")
  if [ -z "$BINARY_URL" ]; then
    echo "❌ Error: No macOS release found. Visit https://github.com/$REPO/releases"
    exit 1
  fi
  curl -L --progress-bar -o /tmp/oasis.tar.gz "$BINARY_URL"
  tar -xzf /tmp/oasis.tar.gz -C /tmp
  sudo mv /tmp/oasis-darwin-arm64 "$INSTALL_DIR/oasis"
  sudo chmod +x "$INSTALL_DIR/oasis"
  rm -f /tmp/oasis.tar.gz

# ═══════════════════════════════════════════════════════════════════════════════
# Linux — prefer .deb on Debian/Ubuntu, fallback to raw binary
# ═══════════════════════════════════════════════════════════════════════════════
elif [ "$OS" = "Linux" ]; then
  if command -v dpkg >/dev/null 2>&1; then
    DEB_URL=$(get_url "oasis-linux-amd64.deb")

    if [ -n "$DEB_URL" ]; then
      echo "📦 Downloading Linux installer package (.deb)..."
      curl -L --progress-bar -o /tmp/oasis.deb "$DEB_URL"
      echo "🔧 Installing (you may be prompted for your password)..."
      sudo dpkg -i /tmp/oasis.deb
      rm -f /tmp/oasis.deb
      echo ""
      echo "✅ Oasis installed successfully!"
      echo "   Run: oasis --help"
      exit 0
    fi
  fi

  # Fallback to raw binary
  echo "📦 Downloading Linux binary (fallback)..."
  BINARY_URL=$(get_url "oasis-linux-amd64.tar.gz")
  if [ -z "$BINARY_URL" ]; then
    echo "❌ Error: No Linux release found. Visit https://github.com/$REPO/releases"
    exit 1
  fi
  curl -L --progress-bar -o /tmp/oasis.tar.gz "$BINARY_URL"
  tar -xzf /tmp/oasis.tar.gz -C /tmp
  sudo mv /tmp/oasis-linux-amd64 "$INSTALL_DIR/oasis"
  sudo chmod +x "$INSTALL_DIR/oasis"
  rm -f /tmp/oasis.tar.gz

# ═══════════════════════════════════════════════════════════════════════════════
# Unsupported OS
# ═══════════════════════════════════════════════════════════════════════════════
else
  echo "❌ Unsupported operating system: $OS"
  echo "   For Windows, download oasis-windows-amd64.zip from:"
  echo "   https://github.com/$REPO/releases/latest"
  exit 1
fi

echo ""
echo "✅ Oasis installed successfully!"
echo "   Run: oasis --help"
