# Capturing a demo

The repository currently includes `docs/dashboard.png`. It accurately shows the core terminal
layout, but it was captured before the current active-alert panel was introduced. A short GIF can
eventually demonstrate live refreshes and the alert area more clearly; no GIF is currently included
or required by the README.

## Recommended capture

1. Install SystemPulse in a clean virtual environment and verify `systempulse live` first.
2. Use a terminal theme with readable contrast and a monospace font. A window around 110–130 columns
   by 30–40 rows usually leaves enough room for the dashboard.
3. Close or hide shell prompts containing usernames, hostnames, repository paths, tokens, or remote
   addresses.
4. Review process names and GPU names before recording. Avoid showing sensitive workloads or device
   identifiers you do not want in a public repository.
5. Start recording, then run:

   ```bash
   systempulse live
   ```

6. Let the dashboard refresh several times. Aim for roughly 10–15 seconds.
7. If useful, create moderate, harmless CPU or network activity in another terminal so rate changes
   are visible. Do not manufacture a critical alert or expose external traffic solely for the demo.
8. Include CPU, RAM, disk, network, and the alert section. GPU metrics are optional and should appear
   only when a real supported NVIDIA device is available.
9. Stop SystemPulse with Ctrl+C and trim idle frames from the recording.
10. Crop to the terminal content, reduce the frame rate if necessary, and optimize the output for a
    practical repository size while keeping text legible.
11. Save the final animation as `docs/demo.gif`.
12. Replace or supplement the existing dashboard image reference in `README.md` only after confirming
    the GIF renders correctly on GitHub.

No particular recording application is required. Use any local screen recorder that can export GIF
directly or produce a short video that can be converted with an offline tool.

## Privacy checklist

Before committing the capture, inspect individual frames for:

- Usernames and home-directory paths.
- Hostnames, IP addresses, interface names, or remote targets.
- Shell history and environment values.
- Sensitive process, VM, container, or project names.
- Notifications or content from other applications.
- Serial numbers or unusually identifying GPU/device text.

Keep `docs/dashboard.png` as the fallback until a newer capture is both accurate and privacy-safe.
