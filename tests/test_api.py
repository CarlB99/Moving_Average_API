import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_default_window_returns_all_instruments():
    response = client.get("/moving-averages")
    assert response.status_code == 200
    body = response.json()
    assert set(body[0]) == {"instrument", "date", "price", "moving_average"}
    assert {r["instrument"] for r in body} == {"Inst1", "Inst2"}
    assert all(85 < r["price"] < 120 for r in body)


def test_decimals_rounds_output_only():
    full = client.get("/moving-averages", params={"window": 3}).json()
    assert full[2]["moving_average"] == 98.59  # exact, not 98.58999999999999
    # Inst1 2023-03-30: (107.53 + 101.80) / 2 = 104.665 exactly, so half up gives 104.67
    full = client.get("/moving-averages", params={"window": 2}).json()
    rounded = client.get("/moving-averages", params={"window": 2, "decimals": 2}).json()
    assert full[13]["moving_average"] == 104.665
    assert rounded[13]["moving_average"] == 104.67
    assert rounded[0]["moving_average"] is None


@pytest.mark.parametrize(
    "params",
    [
        {"window": 0},
        {"window": "abc"},
        {"window": 513},  # longer than the longest series (Inst1: 512)
        {"window": 2**63},
        {"decimals": -1},
        {"decimals": 11},
        {"start_date": "2024-13-01"},
        {"start_date": "2024-03-28", "end_date": "2024-03-01"},  # start after end
        {"instrument": "Inst3"},
        {"instrument": "inst1"},  # names are case-sensitive
    ],
)
def test_invalid_parameters_return_422(params):
    assert client.get("/moving-averages", params=params).status_code == 422


def test_root_redirects_to_docs():
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


def test_longest_window_is_accepted():
    body = client.get("/moving-averages", params={"window": 512}).json()
    assert sum(r["moving_average"] is not None for r in body) == 1  # last Inst1 row only


def test_docs_editable_without_try_it_out_button():
    page = client.get("/docs").text
    assert '"tryItOutEnabled": true' in page
    assert ".try-out { display: none; }" in page


def test_date_range_filters_output_after_calculating_on_full_history():
    full = client.get("/moving-averages", params={"window": 20}).json()
    params = {"window": 20, "start_date": "2024-03-01", "end_date": "2024-03-28"}
    ranged = client.get("/moving-averages", params=params).json()
    assert ranged == [r for r in full if "2024-03-01" <= r["date"] <= "2024-03-28"]
    assert all(r["moving_average"] is not None for r in ranged)  # no warm-up nulls
    assert min(r["date"] for r in ranged) == "2024-03-01"  # both bounds inclusive
    assert max(r["date"] for r in ranged) == "2024-03-28"


def test_date_range_with_one_bound_or_no_data():
    after = client.get("/moving-averages", params={"start_date": "2025-03-01"}).json()
    assert after and all(r["date"] >= "2025-03-01" for r in after)
    assert client.get("/moving-averages", params={"start_date": "2030-01-01"}).json() == []


def test_instrument_filter_returns_only_that_instrument_unchanged():
    full = client.get("/moving-averages", params={"window": 20}).json()
    inst2 = client.get("/moving-averages", params={"window": 20, "instrument": "Inst2"}).json()
    assert inst2 == [r for r in full if r["instrument"] == "Inst2"]
    assert len(inst2) == 509
