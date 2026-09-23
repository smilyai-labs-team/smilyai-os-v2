# SmilyAI OS 0.3.1 — Graphical startup fix

A real Debian/Linux user session: labwc Wayland compositor, Chromium system shell,
and an unprivileged Python agent. The orb is the primary interaction surface.
This is source and image-building infrastructure, not a hosted website.

**Release status: source-tested maintenance preview. The user reports a successful
0.3 live-system/labwc QEMU boot; this revision fixes the Chromium startup failure.
No 0.3.1 binary or visible-window boot was verified in the authoring environment.**

## Start here

- [Startup root cause, fixes and exact guest retest](docs/STARTUP_FIX_0.3.1.md)
- [Build the x86-64 ISO or Raspberry Pi ARM64 image](docs/BUILD_AND_TEST.md)
- [Changes, audit findings, security fixes and remaining gates](docs/RELEASE_0.3.md)
- [Architecture and trust boundaries](docs/ARCHITECTURE.md)
- [Recorded 0.3.1 automated test output](docs/TEST_RESULTS_0.3.1.txt)

## Development on an existing Linux desktop

Requires Python 3.11+, Node.js 20+ for tests, Chromium and a local graphical session.

```bash
bash scripts/check.sh
bash scripts/dev.sh
```

The shell listens on `127.0.0.1:47810`; the harness on `127.0.0.1:47811`.
Development mode does not replace your desktop or change storage partitions.
Use disposable XDG configuration/state directories if testing without touching
your existing SmilyAI profile. Stop with Ctrl+C.

## Interaction

Tap the orb to type. Hold it, or hold Space while the shell background is focused,
for opt-in push-to-talk. Escape or Stop cancels future agent steps.
Files, Apps, Network and Activity appear only when needed.

Voice is off by default. Configure a local whisper.cpp speech server in Voice settings;
no model is bundled. Optional speech output uses installed local browser/system voices.
Wake-word listening is not implemented or enabled.

## SmilyAI API

Choose **SmilyAI API** in onboarding or Settings → Intelligence.
Default base URL: `https://apismilyai.pythonanywhere.com/v1`.
Enter your own key; Test & fetch models, or enter a model ID manually, then Save.
The adapter supports model listing, chat completions and SSE streaming.
An account is optional: Local tools remains the initial selection.

Keys are scoped to provider plus endpoint. They are never stored in JSON settings,
returned by bootstrap, added to browser storage, or included in image staging.
Secret Service is used when available. Without its client, credentials are memory-only;
a present but locked/broken keyring causes a visible save failure, not a plaintext fallback.

## Image outputs

Both builders are manual and require suitable, disposable Linux build hosts:

- `dist/SmilyAI-OS-0.3.1-x86_64.iso` — Debian Live hybrid ISO definition, BIOS + UEFI, graphical Debian installer.
- `dist/SmilyAI-OS-0.3.1-rpi-arm64.img.xz` — pi-gen ARM64 definition, Pi 4/5 firmware and hardware packages.

Follow the exact commands and verification checklist in [BUILD_AND_TEST](docs/BUILD_AND_TEST.md).
The included GitHub Actions workflow is manual-only. Nothing has been published or deployed.

**Not yet verified:** successful full image builds, installed-session login, physical
Wi-Fi/audio/GPIO/camera, Intel Iris Xe frame times, or Secure Boot.
