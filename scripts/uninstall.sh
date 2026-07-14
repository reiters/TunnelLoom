#!/bin/sh
set -eu
sudo rm -rf /opt/tunnelloom-gui
sudo rm -f /usr/local/bin/tunnelloom-gui
sudo rm -f /usr/libexec/tunnelloom-gui-helper
sudo rm -f /usr/share/polkit-1/actions/org.tunnelloom.gui.helper.policy
sudo rm -f /usr/share/applications/tunnelloom-gui.desktop
sudo rm -f /usr/share/icons/hicolor/scalable/apps/tunnelloom-gui.svg
echo "TunnelLoom VPN Client Manager was removed. User settings remain in ~/.config/tunnelloom-gui."
