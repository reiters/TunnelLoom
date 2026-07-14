#!/bin/sh
set -eu
sudo rm -rf /opt/softether-gui
sudo rm -f /usr/local/bin/softether-gui
sudo rm -f /usr/libexec/softether-gui-helper
sudo rm -f /usr/share/polkit-1/actions/org.softether.gui.helper.policy
sudo rm -f /usr/share/applications/softether-gui.desktop
sudo rm -f /usr/share/icons/hicolor/scalable/apps/softether-gui.svg
echo "SoftEther VPN Client Manager was removed. User settings remain in ~/.config/softether-gui."
