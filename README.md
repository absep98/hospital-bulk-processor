# Hospital Bulk Processor

A FastAPI service that takes a CSV of hospitals, creates them in the existing
[Hospital Directory API](https://hospital-directory.onrender.com/docs) as a single batch, and activates the batch
once every row has been created.

**Live demo:** https://hospital-bulk-processor-8zp0.onrender.com/docs

> The demo runs on Render's free tier, which sleeps when idle. The first request after a quiet period can take
> 30 to 60 seconds while it wakes up. The Hospital Directory API behaves the same way.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/hospitals/bulk` | Upload a CSV, create all hospitals as one batch, activate the batch if every row succeeded |
| `POST` | `/csv-preview` | Validate a CSV and return the parsed rows. Creates nothing |
| `GET` | `/` | Health check |

Interactive docs are at `/docs`.

### CSV format

```csv
name,address,phone
General Hospital,123 Main St,555-1234
City Care Clinic,"45 Oak Avenue, Suite 4",555-2345
St. Mary Medical Center,78 Pine Road,
```

- Required columns: `name`, `address`. The `phone` column is optional, and a blank phone is sent as `null`.
- Maximum 20 hospitals per file.
- UTF-8 text.

### Example

```bash
curl -X POST "http://localhost:8000/hospitals/bulk" \
  -H "accept: application/json" \
  -F "file=@hospitals.csv;type=text/csv"
```

```json
{
  "batch_id": "ed6a26a9-fab5-44fe-af7d-fc6d8d2987ec",
  "total_hospitals": 5,
  "processed_hospitals": 5,
  "failed_hospitals": 0,
  "processing_time_seconds": 7.18,
  "batch_activated": true,
  "hospitals": [
    { "row": 1, "hospital_id": 1340, "name": "General Hospital", "status": "created_and_activated" }
  ],
  "activation_error": null
}
```

Row statuses are `created_and_activated`, `created` (created but the batch was not activated), and `failed`
(with an `error` message).

### Error responses

Invalid files are rejected with `400` before any call is made to the Hospital Directory API:

| Cause | `detail` |
|---|---|
| Empty file | `CSV file is empty` |
| Missing `name` or `address` column | `failed to get all fields` |
| More than 20 rows | `got more than 20 rows` |
| Not valid UTF-8 | `File is not valid UTF-8 text` |

## How it works

```
POST /hospitals/bulk (CSV upload)
  1. Validate the file                    -> 400 on any problem, nothing is created
  2. Generate a batch UUID
  3. For each row, POST /hospitals/       -> concurrent, capped at MAX_CONCURRENT in flight
  4. If every row was created:
       PATCH /hospitals/batch/{id}/activate
  5. Return the per-row results and summary
```

## Design decisions

**Activate only if every row succeeded.** The Directory API creates batch hospitals as inactive so that a
half-loaded batch never goes live. If any row fails, the batch is not activated, `batch_activated` is `false`, and the
response lists which rows failed and why. The rows that were created stay inactive on the server under the returned
`batch_id`.

**Failed rows are data, not errors.** A bulk call where some rows fail still returns `200`, because the request itself
was processed. The failures are reported per row. Only an invalid upload returns `400`.

**One bad row does not stop the others.** Each row is created independently, and an exception from one row is caught
and recorded as that row's failure.

**Validate first.** The whole file is checked (encoding, headers, row count) before the first outbound request, so a bad
file costs nothing and leaves no partial batch behind.

**Activation failure is reported, not hidden.** If the activate call fails after all rows were created, the response
still includes the full results, with `batch_activated: false` and the reason in `activation_error`.

**Stateless.** Nothing is stored between requests, which the assignment allows. The batch ID in the response is the
handle for the Directory API's own batch endpoints.

## Performance

Creating hospitals one after another is slow, because each call to the Directory API takes roughly 5.5 seconds
(a free-tier server). The requests are independent, so they are sent concurrently with `asyncio.gather` and a
semaphore limits how many are in flight at once.

Measured against the live Hospital Directory API:

| Approach | Rows | Time |
|---|---|---|
| Sequential | 5 | 27.48 s |
| Concurrent, no limit | 5 | 7.18 s |
| Concurrent, limit 5 | 20 | 22.14 s |
| Concurrent, limit 10 | 20 | 11.91 s |
| Concurrent, limit 20 | 20 | 6.47 s |

Total time is roughly `ceil(rows / limit) x 5.5 s`, so with 20 rows a limit of 5 means 4 waves, 10 means 2 waves and 20
means 1. All runs completed with 0 failures.

The default limit is **10**. A limit of 20 was also fast and clean in testing, but the cap protects the downstream
server when several uploads arrive at the same time, and it is a single setting to tune (see Configuration). The same
10-limit run took 11.41 s deployed on Render and 12.59 s in Docker.

## Running it

### Locally

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Open http://localhost:8000/docs.

### Docker

```bash
docker compose up --build
```

Open http://localhost:8000/docs.

### Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -v
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MAX_CONCURRENT` | `10` | Maximum simultaneous requests to the Directory API per upload |

With Docker, set it in `docker-compose.yml`. On Render, set it under Environment.

## Testing

There are 9 tests in `test_main.py`:

- **CSV validation** (6): a valid file, an empty file, wrong headers, more than 20 rows, and a non-UTF-8 file. Each
  asserts both the status code and the error message.
- **Bulk endpoint** (3): all rows succeed; all rows fail; creation succeeds but activation fails.

The Hospital Directory API is mocked with [respx](https://lundberg.github.io/respx/), so the tests are fast and never
touch the real server. The failure tests also assert the activation rule directly: when rows fail, the activate
endpoint is never called.

## Deployment

Deployed on Render as a Python web service from this repository.

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Environment: `PYTHON_VERSION=3.12.3`

## Limitations and next steps

- **No progress tracking or resume.** A failed batch has to be retried by uploading the file again. The rows already
  created remain on the server under the old `batch_id`, so a retry creates duplicates unless the old batch is deleted
  first with `DELETE /hospitals/batch/{batch_id}`. A resume feature would track per-row state and only retry the
  failed rows.
- **The concurrency limit is per upload,** not global. Several simultaneous uploads each get their own limit. A shared
  semaphore would cap the total.
- **No authentication or rate limiting** on the service itself.
- **No de-duplication** of rows within a file.
- **Blank `name` or `address` values** are passed through, and the Directory API decides whether to reject them.
  Per-row validation before the call would give clearer errors.
- **The whole upload is held in memory.** That is fine for a 20-row limit.
