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
