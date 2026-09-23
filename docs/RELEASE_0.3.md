# SmilyAI OS 0.3 Platinum — release and audit report

Date: 2026-09-22. Based on the supplied complete 0.2 image build kit.

## Delivery status

**Modified complete source/build kit; automated source tests pass.**
No ISO or Pi disk image was produced in this environment. No successful VM boot,
installer run or physical-hardware session is claimed. Image definitions and manual
workflows are supplied so the next release gate can run on appropriate build hosts.
This is an engineering preview, not a production-certified OS.

The original kit's Python, JavaScript, styles, assets, configuration, packaging,
services, scripts, tests and workflow were reviewed. Source-level review is not proof
that every runtime bug has been eliminated. The supplied logo is retained.

## Concise changelog / bugs fixed

| Area | 0.2 problem | 0.3 implementation |
| --- | --- | --- |
| Pi architecture | Default upstream master selected the 32-bit pipeline | Mandatory immutable commit from arm64; native builder and in-image architecture checks |
| Pi stages/output | Missing previous-root copy; obsolete xz settings; arbitrary latest image selection | prerun copy_previous, DEPLOY_COMPRESSION=xz, exactly one custom-stage image |
| Build hygiene | Whole checkout copied into image, stale build reuse and broad cleanup | Runtime allowlist staging, content hashes, fresh build directories, no broad deletion |
| Session startup | Wrong labwc configuration path and reliance on autostart it did not launch | Explicit labwc config, compositor environment import, direct user-service start |
| Boot services | Agent startup/desktop/network ordering coupling | Independent static shell, agent and Chromium services; no network-online gate |
| Login | Live-user autologin configuration could persist after installation | Common profile sets session only; live-config owns live autologin; Pi uses normal login |
| Runtime packages | Missing native recovery apps and keyring pieces | Foot, Thunar, Xorg/Xwayland, gio, keyring/PAM, PackageKit, firmware packages |
| Splash/WebGL | Renderer failure could prevent startup; artificial loader wait | Independent bounded release, static material fallback and backend recovery UI |
| Provider execution | Single first tool, incomplete streaming and unsafe argument defaults | Bounded multi-step job loop, validated SSE, complete-batch schema check |
| Settings | Unvalidated merges, stale provider/key assumptions | Strict types, endpoint-scoped credentials, draft model tests and atomic config file writes |
| Networking/CLI | Secrets could flow through AI Wi-Fi tooling; CLI lacked session token | Native network chooser; CLI bootstraps session token |
| Files | Symlink/overwrite/race risks, incomplete trash metadata | no-follow descriptor traversal, no-replace moves, bounded regular-file copies, recoverable Trash |
| Pi GPIO | Fixed controller assumption and transient output command | libgpiod v2 controller discovery, held output requests |
| Voice | Fragile recognition assumptions and capture lifecycle | Opt-in local WAV transcription bridge, cancellation and pending-permission cleanup |
| API recovery | Backend was also the only UI asset server | Separate same-origin proxy keeps shell assets available during harness failure |

## Security changes

- No hard-coded real API keys were found or added. Build staging does not copy profile
  configuration, credentials, logs, caches, tests, build products or the entire checkout.
  Review any new runtime source before building; no allowlist can detect a secret
  deliberately inserted into otherwise allowed source.
- Keys are Secret Service entries scoped to provider plus normalized endpoint. Browser
  bootstrap returns only flags. No plaintext credential file fallback. Present-but-broken
  keyrings fail save/delete rather than claiming success.
- Provider redirects are refused. Remote endpoints require HTTPS; local inference may
  use loopback HTTP. Error bodies are suppressed. Model-list failure permits manual IDs.
- Host/Origin/session checks and CSP tighten the local API boundary.
- A malformed/truncated provider response never becomes an executable tool call; provider
  failure does not silently reinterpret the request into a different local action.
- Read-file sharing, file moves, camera, screenshots and GPIO changes require approval.
  Trash, installation and power actions require an extra confirmation phrase.
- Permanent deletion, package removal, recursive copies, arbitrary root/shell commands,
  purchases and sending messages are not exposed as executable AI operations.
- Audit records redact sensitive text/results and rotate. Same-user local malware is not
  within the isolation guarantees of this architecture.
- Pi SSH is off; initial login is unique per build; passwordless sudo rule is removed.
  Build hosts must remain private because OS login material can exist in build caches.
- Old destructive install/uninstall convenience scripts are disabled; they no longer
  silently copy services or recursively delete a user-selected application directory.

## Visual and interaction changes

Pearl/platinum layered material, graphite text, restrained champagne/gold accents,
translucent light panels, a dimensional iridescent sphere, and a travelling spectral
light signature replace the dominant dark aesthetic. The logo remains recognizable.
The wake effect is brief and bypassable; it never waits on the shader or provider.
It runs at session start, not during firmware or early kernel boot.

Tap the orb for a spatially connected input; recent activity stays optional.
Listening, transcription, thinking, directed tool motion, warm permission emphasis,
success expansion, controlled error and desaturated offline states are represented.
Pointer response is slight and touch compresses the orb. Visible Stop/mute controls,
keyboard focus outlines, reduced motion and a WebGL fallback are included.

