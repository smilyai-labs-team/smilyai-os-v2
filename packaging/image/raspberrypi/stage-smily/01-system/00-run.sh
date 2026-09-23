#!/bin/bash -e
on_chroot <<'CHROOT'
set -eu
test "$(dpkg --print-architecture)" = arm64
systemctl enable NetworkManager.service lightdm.service
systemctl set-default graphical.target
# pi-gen stage2 grants passwordless sudo by default; remove that exact rule.
if [ -f /etc/sudoers.d/010_pi-nopasswd ]; then
    rm /etc/sudoers.d/010_pi-nopasswd
fi
printf '%s\n' '%sudo ALL=(ALL:ALL) ALL' > /etc/sudoers.d/90-smilyai
chmod 440 /etc/sudoers.d/90-smilyai
visudo -cf /etc/sudoers
dpkg-query -W > /opt/smilyai-os/packages.tsv
python3 -m compileall -q /opt/smilyai-os/smilyai
test -f /boot/firmware/config.txt
grep -q '^camera_auto_detect=1' /boot/firmware/config.txt || printf '\ncamera_auto_detect=1\n' >> /boot/firmware/config.txt
CHROOT
