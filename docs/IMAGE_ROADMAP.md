# Image release gates

See [BUILD_AND_TEST.md](BUILD_AND_TEST.md) for commands and
[RELEASE_0.3.md](RELEASE_0.3.md) for verified scope.

0.3 is a source-tested preview, not a signed or boot-certified binary release.
The previous 0.2 document's unconditional bootability language was not justified by
the original structural tests.

Required before distribution:

- Build the ISO on Debian 13 amd64 and the Pi image on native ARM64.
- Verify BIOS/UEFI live boot and a complete graphical installation to a disposable VM disk.
- Reboot the installed OS and verify login, keyring, persisted settings and recovery.
- Boot both Pi 4 and Pi 5; check firmware, GPIO line naming, camera, PipeWire and networking.
- Measure idle/active CPU/GPU/RAM and interaction latency on Intel Iris Xe hardware.
- Run browser-level accessibility, shader compilation and visual-regression tests.
- Establish signed artifacts, package/repository snapshots, update/rollback and recovery.
- Add per-device OEM user provisioning before distributing Pi images broadly.

No Secure Boot signing, A/B updates, recovery partition or OEM account wizard is included.
The Pi image uses a build-specific initial password, SSH off and normal login. Its login
hash is embedded in the image; use a unique password and never publish a personal build.
