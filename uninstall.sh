#!/bin/bash

APP_DIR="$HOME/.local/share/omen-battery"
BIN_DIR="$HOME/.local/bin"
SYSTEMD_DIR="$HOME/.config/systemd/user"
AUTOSTART_DIR="$HOME/.config/autostart"

echo "🗑️  Uninstalling OMEN Battery Limiter..."

# Stop and disable service
systemctl --user stop omen-battery.service 2>/dev/null
systemctl --user disable omen-battery.service 2>/dev/null

# Remove service file
rm -f "$SYSTEMD_DIR/omen-battery.service"
systemctl --user daemon-reload

# Remove app directory and virtual environment
rm -rf "$APP_DIR"

# Remove bin script
rm -f "$BIN_DIR/omen-battery"

# Remove autostart entry
rm -f "$AUTOSTART_DIR/omen-battery.desktop"

echo "✅ Uninstallation complete."
