# SmilyAI OS 0.3.1 — graphical startup repair

Scope: the Chromium app shell failing after an otherwise successful x86-64 live
boot into labwc. This is a complete updated source/build kit, not a rebuilt ISO.
No public publication/deployment was performed.

## Root cause and evidence

The 0.3 launcher passed `--ozone-platform=auto`. `auto` is not an Ozone backend.
Chromium selects a registered backend such as `wayland` or `x11`; its platform
selection code terminates with `Invalid ozone platform: auto` for the old flag.
The former automatic-choice switch was `--ozone-platform-hint=auto`; newer Chromium
auto-detects only when no explicit backend switch is supplied. This revision uses
an explicit concrete backend instead of depending on version-specific defaults.

This is a confirmed source defect and matches the user's report of Chromium
exiting before any window appears. The guest journal and exact Chromium version
were not supplied, so additional guest-specific faults are not ruled out. We did
not reproduce a visible Chromium crash/window in this authoring environment.

Primary source: [Chromium's platform-selection change and fatal error branch](https://chromium.googlesource.com/chromium/src/%2B/8f2c7d1c8585203b30d8f8c893f24a269a3f5417%5E%21/).

Contributing defects confirmed in the kit:

- `StartLimitIntervalSec=0` disabled systemd start limiting, creating the endless
  restart cycle seen in the QEMU report.
- `Type=simple` plus `After=` ordered process creation, not UI readiness.
- The ten readiness probes waited about 0.9 seconds when connections were refused
  immediately, and at most about 3.9 seconds when each HTTP timeout was exhausted.
- `curl -I /` returned HTTP 501 because HEAD was unimplemented; GET worked.
- Environment-import failures were ignored and XAUTHORITY was not imported.

Inspected but not established as the primary failure: missing runtime libraries,
profile corruption, missing Wayland socket, GPU issues, and sandbox support.
The package lists already contained Chromium/Xwayland/labwc/Python; browser service
hardening did not include NoNewPrivileges or a sandbox-disabling workaround.

## Exact changes

| Area | Change |
| --- | --- |
| Launcher | Installed and developer entry points share `smilyai/shell_launcher.py`; it selects `wayland` for labwc, `x11` for an X11 session, and accepts an explicit diagnostic override. No `auto` backend. |
| Display | Validate the actual compositor socket and wait up to 30 seconds. Check Wayland ownership; diagnose missing/unusable display variables. Do not silently guess a display number. |
| UI readiness | UI validates required local assets, binds/listens, then sends `READY=1`. `Type=notify`, `NotifyAccess=main`, and 120-second startup deadline establish real systemd ordering. |
| Manual readiness | Same-origin `/readyz` endpoint; launcher has a monotonic 90-second limit, 2-second individual request limits and 250ms retry spacing. No provider/backend/network dependency, proxy use or redirects. |
| Restart safety | Shell/UI each permit three starts in a 30-minute window. Shell waits 10 seconds between failed attempts; missing browser/unsafe profile/configuration exits do not retry. No forced sandbox disabling. |
| Recovery | Existing native menu and Super+Return/Super+E remain. Restore SmilyAI/Super+R now runs `smilyai-recover`, imports the current session, clears failed limits and retries services. |
| Environment | Import is still after labwc creates its socket. Checked helper imports Wayland, XWayland, XAUTHORITY, runtime and desktop variables and clears stale empty X11 values. |
| Diagnostics | Category-labelled logs: browser, display, profile, ui, launch, sandbox and recovery. Chromium stderr reaches journal/terminal, with exit status/signal and elapsed lifetime. `--diagnose` runs preflight only. |
| Profile | Owner-only writable directory, no symlink final profile, no automatic deletion of Chromium locks/data, no root browser. |
| Packages | Explicit `chromium-sandbox` in both image package lists, rather than relying on recommendations. Kernel user-namespace/setuid sandbox policy is unchanged. |
| HTTP diagnostics | Static HEAD requests return GET-equivalent headers without a body; `curl -I` works. Existing Host/Origin checks remain. |
| Development | `scripts/launch-shell.sh` invokes the checked source module and forwards arguments. It no longer relies on an installed `/opt` path. |
| Release | Version 0.3.1 and unique image output names prevent overwriting previous 0.3.0 images. |

Systemd references: [service readiness](https://manpages.debian.org/trixie/systemd/systemd.service.5.en.html),
[start-limit semantics](https://github.com/systemd/systemd/blob/main/man/systemd.unit.xml).

## Quick confirmation on the existing 0.3 live boot

Open the native labwc terminal (Super+Return). Run as the live desktop user,
**not with sudo**. This stops only the crash-looping browser service:

```bash
systemctl --user stop smilyai-shell.service
curl -fsS http://127.0.0.1:47810/ >/dev/null
chromium --app=http://127.0.0.1:47810/ --class=smilyai-shell --start-maximized \
  --no-first-run --ozone-platform=wayland \
  --user-data-dir="$HOME/.local/state/smilyai-os/chromium" \
  --enable-logging=stderr --log-level=1
```

If this shows the shell, it confirms the backend flag caused the observed failure
on that guest. If it fails, keep the exact stderr: a separate GPU, profile or
sandbox issue must not be hidden by adding `--no-sandbox`.

## Build and retest the fixed revision

Use the complete commands in [BUILD_AND_TEST.md](BUILD_AND_TEST.md). The x86 output
is `dist/SmilyAI-OS-0.3.1-x86_64.iso`. Both BIOS/UEFI definitions and the installer
remain intact. Raspberry Pi uses the same repaired launcher/session overlay; the
Pi output is `dist/SmilyAI-OS-0.3.1-rpi-arm64.img.xz`.

Inside the newly booted labwc session, first capture diagnostics:

```bash
journalctl --user -b -u smilyai-ui -u smilyai-shell -n 150 --no-pager
systemctl --user show smilyai-shell.service -p ActiveState -p SubState -p NRestarts -p Result
printf "WAYLAND_DISPLAY=%s\nDISPLAY=%s\nXDG_SESSION_TYPE=%s\n" "$WAYLAND_DISPLAY" "$DISPLAY" "$XDG_SESSION_TYPE"
curl -I http://127.0.0.1:47810/
curl -fsS http://127.0.0.1:47810/readyz
```

Expected readiness response: `{"service":"smilyai-ui","ready":true}`.
The log should show UI readiness, selected `wayland`, then the Chromium launch.
`active (running)` alone is not proof: require a visible, interactive orb and a
stable restart counter over at least 60 seconds.

### Required manual-launch test

From the native terminal on the fixed image, without sudo:

```bash
systemctl --user stop smilyai-shell.service
smilyai-shell --diagnose
smilyai-shell
```

`--diagnose` checks readiness but deliberately does not claim a visible window.
The second command must show the shell. Test click-to-type and native shortcuts.
Press Ctrl+C in the terminal to end the manual shell, then restore service ownership:

```bash
smilyai-recover
systemctl --user status smilyai-ui.service smilyai-shell.service --no-pager
```

For targeted isolation only, with the managed shell stopped:

```bash
smilyai-shell --platform=x11
# OR test a GPU issue on the default Wayland backend:
smilyai-shell --software-rendering
```

X11 requires labwc's XWayland DISPLAY and authorization. Software rendering only
adds `--disable-gpu`; it does not change the Chromium security sandbox. There is no
automatic X11/GPU fallback masking an arbitrary Chromium failure.

### Slow-VM and failure checks

1. Repeat live boot with QEMU TCG as documented, then on a physical x86-64 machine.
2. Verify services start without waiting for an AI provider or internet connection.
3. Stop only the harness: static shell and native recovery must remain available.
4. In a disposable VM, delay UI startup with a temporary user-service
   `ExecStartPre=/usr/bin/sleep 45` override, then restart UI and shell. UI remains
   activating until READY; the shell must appear after readiness, without a loop.
   Remove only that test override and reload the user manager afterward.
5. In a disposable VM, force browser failure and observe at most three starts in
   30 minutes, followed by start-limit-hit. Restore the test condition, then use
   the native Restore SmilyAI menu; it explicitly resets the limit.
6. Verify root invocation refuses launch, corrupt/wrong-owner profile gives a
   labelled error, and failures do not erase profile data or Chromium locks.

## Verification performed and remaining gates

Executed `bash scripts/check.sh`: 121 Python tests discovered, 117 passed, four
explicitly skipped; all nine JavaScript tests passed. Shell syntax, image definition
structure, Python compilation, staged executable modes and labwc XML checks passed.
Full output is in [TEST_RESULTS_0.3.1.txt](TEST_RESULTS_0.3.1.txt).

Added tests cover correct Ozone selection, an emulated 45-second slow boot, exact
timeouts, malformed readiness, profile ownership/symlinks, browser exit/signal
diagnostics, manual-entry code path, restart/recovery definitions, real loopback
HTTP readiness/HEAD, assets missing, port conflicts, backend outage and notification
ordering. Subprocess tests use a tiny test child, not Chromium.

Two real Wayland-style Unix-stream tests and two real sd_notify Unix-datagram tests
were skipped because this authoring host prohibits AF_UNIX sockets. Corresponding
mocked contracts passed. Those four tests remain runnable on the release host;
run them there without skips.

No Chromium, labwc, QEMU or live systemd user manager is available here. Accordingly,
**visible manual launch after boot, notify delivery to systemd, actual restart-limit
behaviour, rebuilt ISO boot, physical x86 GPU support and Raspberry Pi boot remain
unverified for 0.3.1**. The user's successful 0.3 kernel/labwc boot is accepted as
the baseline, not misrepresented as a 0.3.1 verification result.

## Changed source inventory

- `smilyai/shell_launcher.py`, `smilyai/service_notify.py` (new)
- `smilyai/ui_server.py`, `smilyai/server.py`
- `packaging/rootfs/usr/local/bin/smilyai-shell`, `smilyai-session-environment`, `smilyai-recover`
- `packaging/rootfs/etc/systemd/user/smilyai-ui.service`, `smilyai-shell.service`
- `packaging/rootfs/etc/xdg/smilyai/labwc/autostart`, `rc.xml`, `menu.xml`
- Both image package lists; builder/version/configuration/workflow output identifiers
- `scripts/launch-shell.sh`, `scripts/validate-image-definitions.sh`
- `tests/test_shell_startup.py`, `tests/test_ui_readiness.py`, `tests/test_staging.py`
- README, build instructions and this report; the earlier 0.3 report is retained as history

The archive contains an updated per-file `SOURCE_MANIFEST.sha256`; the outer ZIP
checksum is delivered separately because an archive cannot contain its own checksum.

