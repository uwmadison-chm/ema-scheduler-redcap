#!/usr/env/bin python

import logging
import os
import subprocess
import sys
import tempfile

import pandas as pd
from pandas.errors import EmptyDataError

from ema_scheduler_redcap import ema_helper as helper
from ema_scheduler_redcap import ema_select as sel

HERE = os.path.dirname(os.path.abspath(__file__))
EMA_COLS = [
    "webscreen_id",
    "redcap_event_name",
    "redcap_repeat_instrument",
    "redcap_repeat_instance",
]
ROWS = [
    {
        "id": "1",
        "redcap_event_name": "int_ema_arm_1",
        "redcap_repeat_instance": 1,
        "ema_deliver_at": "2026-11-02 08:15:00",
    },
    {
        "id": "1",
        "redcap_event_name": "int_ema_arm_1",
        "redcap_repeat_instance": 2,
        "ema_deliver_at": "2026-11-02 11:40:00",
    },
    {
        "id": "2",
        "redcap_event_name": "int_ema_arm_1",
        "redcap_repeat_instance": 1,
        "ema_deliver_at": "2026-11-03 09:05:00",
    },
]


def _write(d, name, text):
    path = os.path.join(d, name)
    with open(path, "w") as f:
        f.write(text)
    return path


def _raises(exc, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


class _Catch(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


# ---- reading
def test_read_keeps_text_and_blanks():
    with tempfile.TemporaryDirectory() as d:
        df = helper.read_csv_file(_write(d, "a.csv", "id,when\n007,\n008,2026-01-01\n"))
        assert list(df["id"]) == ["007", "008"]  # leading zeros survive
        assert list(df["when"]) == ["", "2026-01-01"]  # blank is "", not NaN


def test_read_header_only_is_fine():
    with tempfile.TemporaryDirectory() as d:
        df = helper.read_csv_file(_write(d, "a.csv", "id,redcap_event_name\n"))
        assert df.empty and list(df.columns) == ["id", "redcap_event_name"]


def test_read_missing_empty_and_malformed_files_raise():
    with tempfile.TemporaryDirectory() as d:
        _raises(FileNotFoundError, helper.read_csv_file, os.path.join(d, "nope.csv"))
        _raises(EmptyDataError, helper.read_csv_file, _write(d, "empty.csv", ""))
        _raises(
            pd.errors.ParserError,
            helper.read_csv_file,
            _write(d, "bad.csv", "a,b\n1,2\n1,2,3,4\n"),
        )


# ---- EMA file and --first-run
def test_ema_missing_or_empty_raises_by_default():
    with tempfile.TemporaryDirectory() as d:
        _raises(
            FileNotFoundError,
            helper.read_ema_csv,
            os.path.join(d, "nope.csv"),
            "webscreen_id",
        )
        _raises(
            EmptyDataError,
            helper.read_ema_csv,
            _write(d, "empty.csv", ""),
            "webscreen_id",
            0,
        )


def test_first_run_accepts_missing_and_empty_ema_file():
    with tempfile.TemporaryDirectory() as d:
        catch = _Catch()
        helper.logger.addHandler(catch)
        try:
            for path in (os.path.join(d, "nope.csv"), _write(d, "empty.csv", "")):
                df = helper.read_ema_csv(path, "webscreen_id", first_run=True)
                assert df.empty and list(df.columns) == EMA_COLS
                # the selection code sees it as "nobody scheduled yet"
                assert (
                    sel.already_scheduled_ids(df, "int_ema_arm_1", "webscreen_id")
                    == set()
                )
        finally:
            helper.logger.removeHandler(catch)
        assert len(catch.msgs) == 2 and all("--first-run" in m for m in catch.msgs)


def test_first_run_does_not_hide_an_unparsable_file_or_real_data():
    with tempfile.TemporaryDirectory() as d:
        _raises(
            pd.errors.ParserError,
            helper.read_ema_csv,
            _write(d, "bad.csv", "a,b\n1,2\n1,2,3,4\n"),
            "webscreen_id",
            first_run=True,
        )
        path = _write(d, "a.csv", ",".join(EMA_COLS) + "\n1,int_ema_arm_1,,1\n")
        assert len(helper.read_ema_csv(path, "webscreen_id", first_run=True)) == 1


# ---- writing
def test_write_all_rows_in_one_file_and_create_folder():
    with tempfile.TemporaryDirectory() as d:
        path = helper.write_csv_file(ROWS, os.path.join(d, "new", "dir", "out.csv"))
        assert path is not None
        back = pd.read_csv(path, dtype=str)
        assert len(back) == 3 and list(back["id"]) == ["1", "1", "2"]


def test_write_accepts_a_dataframe():
    with tempfile.TemporaryDirectory() as d:
        out = helper.write_csv_file(pd.DataFrame(ROWS), os.path.join(d, "out.csv"))
        assert out is not None
        assert len(pd.read_csv(out)) == 3


def test_write_nothing_creates_no_file():
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "out.csv")
        assert helper.write_csv_file([], target) is None
        assert not os.path.exists(target)


def test_write_never_overwrites():
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "out.csv")
        helper.write_csv_file(ROWS, target)
        _raises(FileExistsError, helper.write_csv_file, ROWS[:1], target)
        assert len(pd.read_csv(target)) == 3  # original untouched


def test_write_failure_raises():
    with tempfile.TemporaryDirectory() as d:
        blocker = _write(d, "a_file", "x")  # a file where a folder is needed
        _raises(OSError, helper.write_csv_file, ROWS, os.path.join(blocker, "out.csv"))


# ---- logging
def test_import_does_not_configure_logging():
    code = "import logging, ema_scheduler_redcap.ema_helper; assert not logging.getLogger().handlers, logging.getLogger().handlers"
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=HERE,
        capture_output=True,
        text=True,
        check=False,
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
