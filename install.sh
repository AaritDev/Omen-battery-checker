#!/bin/bash

# Define paths
APP_DIR="$HOME/.local/share/omen-battery"
BIN_DIR="$HOME/.local/bin"
SYSTEMD_DIR="$HOME/.config/systemd/user"
AUTOSTART_DIR="$HOME/.config/autostart"

echo "🔋 Installing OMEN Battery Limiter..."

# Ensure python3 is available
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed."
    exit 1
fi

# Ensure notify-send is available (for notifications)
if ! command -v notify-send &> /dev/null; then
    echo "Warning: 'notify-send' not found. Please install libnotify (e.g., 'sudo apt install libnotify-bin' or 'sudo dnf install libnotify')."
fi

# Create app directory
mkdir -p "$APP_DIR"
mkdir -p "$BIN_DIR"
mkdir -p "$SYSTEMD_DIR"
mkdir -p "$AUTOSTART_DIR"

# Copy source code
cp src/omen_battery/main.py "$APP_DIR/main.py"
echo "Copied source files."

# Set up virtual environment
if [ ! -d "$APP_DIR/venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$APP_DIR/venv"
fi

# Install dependencies
echo "Installing dependencies..."
"$APP_DIR/venv/bin/pip" install -r requirements.txt > /dev/null

# Create wrapper script
echo "Creating wrapper script..."
cat <<EOF > "$BIN_DIR/omen-battery"
#!/bin/bash
exec "$APP_DIR/venv/bin/python3" "$APP_DIR/main.py" "\$@"
EOF
chmod +x "$BIN_DIR/omen-battery"

# Create .desktop file for autostart/menu
echo "Creating .desktop file..."
cat <<EOF > "$APP_DIR/omen-battery.desktop"
[Desktop Entry]
Name=OMEN Battery Monitor
Comment=Battery charge limit monitor and notifier
Exec=$BIN_DIR/omen-battery
Icon=battery
Terminal=false
Type=Application
Categories=Utility;System;
StartupNotify=false
EOF

# Install .desktop file to autostart
ln -sf "$APP_DIR/omen-battery.desktop" "$AUTOSTART_DIR/omen-battery.desktop"

# Create systemd user service
echo "Creating systemd service..."
cat <<EOF > "$SYSTEMD_DIR/omen-battery.service"
[Unit]
Description=OMEN Battery Monitor
After=graphical-session.target

[Service]
ExecStart=$BIN_DIR/omen-battery
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

# Reload systemd and enable service
systemctl --user daemon-reload
systemctl --user enable --now omen-battery.service

echo "✅ Installation complete!"
echo "The service is running. You can manage it with:"
echo "  systemctl --user status omen-battery.service"
echo "  systemctl --user stop omen-battery.service"
