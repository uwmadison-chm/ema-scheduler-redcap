#!/usr/env/bin python


import pandas as pd

from ema_scheduler_redcap import ema_select as s

COLS = [
    "webscreen_id",
    "redcap_event_name",
    "trk_enrollment_status",
    "trk_withdrawal",
    "trk_ema_start_time",
    "rand_date",
]
INPUT_FILTERS: list[dict[str, str]] = [
    {"field": "redcap_event_name", "op": "equals", "value": "scr_arm_1"},
    {"field": "trk_enrollment_status", "op": "equals", "value": "enrolled"},
    {"field": "trk_withdrawal", "op": "equals", "value": "0"},
    {"field": "trk_ema_start_time", "op": "not_blank"},
    {"field": "rand_date", "op": "not_blank"},
]
INT = {
    "redcap_event_name": "int_ema_arm_1",
    "input_filters": INPUT_FILTERS,
}


def _scr(rows):
    base = {c: "" for c in COLS}
    return pd.DataFrame([{**base, **r} for r in rows], columns=COLS)


def _ok(**kw):
    return {
        "redcap_event_name": "scr_arm_1",
        "trk_enrollment_status": "enrolled",
        "trk_withdrawal": "0",
        "trk_ema_start_time": "08:00",
        **kw,
    }


SCR = _scr(
    [
        _ok(webscreen_id="101", rand_date="2026-11-02"),  # passes
        _ok(
            webscreen_id="102", rand_date="2026-11-02", trk_ema_start_time=""
        ),  # no start time
        _ok(
            webscreen_id="103",
            rand_date="2026-11-02",
            trk_enrollment_status="not_enrolled",
        ),
        _ok(
            webscreen_id="104", rand_date="2026-11-02", trk_withdrawal="1"
        ),  # withdrawn
        _ok(webscreen_id="105"),  # no rand_date
        _ok(webscreen_id="106", rand_date="2026-11-03"),  # passes, already scheduled
        _ok(
            webscreen_id="107",
            rand_date="2026-11-02",
            redcap_event_name="base_ema_arm_1",
        ),  # not a screening row
        _ok(webscreen_id="108", rand_date="   "),  # whitespace only = blank
        _ok(webscreen_id="109", rand_date="2026-11-04"),  # passes
    ]
)
EMA = pd.DataFrame(
    [
        ("106", "int_ema_arm_1", "int_ema_arm_1", "1"),  # scheduled for int
        (
            "109",
            "base_ema_arm_1",
            "base_ema_arm_1",
            "1",
        ),  # scheduled for a DIFFERENT event only
        (
            "110",
            "int_ema_arm_1",
            "int_ema_arm_1",
            "",
        ),  # any row for the event counts, even with no instance
    ],
    columns=[
        "webscreen_id",
        "redcap_event_name",
        "redcap_repeat_instrument",
        "redcap_repeat_instance",
    ],
)


def _expect(exc, fragment, fn, *args):
    try:
        fn(*args)
    except exc as e:
        assert fragment in str(e), f"wrong message: {e}"
        return
    raise AssertionError(f"expected {exc.__name__} containing {fragment!r}")


def test_apply_filters_all_ops():
    df = pd.DataFrame({"a": ["x", "y", "", None, "  "]})
    ids = lambda rules: list(s.apply_filters(df, rules).index)
    assert ids([{"field": "a", "op": "equals", "value": "x"}]) == [0]
    assert ids([{"field": "a", "op": "not_equals", "value": "x"}]) == [1, 2, 3, 4]
    assert ids([{"field": "a", "op": "blank"}]) == [2, 3, 4]  # "", None and whitespace
    assert ids([{"field": "a", "op": "not_blank"}]) == [0, 1]


def test_all_rules_must_match():
    got = s.apply_filters(SCR, INPUT_FILTERS)
    assert list(got["webscreen_id"]) == ["101", "106", "109"]


def test_unknown_op_and_missing_filter_column():
    _expect(
        ValueError,
        "Unknown filter op",
        s.apply_filters,
        SCR,
        [{"field": "rand_date", "op": "like"}],
    )
    _expect(
        KeyError,
        "['no_such_field']",
        s.apply_filters,
        SCR,
        [{"field": "no_such_field", "op": "not_blank"}],
    )


def test_already_scheduled_is_per_event_and_any_row_counts():
    got = lambda ev: s.already_scheduled_ids(EMA, ev, "webscreen_id")
    assert got("int_ema_arm_1") == {"106", "110"}
    assert got("base_ema_arm_1") == {"109"}
    assert got("pw30_ema_arm_1") == set()


def test_select_for_event():
    done = s.already_scheduled_ids(EMA, "int_ema_arm_1", "webscreen_id")
    todo, counts = s.select_for_event(SCR, INT, done, "webscreen_id")
    assert list(todo["webscreen_id"]) == [
        "101",
        "109",
    ]  # 109 is scheduled for base only
    assert counts == {"passed_filters": 3, "already_scheduled": 1, "to_schedule": 2}


def test_nobody_scheduled_yet():
    todo, counts = s.select_for_event(SCR, INT, set(), "webscreen_id")
    assert (
        list(todo["webscreen_id"]) == ["101", "106", "109"]
        and counts["already_scheduled"] == 0
    )


def test_duplicate_row_for_a_participant_raises():
    dup = pd.concat([SCR, SCR.iloc[[0]]], ignore_index=True)
    _expect(
        ValueError,
        "more than one row passed the filters for: ['101']",
        s.select_for_event,
        dup,
        INT,
        set(),
        "webscreen_id",
    )


def test_blank_id_raises():
    bad = _scr([_ok(webscreen_id="", rand_date="2026-11-02")])
    _expect(
        ValueError,
        "blank webscreen_id",
        s.select_for_event,
        bad,
        INT,
        set(),
        "webscreen_id",
    )


def test_column_gate_names_what_is_missing():
    s.check_columns(SCR, set(COLS), "scr")  # all present: no error
    _expect(
        KeyError,
        "['trk_withdrawal']",
        s.check_columns,
        SCR.drop(columns="trk_withdrawal"),
        set(COLS),
        "scr",
    )
    _expect(
        KeyError,
        "['redcap_event_name']",
        s.already_scheduled_ids,
        EMA.drop(columns="redcap_event_name"),
        "int_ema_arm_1",
        "webscreen_id",
    )


def test_header_only_ema_file_means_nobody_scheduled():
    empty = pd.DataFrame(columns=list(EMA.columns))
    assert s.already_scheduled_ids(empty, "int_ema_arm_1", "webscreen_id") == set()


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
