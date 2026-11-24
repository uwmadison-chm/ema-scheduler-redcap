#!/usr/bin/env python

"""
These tests use their own config, tests/test_config.yaml, not the project's real
ema_config.yaml, so editing the real config cannot break them. Column names, event
names and settings are all read from that file. The last test loads the real config
and only checks that it has everything the code needs.
"""

import copy
import logging
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
import yaml

from ema_scheduler_redcap import ema_populate_redcap as p

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
REAL_CONFIG = CONFIG_DIR / "ema_config.yaml"
TEST_CONFIG_FILE = CONFIG_DIR / "test_config.yaml"
TODAY = date(
    2026, 11, 17
)  # the 'current' date passed to the code; every test date below is relative to it

TEST_CONFIG = yaml.safe_load(TEST_CONFIG_FILE.read_text())

# ---- everything below comes from test_config.yaml, so renaming a column there is enough
DEFAULTS = TEST_CONFIG["defaults"]
ID = TEST_CONFIG["id_field"]
SAMPLE_TIME, DAY_NUM = TEST_CONFIG["sample_time_field"], DEFAULTS["day_field"]
TZ_FIELD, STATE_FIELD, START_TIME = (
    TEST_CONFIG["timezone_field"],
    TEST_CONFIG["state_field"],
    DEFAULTS["start_time_field"],
)
EVENTS = list(
    TEST_CONFIG["events"]
)  # every event in the test config; the tests below use these two
INT, POST = "int_ema_arm_1", "post_ema_arm_1"
assert {INT, POST} <= set(EVENTS), f"test_config.yaml needs events {INT} and {POST}"
INT_DATE, POST_DATE = (
    TEST_CONFIG["events"][e]["start_date_field"] for e in (INT, POST)
)
INT_DAYS, POST_DAYS = (TEST_CONFIG["events"][e]["days"] for e in (INT, POST))
SAMPLES, WINDOW = DEFAULTS["samples_per_day"], DEFAULTS["sampling_min"]
MAX_BEFORE, MAX_AFTER = (
    DEFAULTS["max_days_before_start"],
    DEFAULTS["max_days_after_start"],
)
INT_OFFSET = TEST_CONFIG["events"][INT].get(
    "start_offset_days", DEFAULTS["start_offset_days"]
)
POST_OFFSET = TEST_CONFIG["events"][POST].get(
    "start_offset_days", DEFAULTS["start_offset_days"]
)
STANDARD = [
    "redcap_event_name",
    "redcap_repeat_instrument",
    "redcap_repeat_instance",
]  # fixed by REDCap
OVERRIDE = TEST_CONFIG["no_dst_overrides"][0]  # e.g. Mountain + AZ


def code_for(zone):
    return str(
        next(code for code, iana in TEST_CONFIG["timezones"].items() if iana == zone)
    )


CENTRAL, EASTERN, MOUNTAIN = (
    code_for(TEST_CONFIG["central_tz"]),
    code_for("America/New_York"),
    code_for("America/Denver"),
)
EMA_HEADER = ",".join([ID, *STANDARD]) + "\n"
OUT_COLS = [ID, *STANDARD, SAMPLE_TIME, DAY_NUM]


def _unique(items):
    return list(dict.fromkeys(items))


# screening columns the code reads: id, every filter field, each event's start date, start time, time zone, state
COLS = _unique(
    [
        ID,
        *(r["field"] for r in DEFAULTS["filters"]),
        *(e["start_date_field"] for e in TEST_CONFIG["events"].values()),
        START_TIME,
        TZ_FIELD,
        STATE_FIELD,
    ]
)

# a participant who passes every default filter (values taken from the filters)
OK = {
    r["field"]: str(r["value"]) if r["op"] == "equals" else "x"
    for r in DEFAULTS["filters"]
}
OK.update(
    {START_TIME: "08:00", TZ_FIELD: CENTRAL, STATE_FIELD: "WI"}
)  # a readable time; Central; a non-override state

# a change that makes someone fail one filter (not the screening-event filter)
_f = next(
    r
    for r in DEFAULTS["filters"]
    if r["op"] == "equals" and r["field"] != "redcap_event_name"
)
FAILS_FILTER = {_f["field"]: str(_f["value"]) + "_not"}


@pytest.fixture(autouse=True)
def _seed_random():
    """Same random schedules on every run, for every test."""
    random.seed(0)


def int_on(days):
    """The start-date value (rand_date) that makes the int event start `days` from TODAY."""
    return (TODAY + timedelta(days=days - INT_OFFSET)).isoformat()


