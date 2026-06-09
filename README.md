# Tag_Test

## Samsara API helper

This repository includes a small Python CLI for calling the Samsara REST API:

```bash
python3 scripts/samsara_api.py /fleet/vehicles --paginate
```

### Setup

Set your Samsara token in an environment variable. Do not commit the token or
paste it into scripts:

```bash
export SAMSARA_API_TOKEN="your_samsara_token_here"
```

If a token has been shared in chat, logs, or source control, rotate it in the
Samsara dashboard before using it for production automation.

### Examples

List vehicles and follow pagination:

```bash
python3 scripts/samsara_api.py /fleet/vehicles --paginate
```

List drivers with a query parameter:

```bash
python3 scripts/samsara_api.py /fleet/drivers --param limit=100
```

Save output to a JSON file:

```bash
python3 scripts/samsara_api.py /fleet/vehicles --paginate --output vehicles.json
```

Run a write request only when you intentionally want to modify dashboard data:

```bash
python3 scripts/samsara_api.py /addresses \
  --method POST \
  --body-json '{"name":"Main Yard","formattedAddress":"123 Example St"}' \
  --yes
```

The script supports:

- Bearer-token authentication through `SAMSARA_API_TOKEN`
- `GET`, `POST`, `PUT`, `PATCH`, and `DELETE`
- query parameters with repeated `--param KEY=VALUE`
- JSON bodies with `--body-json` or `--body-file`
- Samsara cursor pagination with `--paginate`

## Emergency lights speed monitor

`scripts/samsara_emergency_lights_monitor.py` watches the vehicle named
`Nates Rav4` and keeps it in the `emergency lights` tag while it is traveling
over 45 MPH. When the vehicle is at or below 45 MPH, the script removes it from
that tag.

The monitor uses:

- `GET /fleet/vehicles` to find the vehicle by name
- `GET /tags` and `GET /tags/{id}` to find and read the tag
- `GET /fleet/vehicles/stats?types=gps` to read `gps.speedMilesPerHour`
- `PATCH /tags/{id}` to replace the tag's vehicle membership only when needed

Start with a dry run. This reads Samsara data and prints the change it would
make, but does not update the tag:

```bash
export SAMSARA_API_TOKEN="your_samsara_token_here"
python3 scripts/samsara_emergency_lights_monitor.py --once
```

Run continuously in dry-run mode:

```bash
python3 scripts/samsara_emergency_lights_monitor.py
```

Apply live tag updates continuously:

```bash
python3 scripts/samsara_emergency_lights_monitor.py --apply
```

If the dashboard names are different, pass explicit names:

```bash
python3 scripts/samsara_emergency_lights_monitor.py \
  --vehicle-name "Nate's Rav4" \
  --tag-name "Emergency Lights" \
  --apply
```

You can also skip name lookup by passing IDs:

```bash
python3 scripts/samsara_emergency_lights_monitor.py \
  --vehicle-id "123456789" \
  --tag-id "987654321" \
  --apply
```

Useful options:

- `--threshold-mph 45` changes the speed cutoff.
- `--poll-seconds 5` changes how often the script checks Samsara.
- `--once` performs a single check and exits.
- `--apply` is required before the script modifies tag membership.
