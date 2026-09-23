# SmilyAI OS 0.3.1 architecture

## Boot and process ownership

Linux boots system services, including NetworkManager and LightDM.
LightDM creates an authenticated user session and starts
`/usr/local/bin/smilyai-session`. It runs labwc with an explicit, shared configuration.
labwc's autostart imports WAYLAND_DISPLAY and session variables into the user service
manager, then starts three separate services:

| Service | Purpose | Failure behaviour |
| --- | --- | --- |
| smilyai-ui | Static assets and same-origin API proxy on loopback 47810; systemd notify-ready after bind/asset checks | Restart after five seconds, up to three starts per 30 minutes |
| smilyai-harness | Config, providers, jobs, permissions and structured tools on loopback 47811 | Restart after three seconds; UI stays available |
| smilyai-shell | Sandboxed Chromium application window, concrete Wayland/X11 backend | Restart after ten seconds, up to three starts per 30 minutes; permanent preflight failures do not retry |

No network-online dependency, AI call, shader compile or microphone grant blocks
the session. The UI service has a 120-second startup deadline; the shell's After=
dependency waits for its READY notification. Manual and managed launches additionally
probe static readiness for at most 90 seconds and check the display for at most 30
seconds, exiting with a labelled diagnostic on failure. Native labwc shortcuts work independently of both
HTTP processes: Super+Return terminal, Super+E files, Super+N network,
Super+R explicitly reset failed limits/restart services, Super+Space raise SmilyAI,
Alt+Tab switch apps. The same launcher runs manually with `smilyai-shell`; its
`--diagnose` mode checks preflight without claiming a visible window.
A backend outage displays a recovery strip and exponentially backed-off retries.
The visual wake sweep dismisses immediately on readiness, has a 2.2-second ceiling,
and also releases on JavaScript errors. It is a session-start effect, not an early
firmware/initramfs Plymouth replacement.

## Agent loop

One in-memory active job per harness, at most 12 model turns and a 600-second
between-step deadline. The model receives registered JSON schemas, not a shell.
Responses must finish cleanly; SSE requires a finish reason and DONE terminator.
All calls in a model batch are schema-validated before any executes.

Each call passes permission policy, executes as the login user, produces a concise
observation and returns it to the model. Confirmation pauses the exact job, with
copied arguments, a one-use token, a five-minute expiry and an additional phrase for
administrative/destructive operations. Stop marks the job cancelled and wakes any
approval wait. Completed operations are not undone; an already-started syscall,
provider socket read or system daemon operation may finish before cancellation takes effect.

Jobs and conversation context are not persisted across a harness restart. Configuration
and redacted activity are persisted. The agent is persistent across steps within a task,
not a durable workflow engine across power loss.

## Trust boundaries

- HTTP binds to IPv4 loopback only. Host, Origin and Fetch-Site checks prevent casual
  DNS-rebinding/cross-origin access. All sensitive APIs require an in-memory session token.
- Chromium keeps its sandbox enabled. Assets have a restrictive same-origin CSP.
  Provider traffic and keys remain in the harness, not browser JavaScript.
- This protects against remote web origins and model-supplied tool input; it is **not**
  isolation from another malicious process running as the same Linux user.
- The harness has NoNewPrivileges and read-only system paths, with writable home and
  runtime directories. It is not root. PackageKit/power operations use existing system
  services and OS authorization, not a model-controlled root shell.
- Files are bounded to configured roots; hidden credential directories and symlinks are
  refused. Directory descriptors and no-follow opens reduce path races. Copy and move
  do not overwrite. Recursive copy and permanent deletion are disabled. Trash metadata
  permits recovery using native file tools; cross-filesystem Trash fails safely.
- Reads that can send file contents to AI require confirmation. Tool results remain
  untrusted model input. Prompt injection cannot grant new tool capabilities, but model
  intent may still be wrong: approvals must be read carefully.
- Trusted system desktop entries are launched via gio with fixed argv. User-written
  desktop files are not model-launchable. Native apps launched from the harness inherit
  its restrictions; use the compositor's native terminal shortcut for normal administration.
- Purchases, messages, arbitrary shell execution and disk formatting are not registered
  tools. No purchase occurs without confirmation because no purchase tool exists.
- Audit logs redact keys, text, content and full results and rotate at 2 MB. Filenames,
  tool names and metadata can still be private; logs are owner-only.

## Providers and credentials

SmilyAI, OpenAI, OpenRouter, Ollama, llama.cpp and custom gateways use one strict
OpenAI-compatible adapter. Anthropic/Gemini selections require a compatible gateway;
native wire formats are not implemented. HTTPS is required except loopback HTTP for
local inference. Redirects are refused so a key cannot follow a redirect to another host.
Changing the configured endpoint never reuses a saved credential from the old endpoint.

Secret Service stores keys under a hash of provider kind plus normalized endpoint.
The UI sees only presence/persistence flags. Keys are masked during entry and cleared
after save/close. A successful GET models is a discovery test, not proof that a particular
model can generate or call tools. Manual model IDs are supported. Provider error bodies
are not reflected into logs/UI. Nonstandard/incomplete streams fail closed.

## Rendering and voice

A small orb-only WebGL 1 shader is capped at 560 × 560 backing pixels. Idle rendering
is approximately 10 fps, active at most 30 fps; hidden/offscreen rendering stops.
Reduced motion renders a still frame. WebGL unavailable/lost uses a CSS material fallback.
Spectral surface sweeps use short compositor transforms rather than a continuous
full-screen shader.

Push-to-talk uses getUserMedia only after user action and opt-in, an AudioWorklet,
30-second recording bounds, WAV conversion, and a local speech-server bridge.
Release sends the recording; cancellation closes microphone tracks. No continuous
capture or wake-word detector is installed. TTS is optional and restricted to local voices.

## Compatibility limits

labwc runs ordinary native applications, but agent-driven window management is currently
implemented only for Sway/X11 tooling when detected. The default labwc session retains
native window shortcuts. Pi GPIO resolves controller lines dynamically through libgpiod v2;
output ownership lasts only as long as the harness process. Never use this for safety-critical
actuators. Camera/GPIO presence, permissions and behaviour require physical testing.