def post_on(days):
    """The start-date value that makes the post event start `days` from TODAY."""
    return (TODAY + timedelta(days=days - POST_OFFSET)).isoformat()


def scr(rows):
    base = {c: "" for c in COLS}
    return pd.DataFrame([{**base, **OK, **r} for r in rows], columns=COLS)


def write_config(d):
    """Write the test config into folder d, adding per-event EMA file names."""
    cfg = copy.deepcopy(TEST_CONFIG)
    for name, ev in cfg["events"].items():
        ev["ema_csv"] = f"ema_{name}.csv"  # a bare name: found next to scr.csv
    path = d / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


@pytest.fixture
def run(tmp_path_factory):
    """run(scr_df, ema=None, today=TODAY) -> {event_name: import DataFrame}.

    ema: {event_name: csv text}; events not listed get no EMA file.
    Every call gets its own fresh folder, so a test can call it more than once.
    """

    def _run(scr_df, ema=None, today=TODAY):
        d = tmp_path_factory.mktemp("run")
        cfg_path, s = write_config(d), d / "scr.csv"
        for name, text in (ema or {}).items():
            (d / f"ema_{name}.csv").write_text(text)
        scr_df.to_csv(s, index=False)
        out = d / "out"
        out.mkdir()
        written = p.main(s, cfg_path, out, today=today)
        return {
            name: pd.read_csv(path, dtype=str, na_filter=False)
            for name, path in written.items()
        }

    return _run


@pytest.fixture
def first_time(run):
    """first_time(df, today=TODAY, seed=7) -> earliest sample time written for the int event."""

    def _first_time(df, today=TODAY, seed=7):
        random.seed(seed)
        return pd.to_datetime(run(df, today=today)[INT][SAMPLE_TIME]).min()

    return _first_time


@pytest.mark.parametrize(
    ("row", "scheduled"),
    [
        pytest.param({INT_DATE: int_on(0)}, True, id="starts-today"),
        pytest.param({INT_DATE: int_on(MAX_BEFORE)}, True, id="furthest-allowed-day"),
        pytest.param({INT_DATE: int_on(MAX_BEFORE + 1)}, False, id="one-day-too-early"),
        pytest.param({INT_DATE: int_on(-MAX_AFTER - 1)}, False, id="one-day-too-late"),
        pytest.param({INT_DATE: ""}, False, id="no-start-date"),
        pytest.param({INT_DATE: "not a date"}, False, id="unreadable-start-date"),
        pytest.param(
            {INT_DATE: int_on(0) + " 14:30", **FAILS_FILTER}, False, id="fails-a-filter"
        ),
    ],
)
def test_who_is_scheduled(run, row, scheduled):
    outs = run(scr([{ID: "1", **row}]))
    assert list(outs) == (
        [INT] if scheduled else []
    )  # one file per event, only if something was scheduled


def test_schedule_content(run):
    df = scr([{ID: "1", INT_DATE: int_on(0)}, {ID: "2", INT_DATE: int_on(MAX_BEFORE)}])
    out = run(df)[INT]
    assert sorted(set(out[ID])) == ["1", "2"]
    assert set(out["redcap_event_name"]) == {INT}
    assert len(out) == 2 * INT_DAYS * SAMPLES
    assert list(out.columns) == OUT_COLS
    assert (
        out["redcap_repeat_instrument"] == ""
    ).all()  # repeating events: no instrument name
    one = out[out[ID] == "1"]
    assert set(one[DAY_NUM]) == {str(i) for i in range(1, INT_DAYS + 1)}
    assert list(one["redcap_repeat_instance"][:3]) == ["1", "2", "3"]
    first_start = datetime.combine(TODAY, datetime.min.time()) + timedelta(
        hours=8
    )  # start day, at the 08:00 start time
    last_day_start = first_start + timedelta(days=INT_DAYS - 1)
    assert one[SAMPLE_TIME].min() >= first_start.strftime("%Y-%m-%d %H:%M:%S")
    assert one[SAMPLE_TIME].max() < (
        last_day_start + timedelta(minutes=WINDOW)
    ).strftime("%Y-%m-%d %H:%M:%S")


def test_offset_zero_events_and_per_event_scheduling(run):
    df = scr([{ID: "1", POST_DATE: post_on(0), INT_DATE: int_on(0)}])
    ema = {
        INT: EMA_HEADER + f"1,{INT},,\n",  # any row for the event counts
        POST: EMA_HEADER,
    }
    outs = run(df, ema)  # already has int; should get only post (offset 0)
    assert list(outs) == [POST] and len(outs[POST]) == POST_DAYS * SAMPLES
    assert outs[POST][SAMPLE_TIME].min() >= f"{TODAY} 08:00:00"


