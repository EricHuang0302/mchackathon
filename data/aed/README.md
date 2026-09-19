# Taiwan MOHW AED open data

The production AED dataset comes from the Ministry of Health and Welfare
national export:

- Dataset page: <https://data.gov.tw/dataset/12063>
- CSV endpoint: <https://tw-aed.mohw.gov.tw/openData?t=csv>
- Publisher: Ministry of Health and Welfare, Department of Medical Affairs
- Published update frequency: daily
- License: [Government Data Open License, version 1.0](https://data.gov.tw/license)

The repository does not contain a downloaded government dataset. Tests use
`data/fixtures/synthetic_mohw_aed_sample.csv`, whose rows are invented.

## Update the local cache

Run this command from the repository root:

```sh
python -m data.aed.update_mohw --cache-dir var/aed
```

The command downloads the CSV with the Python standard library, validates the
published Chinese header, normalizes every row, and requires at least one
valid AED with no more than half of the rows rejected before publishing it.
It writes immutable CSV and metadata files
under `var/aed/versions/`, then atomically replaces `var/aed/current.json`.
A network, decoding, header, or validation failure leaves the previous active
generation unchanged. The cache directory is ignored by Git.

The JSON metadata records the source and dataset URLs, license, retrieval and
source-update timestamps, dataset version, SHA-256 digest, byte and row counts,
and validation counts. Consumers should call
`load_cached_mohw_source(Path("var/aed"))`; it verifies the digest before
returning an adapter.

Optional configuration:

| CLI option | Environment variable | Default |
| --- | --- | --- |
| `--cache-dir` | `AED_MOHW_CACHE_DIR` | `var/aed` |
| `--source-url` | `AED_MOHW_SOURCE_URL` | MOHW national CSV endpoint |
| `--timeout` | `AED_MOHW_TIMEOUT_SECONDS` | `60` seconds |

`--source-url` exists for controlled mirrors and tests. Production deployments
should retain the official HTTPS endpoint unless an explicitly approved mirror
preserves the same schema and provenance.

## Field and availability behavior

`AEDID` is the stable AED identifier and `場所ID` is retained as the source
location identifier. The adapter maps the address and WGS84 `地點LAT` /
`地點LNG` coordinates directly. Placement text, location description,
free-text opening notes, and the published contact number are preserved as
access notes.

Weekday, Saturday, and Sunday columns are converted separately. A missing or
partial pair becomes `unknown` for that day group; it is never guessed to mean
closed. Free-text holiday exceptions remain in access notes and are not
silently converted into calendar rules. Callers must display that caveat when
precise holiday availability matters.