The orb shader is localized and capped; animations stop offscreen/hidden, with lower
idle frequency. These are implementation limits, **not measured Iris Xe benchmarks**.
Visual layout/accessibility/shader compilation on a real browser still needs QA.

## SmilyAI API integration

Built-in choice in onboarding and Settings, with default base URL
https://apismilyai.pythonanywhere.com/v1. Users supply their own key and model.
GET /v1/models populates a datalist; manual model entry remains available.
POST /v1/chat/completions supports streaming SSE and nonstreaming configuration.
The parser bounds response size/time and validates finish markers, function IDs and
complete JSON objects. Invalid keys, HTTP failures, rate limits and interruptions
return recoverable errors without printing provider bodies or keys.

The live SmilyAI service was not contacted with an account in this verification.
Provider tests use controlled fixtures. Compatibility with every model's tool-calling
behaviour is not assumed. Other native APIs require compatible gateways.

## Tests performed

- 70 Python unittest cases passed: config loading/persistence/rollback, first/subsequent
  boot flags, SmilyAI defaults, credential scopes, redaction, model listing, invalid keys,
  malformed/interrupted SSE, cancellation, schemas, permission expiry/immutability,
  bounded agent loop, observations, no-overwrite/path rules, Trash, HTTP origin/session
  boundary, frontend API roundtrips, independent static UI with simulated backend failure,
  hardware-detection fallback, image definitions and staging.
- 9 Node.js tests passed using isolated JavaScript contexts: bounded splash, error release,
  reduced motion, absent WebGL, opt-in microphone, denied microphone, release-before-grant,
  PCM WAV encoding, and untrusted-content rendering checks.
- Python compilation, every shell JavaScript syntax check, build-script shell syntax,
  rootfs staging, XML parsing and structural image checks passed.
- These Node tests are not real-browser screenshots, full DOM integration tests or GPU tests.
- systemd-analyze user-manager verification could not initialize in this environment
  (no user RuntimeDirectory). No service-start success is claimed.
- No QEMU/Docker/live-build/Chromium executable was available for full builds or local
  browser validation. An earlier dependency-install attempt was blocked by the host's
  permission environment. The cloud browser could not reach loopback. Those restrictions
  were not bypassed.

See TEST_RESULTS.txt for the actual final check transcript.

## Known remaining issues / release gates

1. Both full image builds, BIOS/UEFI boot, graphical installation and installed login
   require execution on the documented hosts. Package availability and upstream
   pi-gen changes can still break a build; the source tests cannot detect all such issues.
2. No Secure Boot signing, signed update repository, A/B rollback or recovery partition.
   Package repositories/base images are not frozen; binary reproducibility is not claimed.
3. No OEM per-device account wizard. Pi uses a build-specific initial account/password,
   which must be changed after first login. Do not broadly distribute personal images.
4. Voice requires a separate local speech service/model; optional TTS depends on installed
   local voices. No wake-word detector, always-on microphone or bundled speech model.
5. Browser purchasing/automation and sending messages are not implemented. No simulated
   purchase or fabricated completion is presented. Labwc agent window control is limited;
   native shortcuts work independently, while structured window tooling targets Sway/X11.
6. Cancellation prevents subsequent steps; it cannot reverse completed actions or instantly
   abort every socket read, subprocess or PackageKit daemon transaction. The 600-second
   task deadline is checked between steps, not a hard kill of a privileged operation.
7. Tasks do not resume across backend crashes/power loss. API keys with no Secret Service
   client are memory-only. Autologin/live sessions may need manual keyring unlocking.
8. File reads/copies are deliberately limited; hidden paths, symlinks, recursive copy and
   cross-filesystem moves/Trash fail rather than silently escalating. Use native Files.
9. PackageKit privilege prompts, Wi-Fi/Bluetooth, audio, brightness, suspend/resume,
   multi-monitor/HiDPI, camera and GPIO need system-level testing.
10. GPIO pin ownership ends on process exit; not suitable for safety-critical machinery.
    Camera capability currently reflects command availability, not verified sensor presence.
11. UI text streaming currently displays concise progress and the final response rather
    than continuously painting every token. Conversation state lives within one task.
12. Contrast/focus design is accessibility-conscious, not a formal WCAG conformance audit.
    No physical hardware, real GPU performance or browser visual verification was completed.

## Build and VM instructions

Exact prerequisites, commands, expected outputs, credential handling, BIOS/UEFI QEMU
commands, installer steps and test checklist are in BUILD_AND_TEST.md.
The manual-only workflow in .github/workflows/build-images.yml does not deploy or
publish a release. Use a private repository if uploading the source for CI.

## Upstream references consulted

- [Official pi-gen repository and ARM64 instructions](https://github.com/RPi-Distro/pi-gen)
- [labwc configuration](https://labwc.github.io/labwc-config.5.html)
- [labwc actions](https://labwc.github.io/labwc-actions.5.html)
- [Debian trixie live-build configuration](https://manpages.debian.org/trixie/live-build/lb_config.1.en.html)
- [Debian live-config](https://manpages.debian.org/trixie/live-config-doc/live-config.7.en.html)

SOURCE_MANIFEST.sha256 in the archive hashes all distributed members except itself.
The outer archive SHA-256 is supplied with the download response.