def test_eastern_is_one_hour_earlier_than_central_in_redcap_time(first_time):
    row = {ID: "1", INT_DATE: int_on(0)}
    central, eastern = (
        first_time(scr([row])),
        first_time(scr([{**row, TZ_FIELD: EASTERN}])),
    )
    assert central - eastern == pd.Timedelta(hours=1)  # Eastern 8am is Central 7am


def test_state_without_dst_does_not_follow_its_zone_in_summer(first_time):
    summer = date(
        2026, 7, 1
    )  # a summer day, so Denver is on daylight time and Phoenix is not
    row = {
        ID: "1",
        INT_DATE: (summer - timedelta(days=INT_OFFSET)).isoformat(),
        TZ_FIELD: str(OVERRIDE["zone_code"]),
    }
    with_dst = first_time(scr([{**row, STATE_FIELD: "CO"}]), summer)
    without_dst = first_time(scr([{**row, STATE_FIELD: OVERRIDE["state"]}]), summer)
    assert without_dst - with_dst == pd.Timedelta(
        hours=1
    )  # in summer Phoenix is an hour behind Denver
    winter = {**row, INT_DATE: int_on(0)}  # TODAY must be a winter date for this check
    assert first_time(scr([{**winter, STATE_FIELD: OVERRIDE["state"]}])) == first_time(
        scr([{**winter, STATE_FIELD: "CO"}])
    )


@pytest.mark.parametrize("zone", ["", "999"], ids=["blank", "unknown"])
def test_blank_or_unknown_time_zone_is_skipped(run, zone):
    rows = [
        {ID: "1", INT_DATE: int_on(0), TZ_FIELD: zone},
        {ID: "2", INT_DATE: int_on(0)},
    ]
    out = run(scr(rows))[INT]
    assert set(out[ID]) == {"2"}


def test_nothing_to_schedule_writes_no_file(run):
    assert run(scr([{ID: "1"}])) == {}


def test_missing_ema_file_warns_and_counts_as_nobody_scheduled(run, caplog):
    caplog.set_level(logging.WARNING)
    df = scr([{ID: "1", POST_DATE: post_on(0), INT_DATE: int_on(0)}])
    ema = {
        name: EMA_HEADER for name in EVENTS if name != POST
    }  # every event has a file except post
    ema[INT] = EMA_HEADER + f"1,{INT},,1\n"  # int is running (1 already scheduled)
    outs = run(df, ema)
    assert list(outs) == [
        POST
    ]  # post is scheduled without its file; int is read normally
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert (
        len(warnings) == 1
        and "EMA file missing or empty" in warnings[0]
        and f"ema_{POST}.csv" in warnings[0]
    )


def test_empty_ema_file_with_only_a_header_does_not_warn(run, caplog):
    caplog.set_level(logging.WARNING)
    run(scr([{ID: "1", INT_DATE: int_on(0)}]), {name: EMA_HEADER for name in EVENTS})
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_ema_file_holding_another_event_raises(run):
    ema = {
        INT: EMA_HEADER,
        POST: EMA_HEADER + f"1,{INT},,1\n",
    }  # wrong file for the post event
    with pytest.raises(ValueError, match=f"must only hold {POST}"):
        run(scr([{ID: "1"}]), ema)


def test_load_config_merges_defaults_into_each_event(tmp_path):
    cfg = p.load_config(write_config(tmp_path))
    assert {INT, POST} <= set(cfg["events"])
    intv, post = cfg["events"][INT], cfg["events"][POST]
    assert intv["start_offset_days"] == DEFAULTS["start_offset_days"]  # inherited
    assert (
        post["start_offset_days"]
        == TEST_CONFIG["events"][POST]["start_offset_days"]
        != DEFAULTS["start_offset_days"]
    )  # overridden
    assert (
        intv["days"] == INT_DAYS
        and post["days"] == POST_DAYS
        and intv["samples_per_day"] == SAMPLES
    )
    assert intv["redcap_event_name"] == INT
    assert all(
        isinstance(r.get("value", ""), str) for r in intv["input_filters"]
    )  # values compared as text
    assert len(intv["input_filters"]) == len(DEFAULTS["filters"])
    assert cfg["timezones"][EASTERN] == "America/New_York"
    assert (
        cfg["overrides"][(str(OVERRIDE["zone_code"]), OVERRIDE["state"])]
        == OVERRIDE["iana"]
    )


