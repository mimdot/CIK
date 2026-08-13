#!/bin/bash
# Wrapper script to set up environment for the FastAPI sidecar in Tauri

# Get the app data directory based on platform
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    APP_DATA_DIR="$HOME/Library/Application Support/com.careerintelligence.kit"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    APP_DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/career-intelligence"
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    # Windows
    APP_DATA_DIR="$APPDATA/career-intelligence"
else
    # Fallback
    APP_DATA_DIR="$HOME/.career-intelligence"
fi

# Create the directory if it doesn't exist
mkdir -p "$APP_DATA_DIR"

# Set the database URL to use the app data directory
export DATABASE_URL="sqlite:///$APP_DATA_DIR/phd_data.db"

# Set CIK_SECRET_KEY if not already set (generate a random one for offline use;
# falls back to /dev/urandom when openssl is unavailable)
CIK_GEN_KEY="$(openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | tr -d '\n')"
export CIK_SECRET_KEY="${CIK_SECRET_KEY:-$CIK_GEN_KEY}"

# Disable invite requirement for offline use
export CIK_INVITE_REQUIRED="0"

# Sidecar is served over plain HTTP on localhost — browsers refuse Secure
# cookies on http://localhost origins, so drop the Secure flag. Behind real
# TLS (web deployment) the flag stays on via the CIK_COOKIE_SECURE default.
export CIK_COOKIE_SECURE="0"

# Run the FastAPI binary
exec "$(dirname "$0")/cik-api" "$@"
