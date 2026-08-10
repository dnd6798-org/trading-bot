"""
Verifies scripts/stress_test_pcs.py's entry-timing rule (last SPY trading
day strictly before the window), trough-finding, and the breach/sizing
arithmetic (REDESIGNED: narrow-zone strikes with an assumed $1 achievable
increment, structural-width cap, 2% defined-risk sizing override) —
against a small synthetic SPY series, no network calls.
"""
from src.data_ingestion import Candle
from scripts.backtest_donchian_ensemble import PAPER_VALIDATION_CAPITAL
from scripts.backtest_put_credit_spread import PCS_RISK_PER_TRADE_PCT
from scripts.stress_test_pcs import find_entry_date, find_trough, run_scenario, ASSUMED_NARROWEST_INCREMENT_DOLLARS


def _bar(date_str, close):
    return Candle(symbol="SPY", timestamp=f"{date_str}T00:00:00+00:00", open=close, high=close, low=close, close=close, volume=1)


def _series(dates_closes):
    candles = [_bar(d, c) for d, c in dates_closes]
    return {"symbol": "SPY", "candles": candles, "date_index": {c.timestamp[:10]: i for i, c in enumerate(candles)}}


def test_find_entry_date_picks_last_date_strictly_before_window():
    dates = ["2020-01-30", "2020-01-31", "2020-02-03"]
    assert find_entry_date(dates, "2020-02-01") == "2020-01-31"


def test_find_entry_date_returns_none_when_nothing_precedes_window():
    dates = ["2020-02-05", "2020-02-06"]
    assert find_entry_date(dates, "2020-02-01") is None


def test_find_trough_returns_minimum_close_in_window():
    series = _series([("2020-02-01", 100), ("2020-02-15", 70), ("2020-02-20", 85), ("2020-03-01", 60)])
    trough_date, trough_close = find_trough(series, "2020-02-01", "2020-02-28")
    # 2020-03-01's 60 close is OUTSIDE the window -- 02-15's 70 is the window's own min.
    assert trough_date == "2020-02-15"
    assert trough_close == 70


def test_run_scenario_width_is_the_assumed_narrowest_increment():
    # spot 1000 -> zone center 3% OTM -> short strike round(970), long =
    # short - $1 (the assumed carried-over increment) -> width == $1, not
    # the old 5%/8%-OTM design's ~$30 width.
    series = _series([("2020-01-31", 1000), ("2020-02-03", 950), ("2020-02-15", 990)])
    window = {"label": "test", "start": "2020-02-01", "end": "2020-02-28"}
    r = run_scenario(series, window)
    assert r["short_strike"] == 970
    assert r["long_strike"] == 970 - ASSUMED_NARROWEST_INCREMENT_DOLLARS
    assert r["width"] == ASSUMED_NARROWEST_INCREMENT_DOLLARS


def test_run_scenario_breach_capped_at_structural_width():
    # trough crashes far below both strikes -> breach must cap at the
    # (now much narrower, $1) structural width, not the raw shortfall.
    series = _series([("2020-01-31", 1000), ("2020-02-03", 950), ("2020-02-15", 400)])
    window = {"label": "test", "start": "2020-02-01", "end": "2020-02-28"}
    r = run_scenario(series, window)
    assert r["short_strike"] - r["long_strike"] == r["width"]
    assert r["capped_loss_per_contract_dollars"] == r["width"] * 100
    assert r["loss_pct_of_max"] == 100.0


def test_run_scenario_sizing_uses_structural_width_and_2pct_defined_risk_override():
    series = _series([("2020-01-31", 1000), ("2020-02-03", 950), ("2020-02-15", 990)])
    window = {"label": "test", "start": "2020-02-01", "end": "2020-02-28"}
    r = run_scenario(series, window)
    expected_structural_max_loss = r["width"] * 100
    risk_amount = PAPER_VALIDATION_CAPITAL * (PCS_RISK_PER_TRADE_PCT / 100)
    assert r["contracts"] == int(risk_amount // expected_structural_max_loss)


def test_run_scenario_reports_error_when_no_prior_data():
    series = _series([("2020-02-05", 1000), ("2020-02-06", 995)])
    window = {"label": "test", "start": "2020-02-01", "end": "2020-02-28"}
    r = run_scenario(series, window)
    assert "error" in r
