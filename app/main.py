"""HTTP layer: validation and serialization only; calculation lives in analytics."""

import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import FastAPI, HTTPException, Query
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.analytics import clean, load_raw, moving_average

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Moving Average API", docs_url=None)
OBSERVATIONS = clean(load_raw())  # validated once at startup; exclusions logged once
MAX_WINDOW = int(OBSERVATIONS.groupby("instrument").size().max())  # longest series
INSTRUMENTS = sorted(OBSERVATIONS["instrument"].unique())


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.get("/docs", include_in_schema=False)
def docs() -> HTMLResponse:
    """Swagger UI with parameters editable immediately and the "Try it out" button hidden."""
    page = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title,
        swagger_ui_parameters={"tryItOutEnabled": True},
    )
    hide_try_out = "<style>.try-out { display: none; }</style></head>"
    return HTMLResponse(page.body.decode().replace("</head>", hide_try_out))


def to_output(value: Decimal | None, decimals: int | None) -> float | None:
    """Serialize an exact average; rounding (half up, e.g. 0.125 -> 0.13) happens before float."""
    if value is None:
        return None
    if decimals is not None:
        value = value.quantize(Decimal(1).scaleb(-decimals), ROUND_HALF_UP)
    return float(value)


class Observation(BaseModel):
    instrument: str
    date: date
    price: float
    moving_average: float | None


@app.get("/moving-averages", response_model=list[Observation])
def get_moving_averages(
    window: int = Query(
        20, ge=1, le=MAX_WINDOW, description="Number of trading days (observations) in window"
    ),
    decimals: int | None = Query(
        None, ge=0, le=10, description="Round moving averages half up; omit for full precision"
    ),
    start_date: date | None = Query(None, description="First date returned (inclusive)"),
    end_date: date | None = Query(None, description="Last date returned (inclusive)"),
    instrument: str | None = Query(
        None,
        description="Only this instrument; omit for all",
        json_schema_extra={"enum": INSTRUMENTS},  # dropdown in Swagger UI
    ),
) -> list[Observation]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, "start_date must be on or before end_date")
    if instrument is not None and instrument not in INSTRUMENTS:
        raise HTTPException(422, f"instrument must be one of {INSTRUMENTS}")
    # Calculate on the full history and filter afterwards, so windows at the range start are full.
    # Instruments are calculated independently, so filtering on one first is safe.
    selected = (
        OBSERVATIONS[OBSERVATIONS["instrument"] == instrument] if instrument else OBSERVATIONS
    )
    df = moving_average(selected, window)
    df["date"] = df["date"].dt.date
    df = df[(df["date"] >= (start_date or date.min)) & (df["date"] <= (end_date or date.max))]
    df["moving_average"] = df["moving_average"].map(lambda v: to_output(v, decimals))
    return [Observation(**r) for r in df.to_dict("records")]
