#!/bin/sh
set -eu

VERSION="0.1.19"
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ "$(id -u)" -eq 0 ]; then
    echo "Run this installer as your normal desktop user. It will use sudo when needed." >&2
    exit 1
fi

echo "Installing SoftEther VPN Client Manager ${VERSION}..."

sudo apt update
sudo apt install -y \
    python3 \
    python3-pyside6.qtcore \
    python3-pyside6.qtgui \
    python3-pyside6.qtwidgets \
    qt6-svg-plugins \
    polkitd \
    pkexec \
    network-manager \
    dhcpcd-base \
    iproute2

# A tray instance can remain alive after its window is closed. Python modules
# already loaded by that process cannot be replaced in memory, so stop the old
# GUI before installing the new files.
if command -v pgrep >/dev/null 2>&1 && pgrep -u "$(id -u)" -f '/usr/bin/python3.*-m softether_gui' >/dev/null 2>&1; then
    echo "Stopping the currently running SoftEther GUI so the upgrade takes effect..."
    pkill -u "$(id -u)" -f '/usr/bin/python3.*-m softether_gui' 2>/dev/null || true
    sleep 1
fi

# Replace the complete application tree and launcher rather than merging files
# with an older installation.
sudo rm -rf /opt/softether-gui
sudo install -d -m 0755 /opt/softether-gui /usr/libexec /usr/share/polkit-1/actions /usr/share/applications /usr/share/icons/hicolor/scalable/apps
sudo cp -a "$PROJECT_DIR/softether_gui" /opt/softether-gui/
sudo cp -a "$PROJECT_DIR/assets" /opt/softether-gui/
printf '%s\n' "$VERSION" | sudo tee /opt/softether-gui/VERSION >/dev/null
sudo install -m 0755 "$PROJECT_DIR/scripts/softether-gui" /usr/local/bin/softether-gui
sudo install -m 0755 "$PROJECT_DIR/scripts/softether-gui-helper" /usr/libexec/softether-gui-helper
sudo install -m 0644 "$PROJECT_DIR/packaging/org.softether.gui.helper.policy" /usr/share/polkit-1/actions/org.softether.gui.helper.policy
sudo install -m 0644 "$PROJECT_DIR/packaging/softether-gui.desktop" /usr/share/applications/softether-gui.desktop
sudo install -m 0644 "$PROJECT_DIR/assets/softether-gui.svg" /usr/share/icons/hicolor/scalable/apps/softether-gui.svg

# Do not change ownership, permissions, ACLs, or contents anywhere in the
# existing SoftEther installation. Runtime access is obtained through a
# PolicyKit-authenticated helper process instead.

command -v update-desktop-database >/dev/null 2>&1 && sudo update-desktop-database /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && sudo gtk-update-icon-cache -f /usr/share/icons/hicolor || true

installed_version=$(/usr/local/bin/softether-gui --version 2>/dev/null || true)
if [ "$installed_version" != "$VERSION" ]; then
    echo "Installation verification failed: expected ${VERSION}, found ${installed_version:-nothing}." >&2
    exit 1
fi

# Run this check while the installer's current directory is still the extracted
# source tree. This catches the exact failure mode where Python imports the
# source copy instead of the newly installed copy under /opt.
diagnostic_output=$(/usr/local/bin/softether-gui --diagnose 2>&1 || true)
expected_module="Loaded module: /opt/softether-gui/softether_gui/diagnostics.py"
if ! printf '%s\n' "$diagnostic_output" | grep -Fqx "$expected_module"; then
    echo "Installation verification failed: the launcher did not load the installed application." >&2
    printf '%s\n' "$diagnostic_output" >&2
    exit 1
fi

resolved=$(command -v softether-gui 2>/dev/null || true)
if [ -n "$resolved" ] && [ "$resolved" != "/usr/local/bin/softether-gui" ]; then
    echo "WARNING: your shell resolves softether-gui to $resolved instead of /usr/local/bin/softether-gui." >&2
    echo "Run 'type -a softether-gui' to locate the older launcher." >&2
fi

echo
echo "Installed SoftEther VPN Client Manager ${VERSION}."
echo "Verified launcher version: $(/usr/local/bin/softether-gui --version)"
echo "Verified loaded module: /opt/softether-gui/softether_gui/diagnostics.py"
echo "Open it from the Cinnamon menu or run: softether-gui"
echo "It may be started from any directory."
echo "For path diagnostics, run: softether-gui --diagnose"
echo "To execute the exact GUI vpncmd launch path, run: softether-gui --probe-vpncmd"
