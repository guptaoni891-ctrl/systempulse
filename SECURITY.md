# Security policy

## Supported code

SystemPulse has not yet published its planned 2.0 release. Security fixes are considered on a
best-effort basis for the current development branch and, after releases begin, the latest released
line. Older releases are not guaranteed to receive backports.

| Version or branch | Security support |
|---|---|
| Current development branch | Best effort |
| Latest release, when published | Best effort |
| Older releases | Not guaranteed |

This policy can be expanded when the project has multiple maintained release lines.

## Reporting a vulnerability

Use GitHub's **Security** tab and **Report a vulnerability** private-reporting flow if it is enabled
for this repository. Include affected versions, platform, impact, reproduction conditions, and a
minimal proof of concept where safe.

If private vulnerability reporting is not available, open a GitHub issue containing no exploit,
credentials, personal data, or other sensitive details and ask the maintainer to establish a private
channel. Do not publish a working exploit in a public issue before the maintainer has had a reasonable
opportunity to respond.

No dedicated security email address is currently advertised.

## Relevant limitations

- The Prometheus endpoint uses plain HTTP and has no built-in authentication, authorization, or TLS.
- It binds to `127.0.0.1` by default. Binding to `0.0.0.0` or another non-loopback address exposes
  system metrics on reachable interfaces.
- Metrics can reveal host utilization, capacity, temperature, traffic volume, and GPU presence.
- SQLite history and CSV output are local files protected by the permissions of the user account and
  operating system. SystemPulse does not encrypt them.
- NVIDIA monitoring executes `nvidia-smi` from the process `PATH`; run SystemPulse with a trusted
  executable search path.
- SystemPulse is an observability tool, not a sandbox or endpoint security product. It should not be
  run with elevated privileges unless the operator has a separate reason to do so.

Core monitoring does not require internet access. The only network listener created by SystemPulse
is the explicitly started Prometheus exporter.
