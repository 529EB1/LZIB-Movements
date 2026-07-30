# LZIB Movements

LZIB Movements is a private, non-commercial, one-way Discord alert service for aviation
enthusiasts watching Bratislava Airport (BTS/LZIB). It has no website and is completely
independent of AstroRemote, Airplanes.live, Virtual Radar Server (VRS), Discord, and any photo
provider.

## What it reports

One Airplanes.live geographic query (default 250 NM) is reused for both rule sets:

* **Special Arrivals** — an airborne flight whose normalized callsign has a local VRS route
  database match ending at LZIB. A registration in `special_registrations.json` produces a
  “Special-livery aircraft” alert; the special list takes priority over the ignored list. An
  ignored registration produces no registration alert. Every other known registration produces
  an “Unusual aircraft registration” alert. A missing registration never produces this alert.
* **Unusual Movements** — an airborne aircraft at **exactly or within 40 km**, **strictly below
  8,000 ft**, descending by at least 100 ft/min, with a recent position, whose destination is
  unknown or matched somewhere other than BTS/LZIB. Recent obvious LZIB departures and duplicate
  movements are suppressed. Exactly 40 km is included; exactly 8,000 ft is excluded.

VRS data is historical standing data, **not an official live filed flight plan**. Discord wording
says “Route database match: ORIGIN → DESTINATION”; it never says confirmed destination. Routes may
be stale, seasonal, missing, reused, or wrong. Heading alone is never treated as a destination.
Likewise, an unusual-movement alert is not confirmation of an arrival, emergency, or special
aircraft. All alerts are informational and unofficial.

## Sources and known limitations

The adapter follows the Airplanes.live v2 point endpoint
`GET https://api.airplanes.live/v2/point/{lat}/{lon}/{radius}` and documented readsb-style fields
including `ac`, `now`, `hex`, `flight`, `r`, `t`, `lat`, `lon`, `alt_baro`, `alt_geom`, `gs`,
`track`, `baro_rate`, `geom_rate`, `seen`, `seen_pos`, `category`, and `ownOp`. The point radius is
nautical miles and the published maximum is 250 NM. Published guidance requires no more than one
request per second. Provider availability, response coverage, and account/free-tier quotas can
change; therefore the independently configurable local budget defaults to 500/day with 40 held in
reserve and uses UTC-day boundaries. The monitor does not use per-aircraft requests. Although the
API documents identifier endpoints, no extra batch request is made because a stable batch contract
and its quota benefit could not be verified in this environment.

Standing data is downloaded from the official `vradarserver/standing-data` GitHub project archive.
The importer requires `airports.csv` and `routes.csv`, validates named columns, filters archived or
deleted rows, resolves airport codes to ICAO, and atomically swaps the indexed SQLite route table.
An ETag or archive SHA-256 identifies an update. The previous table remains intact if download,
archive, validation, or import fails. Upstream schema/release changes remain an operational risk and
must be checked with a dry run before production updates.

The default aerodrome reference point is `48.170167, 17.212667` (48°10′12.6″N,
17°12′45.6″E), transcribed from the Slovak Republic AIP, LZIB AD 2.2. Coordinates remain
configurable. Official sites were unreachable from this build environment, so current contracts
and coordinates require a final operator review against the live official documentation.

Photographs are deliberately disabled. A replaceable `PhotoProvider` interface is present, but no
PlaneSpotters.net implementation is included because its current public endpoint and attribution
terms could not be verified. JetPhotos and image-search sites are never scraped. A missing photo
cannot block an alert.

## Local setup and configuration

Python 3.12 is required.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps --no-build-isolation .
cp .env.example .env
```

Create incoming webhooks in the Discord channel settings under **Integrations → Webhooks**, one for
each channel, then put the URLs only in `.env` locally or `/etc/lzib-movements.env` on the server.
Never commit or paste them into logs.

Populate `data/special_registrations.json`:

```json
[{"registration": "EX-AMPLE", "livery": "Example only", "notes": ""}]
```

Populate `data/ignored_registrations.json` with strings such as `["EX-AMPLE"]`. These are format
examples, not real suggested registrations. Values are trimmed, uppercased, hyphen-normalized,
validated, and deduplicated. Do not put airline names in either file. Lists reload every scan.

```bash
python -m lzib_movements update-routes
python -m lzib_movements --check-config
python -m lzib_movements --dry-run --once
python -m lzib_movements --once
python -m lzib_movements
```

`--dry-run` retrieves/evaluates live aircraft but never contacts Discord. `--check-config` validates
settings, timezone, lists, database access, route presence/age, numeric budget thresholds, and the
presence (without disclosure) of both webhook values. Temporary provider failures yield no alerts
and do not crash the continuous monitor.

## State and safety

SQLite stores migrations, alert history, observations, recent departure state, UTC request counts,
the route index/metadata, and optional photo metadata. Alert history survives restarts. Cleanup
retains observations for 48 hours, alerts for 30 days, and request counts for 14 days. The provider
budget is claimed transactionally before a request; normal monitoring stops at `limit - reserve`.
HTTP 429 and timeouts are recoverable scan failures. Discord delivery uses bounded retries and
redacts webhook URLs from its own errors.

## Tests and development checks

Tests use only mock transports and local CSV/ZIP fixtures. Network access is forbidden by test
design.

```bash
pytest
ruff check .
ruff format --check .
mypy
```

## Ubuntu installation (does not deploy automatically)

Clone this repository onto the intended Ubuntu host, review `/opt/lzib-movements` and
`/var/lib/lzib-movements` as dedicated paths, then run `sudo scripts/install-ubuntu.sh` from the
checkout. It creates only the dedicated `lzib-movements` system user and directories, a separate
virtual environment/database, and hardened systemd units. It does not know or touch any AstroRemote
path, service, account, port, variable, or data. The installer creates a placeholder environment
file and stops for manual configuration before validation; it never starts live alerts.

Configure `/etc/lzib-movements.env` as root. It must be owned by `root:lzib-movements`, mode `0640`,
and contain the two webhook URLs. Then rerun the installer, inspect its successful config check, and
run a dry scan. Only after reviewing the result enable services:

```bash
python -m lzib_movements --check-config
python -m lzib_movements --dry-run --once
python -m lzib_movements update-routes

sudo systemctl enable --now lzib-movements
sudo systemctl status lzib-movements
sudo systemctl enable --now lzib-routes-update.timer

journalctl -u lzib-movements -f
journalctl -u lzib-routes-update.service
```

Manage it with `sudo systemctl stop|restart lzib-movements`. For a reviewed fast-forward Git update,
run `sudo scripts/update.sh`; it stops the service, backs up the application, updates locked
dependencies, validates configuration, and restores the backup on failure. Run
`sudo scripts/uninstall.sh` to remove code/units while preserving secrets, registrations, state, and
the user. Only `sudo scripts/uninstall.sh --delete-data` removes persistent LZIB Movements data.

No live provider response, webhook delivery, route download, systemd operation, or Ubuntu
deployment was verified by the automated suite. After merging, the operator must populate both
registration files, clone on Ubuntu, add both secrets, run the installer, check configuration, run
one dry scan, inspect it, and only then enable the main service.
