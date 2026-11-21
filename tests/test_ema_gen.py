#!/usr/bin/env python

"""Tests for the schedule generator (ema_gen)."""

import io
import random
import subprocess
import sys
from datetime import datetime, timedelta
from itertools import pairwise

import pandas as pd
import pytest

from ema_scheduler_redcap import ema_gen as g


@pytest.fixture(autouse=True)
def _seed_random():
    """Same random schedules on every run, for every test."""
    random.seed(0)


def test_offsets_respect_window_and_gap():
    # Many seeds in one test on purpose: the gap rule is strict (more than gap_min), and a
    # tie of exactly gap_min is rare, so a handful of seeds would never reach it.
    for seed in range(200):
        random.seed(seed)
        o = g.random_minute_offsets(4, 720, 60)
        assert len(o) == 4 and o == sorted(o) and 0 <= o[0] and o[-1] < 720, (
            f"seed {seed}: {o}"
        )
        assert min(b - a for a, b in pairwise(o)) > 60, (
            f"seed {seed}: {o}"
        )  # strictly more than gap_min


def test_one_sample_per_day_is_fine():
    (o,) = g.random_minute_offsets(1, 720, 60)
    assert 0 <= o < 720


def test_impossible_settings_raise_with_the_settings_in_the_message():
    with pytest.raises(ValueError, match="samples=4, window=100 min, gap=60 min"):
        g.random_minute_offsets(4, 100, 60, max_iters=50)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("08:00", timedelta(hours=8)),
        ("15:30", timedelta(hours=15, minutes=30)),
        ("3:00 pm", timedelta(hours=15)),
        ("3:00PM", timedelta(hours=15)),
        ("12:00 AM", timedelta(0)),
    ],
)
def test_time_string_formats(text, expected):
    assert g.time_str_to_delta(text) == expected


def test_unreadable_time_string_raises():
    with pytest.raises(ValueError, match="does not match"):
        g.time_str_to_delta("8 o'clock")


def test_generate_schedule_shape_days_and_start():
    start = datetime(2026, 11, 2)
    sched = g.generate_schedule(start, timedelta(hours=8), 3, 4, 720, 60)
    assert len(sched) == 12
    assert [d for _, d in sched] == [1] * 4 + [2] * 4 + [3] * 4  # day numbers
    for t, day in sched:
        day_start = start + timedelta(days=day - 1, hours=8)
        assert day_start <= t < day_start + timedelta(minutes=720)
    times = [t for t, _ in sched]
    assert times == sorted(times)


def test_command_line_prints_csv(tmp_path):
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "ema_scheduler_redcap.ema_gen",
            "--seed=1",
            "--start-date=2026-11-02",
            "--event-name=int_ema_arm_1",
            "--rec-field=webscreen_id",
            "101",
            "ema_deliver_at",
            "ema_day_num",
            "08:00",
            "2",
            "4",
            "720",
            "60",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    df = pd.read_csv(io.StringIO(r.stdout), dtype=str)
    assert len(df) == 8
    assert list(df.columns) == [
        "webscreen_id",
        "redcap_event_name",
        "redcap_repeat_instrument",
        "redcap_repeat_instance",
        "ema_deliver_at",
        "ema_day_num",
    ]
    assert list(df["ema_day_num"]) == ["1"] * 4 + ["2"] * 4


def test_import_does_not_configure_logging_or_need_docopt_at_import(tmp_path):
    code = "import logging, ema_scheduler_redcap.ema_gen; assert not logging.getLogger().handlers"
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
