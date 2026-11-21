#!/usr/bin/env python

"""Tests for choosing who is due a schedule (ema_select)."""

import re

import pandas as pd
import pytest

from ema_scheduler_redcap import ema_select as s

COLS = [
    "webscreen_id",
    "redcap_event_name",
    "trk_enrollment_status",
    "trk_withdrawal",
    "trk_ema_start_time",
    "rand_date",
]
EMA_COLS = [
    "webscreen_id",
    "redcap_event_name",
    "redcap_repeat_instrument",
    "redcap_repeat_instance",
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


@pytest.fixture
def scr_df():
    """Screening rows, one for each way of passing or failing the filters."""
    return _scr(
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
            _ok(
                webscreen_id="106", rand_date="2026-11-03"
            ),  # passes, already scheduled
            _ok(
                webscreen_id="107",
                rand_date="2026-11-02",
                redcap_event_name="base_ema_arm_1",
            ),  # not a screening row
            _ok(webscreen_id="108", rand_date="   "),  # whitespace only = blank
            _ok(webscreen_id="109", rand_date="2026-11-04"),  # passes
        ]
    )


@pytest.fixture
def ema_df():
    """Existing EMA rows, to test who counts as already scheduled."""
    return pd.DataFrame(
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
        columns=EMA_COLS,
    )


def test_apply_filters_all_ops():
    df = pd.DataFrame({"a": ["x", "y", "", None, "  "]})

    def ids(rules):
        return list(s.apply_filters(df, rules).index)

    assert ids([{"field": "a", "op": "equals", "value": "x"}]) == [0]
    assert ids([{"field": "a", "op": "not_equals", "value": "x"}]) == [1, 2, 3, 4]
    assert ids([{"field": "a", "op": "blank"}]) == [2, 3, 4]  # "", None and whitespace
    assert ids([{"field": "a", "op": "not_blank"}]) == [0, 1]


def test_all_rules_must_match(scr_df):
    got = s.apply_filters(scr_df, INPUT_FILTERS)
    assert list(got["webscreen_id"]) == ["101", "106", "109"]


def test_unknown_op_raises(scr_df):
    with pytest.raises(ValueError, match="Unknown filter op"):
        s.apply_filters(scr_df, [{"field": "rand_date", "op": "like"}])


def test_missing_filter_column_raises(scr_df):
    with pytest.raises(KeyError, match=re.escape("['no_such_field']")):
        s.apply_filters(scr_df, [{"field": "no_such_field", "op": "not_blank"}])


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("int_ema_arm_1", {"106", "110"}),
        ("base_ema_arm_1", {"109"}),
        ("pw30_ema_arm_1", set()),
    ],
)
def test_already_scheduled_is_per_event_and_any_row_counts(ema_df, event, expected):
    assert s.already_scheduled_ids(ema_df, event, "webscreen_id") == expected


def test_select_for_event(scr_df, ema_df):
    done = s.already_scheduled_ids(ema_df, "int_ema_arm_1", "webscreen_id")
    todo, counts = s.select_for_event(scr_df, INT, done, "webscreen_id")
    assert list(todo["webscreen_id"]) == [
        "101",
        "109",
    ]  # 109 is scheduled for base only
    assert counts == {"passed_filters": 3, "already_scheduled": 1, "to_schedule": 2}


def test_nobody_scheduled_yet(scr_df):
    todo, counts = s.select_for_event(scr_df, INT, set(), "webscreen_id")
    assert list(todo["webscreen_id"]) == ["101", "106", "109"]
    assert counts["already_scheduled"] == 0


def test_duplicate_row_for_a_participant_raises(scr_df):
    dup = pd.concat([scr_df, scr_df.iloc[[0]]], ignore_index=True)
    with pytest.raises(
        ValueError, match=re.escape("more than one row passed the filters for: ['101']")
    ):
        s.select_for_event(dup, INT, set(), "webscreen_id")


def test_blank_id_raises():
    bad = _scr([_ok(webscreen_id="", rand_date="2026-11-02")])
    with pytest.raises(ValueError, match="blank webscreen_id"):
        s.select_for_event(bad, INT, set(), "webscreen_id")


def test_column_gate_names_what_is_missing_in_the_screening_file(scr_df):
    s.check_columns(scr_df, set(COLS), "scr")  # all present: no error
    with pytest.raises(KeyError, match=re.escape("['trk_withdrawal']")):
        s.check_columns(scr_df.drop(columns="trk_withdrawal"), set(COLS), "scr")


def test_column_gate_names_what_is_missing_in_the_ema_file(ema_df):
    with pytest.raises(KeyError, match=re.escape("['redcap_event_name']")):
        s.already_scheduled_ids(
            ema_df.drop(columns="redcap_event_name"), "int_ema_arm_1", "webscreen_id"
        )


def test_header_only_ema_file_means_nobody_scheduled(ema_df):
    empty = pd.DataFrame(columns=list(ema_df.columns))
    assert s.already_scheduled_ids(empty, "int_ema_arm_1", "webscreen_id") == set()
