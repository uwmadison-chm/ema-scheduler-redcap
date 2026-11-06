#!/usr/env/bin python

"""
These tests use their own config, tests/test_config.yaml, not the project's real
ema_config.yaml, so editing the real config cannot break them. Column names, event
names and settings are all read from that file. The last test loads the real config
and only checks that it has everything the code needs.
"""

import copy
import os
import random
import tempfile
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
import yaml

from ema_scheduler_redcap import ema_populate_redcap as p

HERE = os.path.dirname(os.path.abspath(__file__))
REAL_CONFIG = os.path.join(HERE, "../config/ema_config.yaml")
TEST_CONFIG_FILE = os.path.join(HERE, "../config/test_config.yaml")
TODAY = date(2026, 11, 2)

with open(TEST_CONFIG_FILE) as f:
    TEST_CONFIG = yaml.safe_load(f)

# ---- everything below comes from test_config.yaml, so renaming a column there is enough
DEFAULTS = TEST_CONFIG["defaults"]
ID = TEST_CONFIG["id_field"]
SAMPLE_TIME, DAY_NUM = TEST_CONFIG["sample_time_field"], DEFAULTS["day_field"]
TZ_FIELD, STATE_FIELD, START_TIME = (
    TEST_CONFIG["timezone_field"],
    TEST_CONFIG["state_field"],
    DEFAULTS["start_time_field"],
)
INT, POST = list(TEST_CONFIG["events"])
INT_DATE, POST_DATE = (
    TEST_CONFIG["events"][e]["start_date_field"] for e in (INT, POST)
)
INT_DAYS, POST_DAYS = (TEST_CONFIG["events"][e]["days"] for e in (INT, POST))
SAMPLES, WINDOW = DEFAULTS["samples_per_day"], DEFAULTS["sampling_min"]
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


def scr(rows):
    base = {c: "" for c in COLS}
    return pd.DataFrame([{**base, **OK, **r} for r in rows], columns=COLS)


