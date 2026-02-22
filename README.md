# OMEN Battery Limiter

A beautiful, translucent battery monitor and charge limiter notification tool for HP OMEN laptops on Linux.

![Battery Panel](https://i.imgur.com/placeholder.png)

## Features

- **Charge Limit Alert**: Notifies you (via desktop notifications) when your battery hits 80% charge.
- **Top Up Mode**: Temporarily disables the 80% limit for one full charge cycle, notifying you at 100%.
- **Beautiful UI**: Click the tray icon to see a translucent panel with:
    - Animated arc gauge showing charge level and limit.
    - Power source indicator (AC vs Battery) with real-time wattage.
    - Detailed stats: Energy (Wh), BIOS Capacity, Cycle Count, Estimated Time Remaining, Voltage.
- **System Tray Integration**: Shows live battery percentage and status.
- **Persistent State**: Remembers your settings across reboots.

## Why Notifications?

Many newer HP OMEN laptops (like the 16-xd0) lack kernel-level battery charge threshold support (`charge_control_end_threshold`). The BIOS "Adaptive Battery Optimizer" is often just a cosmetic feature on Linux.

This tool acts as a userspace solution, similar to AlDente on macOS, by alerting you when to unplug to prolong battery health.

## Installation

### Prerequisites

- **Python 3**
- **pip** (Python package installer)
- **libnotify** (for notifications)

**Debian/Ubuntu/Mint:**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv libnotify-bin
```

**Fedora:**
```bash
sudo dnf install python3 python3-pip libnotify
```

**Arch Linux:**
```bash
sudo pacman -S python3 python-pip libnotify
```

### Automatic Install (Recommended)

1.  Clone this repository:
    ```bash
    git clone https://github.com/yourusername/omen-battery.git
    cd omen-battery
    ```

2.  Run the installer:
    ```bash
    ./install.sh
    ```

This will:
- Install Python dependencies (`PyQt6`) in a local virtual environment.
- Install the application to `~/.local/share/omen-battery`.
- Create a desktop entry for autostart.
- Set up and start a systemd user service (`omen-battery.service`) to run in the background.

### Manual Install

If you prefer to install manually:

1.  Create a virtual environment:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

2.  Run the application:
    ```bash
    python3 src/omen_battery/main.py
    ```

## Usage

- **Tray Icon**: The application runs in the system tray. Click the icon to toggle the main panel.
- **Top Up**: Click the "Top Up to 100%" button in the panel to disable the 80% alert for one charge cycle. It will notify you when the battery reaches 100% instead.
- **Settings**: The application stores state in `~/.local/share/omen-battery/state.json`. You can manually edit the `limit` value (default 80) if you wish.

## Uninstallation

To remove the application and service:

```bash
./uninstall.sh
```

## Troubleshooting

- **No Tray Icon**: Ensure your desktop environment supports system tray icons (e.g., AppIndicator support on GNOME).
- **Service Not Starting**: Check logs with:
    ```bash
    journalctl --user -u omen-battery.service
    ```

## License

MIT License
