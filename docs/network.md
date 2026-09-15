# Network measurements

SystemPulse provides two intentionally separate network measurements.

## Local interface throughput

```bash
systempulse network --speed
```

This command samples the operating system's cumulative interface counters twice and reports the
current local upload and download rate. It observes traffic already crossing the machine's network
interfaces and does not create internet benchmark traffic.

Plain `systempulse network` reports the same cumulative sent and received counters since the
operating system last reset them.

## Active internet speed test

```bash
systempulse speedtest
```

This command actively downloads and uploads progressively larger payloads through Cloudflare's edge
infrastructure. It reports decimal download and upload Mbps, median unloaded HTTP latency, unloaded
jitter, the provider, and the Cloudflare edge colo code when available.

SystemPulse uses a persistent native Python HTTPX client with HTTP/2 enabled. Its
Cloudflare-inspired CLI methodology reports P90 from the final stable transfer-size set, or the
largest completed valid set when no request reaches the stability threshold. Results can differ
from Cloudflare's browser test, which uses modern browser connections and the
PerformanceResourceTiming API; SystemPulse does not claim bit-for-bit numerical equivalence.
The latency value is application-layer response-start timing from HTTPS requests to the Cloudflare
edge. It is not ICMP ping. Different protocol behavior and timing APIs can therefore produce a
different value in Cloudflare's browser test.

The benchmark may consume significant bandwidth. It runs only when explicitly requested or chosen
from the interactive menu; it is not part of snapshot, live monitoring, history, save, serve,
configuration, process, or ordinary network commands. Its results are not written to SQLite
history or CSV.

Cloudflare's anycast routing selects the reachable edge through normal internet routing. SystemPulse
does not call an IP-geolocation service, infer the user's location, translate colo codes into city
names, or display a country or city. If response metadata does not include a usable colo code, the
UI shows `Unavailable` and retains the speed result.