def write_config(d):
    """Write the test config into folder d, adding per-event EMA file names and output paths."""
    cfg = copy.deepcopy(TEST_CONFIG)
    for name, ev in cfg["events"].items():
        ev["ema_csv"] = f"ema_{name}.csv"  # a bare name: found next to scr.csv
        ev["output_csv"] = os.path.join(d, "out", f"import_{name}_{{timestamp}}.csv")
    path = os.path.join(d, "cfg.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(cfg, f)
    return path


def run(scr_df, ema=None, first_run=False, today=TODAY):
    """ema: {event_name: csv text}; events not listed get no EMA file. Returns {event_name: import DataFrame}."""
    with tempfile.TemporaryDirectory() as d:
        cfg_path, s = write_config(d), os.path.join(d, "scr.csv")
        for name, text in (ema or {}).items():
            with open(os.path.join(d, f"ema_{name}.csv"), "w") as f:
                f.write(text)
        scr_df.to_csv(s, index=False)
        written = p.main(s, cfg_path, first_run=first_run, today=today)
        return {
            name: pd.read_csv(path, dtype=str, na_filter=False)
            for name, path in written.items()
        }


def first_time(df, today=TODAY, seed=7):
    random.seed(seed)
    out = run(df, first_run=True, today=today)[INT]
    return pd.to_datetime(out[SAMPLE_TIME]).min()


def test_schedules_only_people_inside_the_window():
    random.seed(1)
    df = scr(
        [
            {ID: "1", INT_DATE: "2026-11-01"},  # start 11-02 (today): in window
            {ID: "2", INT_DATE: "2026-11-04"},  # start 11-05: 3 days away, ok
            {ID: "3", INT_DATE: "2026-11-05"},  # start 11-06: 4 days away, too early
            {ID: "4", INT_DATE: "2026-10-31"},  # start 11-01: already passed
            {ID: "5", INT_DATE: ""},  # no start date
            {ID: "6", INT_DATE: "not a date"},  # bad data, skipped not fatal
            {ID: "7", INT_DATE: "2026-11-01 14:30", **FAILS_FILTER},  # filtered out
        ]
    )
    outs = run(df, first_run=True)
    assert list(outs) == [
        INT
    ]  # one file per event, only for events with something to schedule
    out = outs[INT]
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
    first_start = datetime(
        2026, 11, 2, 8
    )  # start date + offset, at the 08:00 start time
    last_day_start = first_start + timedelta(days=INT_DAYS - 1)
    assert one[SAMPLE_TIME].min() >= first_start.strftime("%Y-%m-%d %H:%M:%S")
    assert one[SAMPLE_TIME].max() < (
        last_day_start + timedelta(minutes=WINDOW)
    ).strftime("%Y-%m-%d %H:%M:%S")


def test_offset_zero_events_and_per_event_scheduling():
    random.seed(2)
    df = scr([{ID: "1", POST_DATE: "2026-11-02", INT_DATE: "2026-11-01"}])
    ema = {
        INT: EMA_HEADER + f"1,{INT},,\n",  # any row for the event counts
        POST: EMA_HEADER,
    }
    outs = run(df, ema)  # already has int; should get only post (offset 0)
    assert list(outs) == [POST] and len(outs[POST]) == POST_DAYS * SAMPLES
    assert outs[POST][SAMPLE_TIME].min() >= "2026-11-02 08:00:00"


def test_eastern_is_one_hour_earlier_than_central_in_redcap_time():
    row = {ID: "1", INT_DATE: "2026-11-01"}
    central, eastern = (
        first_time(scr([row])),
        first_time(scr([{**row, TZ_FIELD: EASTERN}])),
    )
    assert central - eastern == pd.Timedelta(hours=1)  # Eastern 8am is Central 7am


def test_state_without_dst_does_not_follow_its_zone_in_summer():
    row = {ID: "1", INT_DATE: "2026-06-30", TZ_FIELD: str(OVERRIDE["zone_code"])}
    summer = date(2026, 7, 1)
    with_dst = first_time(scr([{**row, STATE_FIELD: "CO"}]), summer)
    without_dst = first_time(scr([{**row, STATE_FIELD: OVERRIDE["state"]}]), summer)
    assert without_dst - with_dst == pd.Timedelta(
        hours=1
    )  # in summer Phoenix is an hour behind Denver
    winter = {**row, INT_DATE: "2026-11-01"}
    assert first_time(scr([{**winter, STATE_FIELD: OVERRIDE["state"]}])) == first_time(
        scr([{**winter, STATE_FIELD: "CO"}])
    )


def test_blank_or_unknown_time_zone_is_skipped():
    rows = [
        {ID: str(i), INT_DATE: "2026-11-01", TZ_FIELD: z}
        for i, z in enumerate(("", "999"), 1)
    ]
    rows.append({ID: "3", INT_DATE: "2026-11-01"})
    out = run(scr(rows), first_run=True)[INT]
    assert set(out[ID]) == {"3"}


def test_nothing_to_schedule_writes_no_file():
    assert run(scr([{ID: "1"}]), first_run=True) == {}


def test_missing_ema_file_raises_without_first_run():
    with pytest.raises(FileNotFoundError):
        run(scr([{ID: "1"}]))


def test_ema_file_holding_another_event_raises():
    ema = {
        INT: EMA_HEADER,
        POST: EMA_HEADER + f"1,{INT},,1\n",
    }  # wrong file for the post event
    with pytest.raises(ValueError, match=f"must only hold {POST}"):
        run(scr([{ID: "1"}]), ema)


def test_load_config_merges_defaults_into_each_event():
    with tempfile.TemporaryDirectory() as d:
        cfg = p.load_config(write_config(d))
    assert list(cfg["events"]) == [INT, POST]
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


def test_participant_zone_uses_state_override():
    with tempfile.TemporaryDirectory() as d:
        cfg = p.load_config(write_config(d))
    row = lambda code, state: {TZ_FIELD: code, STATE_FIELD: state}
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
    local = lambda y, m, d, hh: datetime(y, m, d, hh)
    assert p.to_central(
        local(2026, 11, 3, 8), "America/New_York", "America/Chicago"
    ) == local(2026, 11, 3, 7)
    assert p.to_central(
        local(2026, 7, 1, 8), "America/Phoenix", "America/Chicago"
    ) == local(2026, 7, 1, 10)
    assert p.to_central(
        local(2026, 11, 3, 8), "America/Phoenix", "America/Chicago"
    ) == local(2026, 11, 3, 9)


def test_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as d:
        cfg_path, s_path = write_config(d), os.path.join(d, "scr.csv")
        scr([{ID: "1", INT_DATE: "2026-11-01"}]).to_csv(s_path, index=False)
        assert p.main(s_path, cfg_path, first_run=True, dry_run=True, today=TODAY) == {}
        assert not os.path.exists(os.path.join(d, "out"))


def test_real_config_has_everything_the_code_needs():
    """Checks only that the project's real config loads and is complete; not what its values are."""
    if not os.path.exists(REAL_CONFIG):
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


if __name__ == "__main__":
    tests = [
        (n, f)
        for n, f in sorted(globals().items())
        if n.startswith("test_") and callable(f)
    ]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} passed")