def test_participant_zone_uses_state_override(tmp_path):
    cfg = p.load_config(write_config(tmp_path))

    def row(code, state):
        return {TZ_FIELD: code, STATE_FIELD: state}

    assert p.participant_zone(row(MOUNTAIN, "CO"), cfg) == "America/Denver"
    assert (
        p.participant_zone(row(MOUNTAIN, OVERRIDE["state"].lower()), cfg)
        == OVERRIDE["iana"]
    )
    assert p.participant_zone(row(EASTERN, ""), cfg) == "America/New_York"
    assert (
        p.participant_zone(row("", "WI"), cfg) is None
        and p.participant_zone(row("999", "WI"), cfg) is None
    )


def test_to_central_in_winter_and_summer():
    def local(y, m, d, hh):
        return datetime(y, m, d, hh)

    assert p.to_central(
        local(2026, 11, 3, 8), "America/New_York", "America/Chicago"
    ) == local(2026, 11, 3, 7)
    assert p.to_central(
        local(2026, 7, 1, 8), "America/Phoenix", "America/Chicago"
    ) == local(2026, 7, 1, 10)
    assert p.to_central(
        local(2026, 11, 3, 8), "America/Phoenix", "America/Chicago"
    ) == local(2026, 11, 3, 9)


def test_dry_run_writes_nothing(tmp_path):
    cfg_path, s_path, out = (
        write_config(tmp_path),
        tmp_path / "scr.csv",
        tmp_path / "out",
    )
    scr([{ID: "1", INT_DATE: int_on(0)}]).to_csv(s_path, index=False)
    assert p.main(s_path, cfg_path, out, dry_run=True, today=TODAY) == {}
    assert not out.exists()


def test_missing_ema_file_is_saved_as_a_template_with_only_the_column_names(tmp_path):
    cfg_path, s_path, out = (
        write_config(tmp_path),
        tmp_path / "scr.csv",
        tmp_path / "out",
    )
    out.mkdir()
    scr([{ID: "1", INT_DATE: int_on(0)}]).to_csv(s_path, index=False)
    p.main(s_path, cfg_path, out, today=TODAY)
    expected = [
        ID,
        "redcap_event_name",
        "redcap_repeat_instrument",
        "redcap_repeat_instance",
        SAMPLE_TIME,
        TEST_CONFIG["defaults"]["day_field"],
    ]
    for name in EVENTS:
        text = (
            tmp_path / f"ema_{name}.csv"
        ).read_text()  # saved next to the screening file
        assert text == ",".join(expected) + "\n"


def test_existing_ema_file_is_never_replaced_by_the_template(tmp_path):
    cfg_path, s_path, out = (
        write_config(tmp_path),
        tmp_path / "scr.csv",
        tmp_path / "out",
    )
    out.mkdir()
    ema = tmp_path / f"ema_{INT}.csv"
    text = EMA_HEADER + f"1,{INT},,1\n"
    ema.write_text(text)
    scr([{ID: "2", INT_DATE: int_on(0)}]).to_csv(s_path, index=False)
    p.main(s_path, cfg_path, out, today=TODAY)
    assert ema.read_text() == text


def test_dry_run_saves_no_template(tmp_path):
    cfg_path, s_path = write_config(tmp_path), tmp_path / "scr.csv"
    scr([{ID: "1", INT_DATE: int_on(0)}]).to_csv(s_path, index=False)
    p.main(s_path, cfg_path, tmp_path / "out", dry_run=True, today=TODAY)
    assert not [f for f in tmp_path.iterdir() if f.name.startswith("ema_")]


def test_missing_output_folder_raises(tmp_path):
    cfg_path, s_path = write_config(tmp_path), tmp_path / "scr.csv"
    scr([{ID: "1", INT_DATE: int_on(0)}]).to_csv(s_path, index=False)
    with pytest.raises(NotADirectoryError):
        p.main(s_path, cfg_path, tmp_path / "nope", today=TODAY)


def test_real_config_has_everything_the_code_needs():
    """Checks only that the project's real config loads and is complete; not what its values are."""
    if not REAL_CONFIG.exists():
        pytest.skip(f"no real config at {REAL_CONFIG}")
    cfg = p.load_config(REAL_CONFIG)  # raises KeyError naming a missing top-level key
    assert cfg["events"], "no events in the config"
    needed = {
        "redcap_event_name",
        "start_date_field",
        "start_time_field",
        "start_offset_days",
        "days",
        "max_days_before_start",
        "max_days_after_start",
        "samples_per_day",
        "sampling_min",
        "gap_min",
        "max_iters",
        "day_field",
        "ema_csv",
        "output_csv",
        "input_filters",
    }
    for name, ev in cfg["events"].items():
        assert not needed - set(ev), f"{name} is missing {sorted(needed - set(ev))}"
