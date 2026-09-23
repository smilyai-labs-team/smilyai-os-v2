# Exact build and VM test instructions

Run from the extracted `smilyai-os` directory. Do not run image builds on a machine
containing important data. These commands download packages and modify only the
disposable builder and build outputs; installation/flashing later can erase disks.

## 1. Source verification

Python 3.11+ and Node.js 20+:

```bash
bash scripts/check.sh
```

Use the supplied checks before each image build. They validate source behaviour and
definitions, not bootability. Build output directories are fresh and retained for diagnosis.
Existing final output names are not overwritten.

## 2. x86-64 hybrid ISO

Use a fresh Debian 13 (trixie) amd64 VM with network access, 4 vCPUs, 8 GB RAM,
and at least 40 GB free disk space. This is an engineering allowance, not a measured
minimum. Secure Boot signing is not configured.

```bash
sudo apt-get update
sudo apt-get install -y live-build python3 xorriso isolinux syslinux-common syslinux-efi \
  grub-pc-bin grub-efi-amd64-bin mtools dosfstools squashfs-tools ca-certificates
sudo bash scripts/build-x86-iso.sh
sha256sum -c dist/SmilyAI-OS-0.3.1-x86_64.iso.sha256
```

Expected output: `dist/SmilyAI-OS-0.3.1-x86_64.iso`, checksum, runtime manifest and
El Torito boot report. The builder refuses export unless both BIOS and UEFI boot
entries are reported. The image definition includes Debian Live and the graphical
Debian installer; an actual successful installer run remains a release gate.

For a Docker-enabled disposable amd64 host, the manual GitHub workflow contains the
equivalent privileged Debian container command. Privileged containers are not a safe
boundary for untrusted source; review the source before running.

## 3. Raspberry Pi 4/5 ARM64 image

Use a native aarch64 Debian/Raspberry Pi OS builder with Docker, 8 GB RAM recommended
and at least 40 GB free. Cross-building from x86 is deliberately rejected.

```bash
sudo apt-get update
sudo apt-get install -y docker.io git python3 openssl xz-utils
sudo systemctl enable --now docker
git ls-remote https://github.com/RPi-Distro/pi-gen.git refs/heads/arm64
```

Review the upstream commit printed above, then set its complete 40-character SHA.
Do not use master (the upstream 32-bit branch). The following is executable once
the placeholder is replaced:

```bash
export PI_GEN_REF='REPLACE_WITH_REVIEWED_40_CHARACTER_ARM64_COMMIT'
sudo env PI_GEN_REF="$PI_GEN_REF" bash scripts/build-rpi-image.sh
sha256sum -c dist/SmilyAI-OS-0.3.1-rpi-arm64.img.xz.sha256
xz -t dist/SmilyAI-OS-0.3.1-rpi-arm64.img.xz
```

The builder verifies the commit belongs to upstream arm64, uses a fresh checkout,
copies the previous stage, suppresses stage2's extra image, checks dpkg architecture
inside the image, and exports exactly one xz image.

Read the owner-only `dist/SmilyAI-OS-0.3.1-rpi-arm64.credentials.txt` locally.
Login is `smily`; its password is randomly generated per build. Change it with
`passwd` immediately after first login. SSH is off. The keyring may require creation
or unlocking at first use. No AI API key is supplied to either build script.

The disposable build host/container caches may contain the initial OS password or
its hash. Do not publish those caches, credential files, or an image with a personal
password. The GitHub workflow requires a dedicated repository secret named
`SMILYAI_PI_PASSWORD` (16–128 letters/digits/dot/underscore/hyphen); it does not upload
the credentials file. Do not use an API key as this OS login password.

Use Raspberry Pi Imager's custom-image option to flash the resulting `.img.xz`.
Confirm the selected SD card/USB device carefully; flashing erases that device.
A PC ISO is not a Pi image. Test Pi 4 and Pi 5 separately.

## 4. VM tests (x86-64)

On a separate Debian desktop test host:

```bash
sudo apt-get update
sudo apt-get install -y qemu-system-x86 qemu-utils ovmf
mkdir -p vm-test
qemu-img create -f qcow2 vm-test/smilyai-test.qcow2 32G
```

Legacy BIOS live boot:

```bash
qemu-system-x86_64 -enable-kvm -cpu host -m 4096 -smp 4 \
  -device virtio-vga -display gtk,gl=off \
  -drive file=vm-test/smilyai-test.qcow2,format=qcow2,if=virtio \
  -cdrom dist/SmilyAI-OS-0.3.1-x86_64.iso -boot d \
  -nic user,model=virtio-net-pci
```

Shut that VM down before starting UEFI with the same test disk:

```bash
cp /usr/share/OVMF/OVMF_VARS_4M.fd vm-test/OVMF_VARS_4M.fd
qemu-system-x86_64 -enable-kvm -cpu host -m 4096 -smp 4 \
  -device virtio-vga -display gtk,gl=off \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
  -drive if=pflash,format=raw,file=vm-test/OVMF_VARS_4M.fd \
  -drive file=vm-test/smilyai-test.qcow2,format=qcow2,if=virtio \
  -cdrom dist/SmilyAI-OS-0.3.1-x86_64.iso -boot d \
  -nic user,model=virtio-net-pci
```

Without KVM, replace `-enable-kvm -cpu host` with `-accel tcg -cpu max`.
That is much slower and does not measure actual GPU performance.

Choose graphical installation from the ISO's boot menu and install **only to the
32 GB virtual disk**. Never attach a physical disk to this test VM. Then restart
the same command without `-cdrom ... -boot d` to boot the installed OS.
Keep the same firmware mode and UEFI variable file used during installation.

Verify all of the following:

1. Desktop reaches usable state; no indefinite branded overlay.
2. New Linux account login works; no installed-system forced live-user autologin.
3. Onboarding completes once and stays completed after reboot.
4. Files, memory inspection, native apps and network settings work without an API key.
5. Configure your own provider key; it is absent from config JSON, bootstrap and logs.
6. Stop the harness with `systemctl --user stop smilyai-harness`. The static UI remains,
   recovery appears, and Super+Return/Super+E work. Restart it and use Retry.
7. Disable network, reject microphone permission, and disable WebGL in a separate
   test browser profile. Typing and fallback visuals still work.
8. Cancel a task waiting for approval; no action occurs after denial.
9. Inspect `journalctl --user -b -u smilyai-harness -u smilyai-ui -u smilyai-shell`.
10. Repeat with software rendering, reduced motion, small display, and keyboard-only navigation.

QEMU's generic ARM machine is not a substitute for Pi firmware/GPIO/camera testing.

## 5. Local speech setup

Build/install whisper.cpp's `whisper-server` and a trusted speech model separately.
Start it on loopback, with its inference route at, for example,
`http://127.0.0.1:8080/inference`. In SmilyAI Voice settings enable push-to-talk
and enter that endpoint. No audio is sent to the chat provider.
This kit does not automatically download models, start a speech daemon or enable a wake word.

## 6. Reproducibility and release

Pi upstream is commit-pinned by mandatory input; the exact SHA is emitted beside the image.
Runtime files are allowlist-staged and hashed. x86 package versions are recorded in
`/opt/smilyai-os/packages.tsv`. Debian/Raspberry Pi package repositories and the Docker
base tag are not snapshot-pinned: full binary reproducibility is not claimed.
Do not publish until the image, installer and hardware gates above pass.
