#!/usr/env/bin python

import io
import random
import subprocess
import sys
from datetime import datetime, timedelta
from itertools import pairwise

import pandas as pd

from ema_scheduler_redcap import ema_gen as g


def _raises(exc, fragment, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except exc as e:
        assert fragment in str(e), f"wrong message: {e}"
        return
    raise AssertionError(f"expected {exc.__name__}")


def test_offsets_respect_window_and_gap():
    for seed in range(200):
        random.seed(seed)
        o = g.random_minute_offsets(4, 720, 60)
        assert len(o) == 4 and o == sorted(o) and 0 <= o[0] and o[-1] < 720
        assert min(b - a for a, b in pairwise(o)) > 60  # strictly more than gap_min


def test_one_sample_per_day_is_fine():
    random.seed(1)
    (o,) = g.random_minute_offsets(1, 720, 60)
    assert 0 <= o < 720


def test_impossible_settings_raise_with_the_settings_in_the_message():
    _raises(
        ValueError,
        "samples=4, window=100 min, gap=60 min",
        g.random_minute_offsets,
        4,
        100,
        60,
        max_iters=50,
    )


def test_time_string_formats():
    h = lambda s: g.time_str_to_delta(s)
    assert h("08:00") == timedelta(hours=8)
    assert h("15:30") == timedelta(hours=15, minutes=30)
    assert h("3:00 pm") == h("3:00PM") == timedelta(hours=15)
    assert h("12:00 AM") == timedelta(0)
    _raises(ValueError, "does not match", h, "8 o'clock")


def test_generate_schedule_shape_days_and_start():
    random.seed(3)
    start = datetime(2026, 11, 2)
    sched = g.generate_schedule(start, timedelta(hours=8), 3, 4, 720, 60)
    assert len(sched) == 12
    assert [d for _, d in sched] == [1] * 4 + [2] * 4 + [3] * 4  # day numbers
    for t, day in sched:
        day_start = start + timedelta(days=day - 1, hours=8)
        assert day_start <= t < day_start + timedelta(minutes=720)
    times = [t for t, _ in sched]
    assert times == sorted(times)


def test_command_line_prints_csv():
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


def test_import_does_not_configure_logging_or_need_docopt_at_import():
    code = "import logging, ema_scheduler_redcap.ema_gen; assert not logging.getLogger().handlers"
    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert r.returncode == 0, r.stderr


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
