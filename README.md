# Moving Average API

A REST API, built with FastAPI, that calculates a moving average of the price for each
instrument in the supplied dataset.

- **Framework:** FastAPI
- **Interface:** REST API, usable from the browser (Swagger UI at `/docs`) or the terminal
  (`curl`)
- **Endpoint:** `GET /moving-averages?window=20`
- **Input:** window size as a query parameter: `window`, in trading days, default 20, from 1
  up to the length of the longest series (512 for the supplied data). Optional:
  - `decimals`, 0–10, rounds the output half up.
  - `start_date` and `end_date` (`YYYY-MM-DD`, inclusive) limit the dates returned. Averages
    are still calculated on the full history, so the first date in the range already has a
    complete window.
  - `instrument` (`Inst1` or `Inst2`) returns a single instrument. Leave it out for all.
- **Output:** JSON containing instrument, date, price and the calculated moving average
- **Validation:** FastAPI/Pydantic. Invalid parameters are rejected with HTTP 422.
- **Documentation:** automatically generated Swagger UI at `/docs`. `/` redirects there.
  This follows standard FastAPI behaviour, so `/docs` needs internet access: Swagger UI's
  files load from a CDN.
- **Execution:** Uvicorn, optionally packaged in Docker
- **Testing:** pytest + FastAPI TestClient (using httpx)

The architecture is:

```text
HTTP Request → FastAPI → pandas calculation → JSON Response
```

The files are:
- `app/main.py`: the HTTP layer.
- `app/analytics.py`: data loading, validation and the calculation, with no HTTP code.
- `app/data/input_data.json`: the supplied dataset.

## Setup and run

You need Python 3.13 and [uv](https://docs.astral.sh/uv/). Versions are pinned in
`.python-version` and `uv.lock`.
- Runtime dependencies: FastAPI, pandas, uvicorn.
- Development dependencies: pytest, httpx, Ruff.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # only if uv is not installed
uv sync
uv run uvicorn app.main:app --reload              # then open http://localhost:8000
```

Docker (the container runs as a non-root user):

```bash
docker build -t moving-average .
docker run --rm -p 8000:8000 moving-average
```

Tests and lint:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Example

To try it in the browser, open <http://localhost:8000>, enter a `window` and click **Execute**.

From the command line:

```bash
curl "http://localhost:8000/moving-averages?window=3"
curl "http://localhost:8000/moving-averages?window=20&instrument=Inst1&start_date=2024-03-01&end_date=2024-03-28"
```

```json
[
  {"instrument": "Inst1", "date": "2023-03-13", "price": 98.45, "moving_average": null},
  {"instrument": "Inst1", "date": "2023-03-14", "price": 101.89, "moving_average": null},
  {"instrument": "Inst1", "date": "2023-03-15", "price": 95.43, "moving_average": 98.59}
]
```

The response is truncated here. Averages are calculated in exact decimal arithmetic, so the
third value is `98.59`, not the binary floating-point `98.58999999999999`.

## Key assumptions

- **Window = N trading days, which is N observations.** This is the market
  convention, and the data has one record per weekday.
  - If a record is excluded, the window reaches one day further back, so it still averages N
    real prices.
- **A complete window is required.** The first N−1 rows of each instrument return `null`.
- **The average is trailing and per instrument.** It is calculated in date order and never
  uses later prices.
- **Data is never filled, interpolated or corrected.** Invalid records are excluded and logged
  at startup. Interpolating would add look-ahead bias, and correcting assumes a cause that
  can't be verified. Excluding is deliberate: the true values can't be confirmed without the
  data owner.
- **Averages are calculated exactly**, in decimal arithmetic, and returned as standard JSON numbers.
  - Averages use decimal arithmetic, because binary floats would store 104.665 as
    104.66499999999999.
  - `decimals` rounds only the output, half up: 104.665 → 104.67.

Data-quality rules (both instruments end up with valid prices of 85–116):

| Rule | Records in the supplied data |
|---|---|
| Malformed record, invalid date (e.g. `2024-02-31`) or weekend date → excluded | 3 |
| Missing or non-numeric price → excluded | 1 (`null` on Inst2 2023-06-15; the duplicate with a price is kept) |
| Zero or negative price → excluded | 13 (Inst2) |
| More than 2.5× above or below the instrument median → excluded | 10 (Inst1, ~10× values) |
| Duplicate date: an identical one is kept once; conflicting ones are all excluded | 0 (the one duplicate date, Inst2 2023-06-15, is already resolved by the missing-price rule) |

**Why the outlier rule uses the median.** Valid prices are 0.85–1.16× their instrument's median
and the suspect ones are 9.1–10.7×, so the 2.5× cutoff has a wide margin on both sides. A
median/MAD modified z-score could be considered for instruments with different volatility. On
this data it excludes the same records, but its cutoff sits only ~2% above the highest valid
price, so 2.5× was preferred.

The median is taken over the full series. That is fine for a fixed historical file, but with a
live feed, future prices could change which past prices are excluded.

After cleaning, Inst1 has 512 rows and Inst2 has 509.

## Next steps

All required features are complete. Out of scope by choice: authentication, rate limiting,
databases, caching and production monitoring. With more time I would:

1. **Confirm the data rules with the data owner.** For example, check whether the negative and
   ~10× prices are known sign or decimal errors and whether they could be handled at source.
2. **Report excluded records through the API**, not only in the logs.
3. **Use a trailing median and an exchange calendar** for live or trending data.
4. **Add pagination** for larger datasets.
5. **Load other datasets**, for example by uploading or selecting a file with the same
   structure.

## Tools and AI assistance

- **Libraries and tools:** FastAPI, Pydantic, pandas, uvicorn, pytest, httpx, Ruff, uv and Docker.
- **Planning and decisions** were mine. I wrote the implementation plan in advance and made
  every data-handling and design decision, including the window definition, the exclusion
  rules, the 2.5× median rule and rounding.
- **Implementation** was done by Claude Code (Anthropic, Claude Opus 5.5), working from that
  plan. Claude:
  - profiled the data
  - presented options and trade-offs
  - wrote the code, tests, Dockerfile and README
  - ran the checks

  I then reviewed the result and modified parts of the code and documentation.
