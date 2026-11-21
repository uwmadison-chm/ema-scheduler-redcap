#!/usr/bin/env python

"""Tests for the CSV helpers (reading the screening and EMA files, writing the import file)."""

import logging
import subprocess
import sys

import pandas as pd
import pytest
from pandas.errors import EmptyDataError, ParserError

from ema_scheduler_redcap import ema_helper as helper
from ema_scheduler_redcap import ema_select as sel

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
MALFORMED = "a,b\n1,2\n1,2,3,4\n"  # the second data row has too many fields


@pytest.fixture
def make_csv(tmp_path):
    """make_csv(name, text) -> path of a new file with that text, in this test's own folder."""

    def _make(name, text):
        path = tmp_path / name
        path.write_text(text)
        return path

    return _make


# ---- reading
def test_read_keeps_text_and_blanks(make_csv):
    df = helper.read_csv_file(make_csv("a.csv", "id,when\n007,\n008,2026-01-01\n"))
    assert list(df["id"]) == ["007", "008"]  # leading zeros survive
    assert list(df["when"]) == ["", "2026-01-01"]  # blank is "", not NaN


def test_read_header_only_is_fine(make_csv):
    df = helper.read_csv_file(make_csv("a.csv", "id,redcap_event_name\n"))
    assert df.empty and list(df.columns) == ["id", "redcap_event_name"]


@pytest.mark.parametrize(
    ("text", "error"),
    [(None, FileNotFoundError), ("", EmptyDataError), (MALFORMED, ParserError)],
    ids=["missing", "empty", "malformed"],
)
def test_read_bad_files_raise(tmp_path, text, error):
    path = tmp_path / "x.csv"
    if text is not None:  # None means the file does not exist
        path.write_text(text)
    with pytest.raises(error):
        helper.read_csv_file(path)


# ---- EMA file
@pytest.mark.parametrize("text", [None, ""], ids=["missing", "empty"])
def test_ema_missing_or_empty_gives_an_empty_frame_and_a_warning(
    tmp_path, caplog, text
):
    path = tmp_path / "ema.csv"
    if text is not None:  # None means the file does not exist
        path.write_text(text)
    with caplog.at_level(logging.WARNING, logger=helper.logger.name):
        df = helper.read_ema_csv(path, "webscreen_id")
    assert df.empty and list(df.columns) == EMA_COLS
    # the selection code sees it as "nobody scheduled yet"
    assert sel.already_scheduled_ids(df, "int_ema_arm_1", "webscreen_id") == set()
    assert len(caplog.records) == 1
    assert "EMA file missing or empty" in caplog.messages[0]


def test_ema_unparsable_file_still_raises(make_csv):
    with pytest.raises(ParserError):
        helper.read_ema_csv(make_csv("bad.csv", MALFORMED), "webscreen_id")


def test_ema_file_with_data_is_read_without_a_warning(make_csv, caplog):
    path = make_csv("a.csv", ",".join(EMA_COLS) + "\n1,int_ema_arm_1,,1\n")
    with caplog.at_level(logging.WARNING, logger=helper.logger.name):
        df = helper.read_ema_csv(path, "webscreen_id")
    assert len(df) == 1
    assert not caplog.records


# ---- writing
def test_write_all_rows_in_one_file_and_create_folder(tmp_path):
    target = tmp_path / "new" / "dir" / "out.csv"
    assert helper.write_csv_file(ROWS, target) == target  # returns the path it wrote
    back = pd.read_csv(target, dtype=str)
    assert len(back) == 3 and list(back["id"]) == ["1", "1", "2"]


def test_write_accepts_a_dataframe(tmp_path):
    target = tmp_path / "out.csv"
    assert helper.write_csv_file(pd.DataFrame(ROWS), target) == target
    assert len(pd.read_csv(target)) == 3


def test_write_nothing_creates_no_file(tmp_path):
    target = tmp_path / "out.csv"
    assert helper.write_csv_file([], target) is None
    assert not target.exists()


def test_write_replaces_an_existing_file(tmp_path):
    target = tmp_path / "out.csv"
    helper.write_csv_file(ROWS, target)
    helper.write_csv_file(ROWS[:1], target)
    assert len(pd.read_csv(target)) == 1  # the new content replaced the old
    assert [f.name for f in tmp_path.iterdir()] == [
        "out.csv"
    ]  # no temporary file left behind


def test_failed_write_keeps_the_old_file_and_leaves_no_temp_file(tmp_path, monkeypatch):
    target = tmp_path / "out.csv"
    helper.write_csv_file(ROWS, target)

    def fail(self, *args, **kwargs):
        raise OSError("disk full")

    with monkeypatch.context() as m:
        m.setattr(pd.DataFrame, "to_csv", fail)
        with pytest.raises(OSError, match="disk full"):
            helper.write_csv_file(ROWS[:1], target)
    assert len(pd.read_csv(target)) == 3  # the old file is untouched
    assert [f.name for f in tmp_path.iterdir()] == ["out.csv"]


def test_write_failure_raises(make_csv):
    blocker = make_csv("a_file", "x")  # a file where a folder is needed
    with pytest.raises(OSError):
        helper.write_csv_file(ROWS, blocker / "out.csv")


# ---- logging
def test_import_does_not_configure_logging(tmp_path):
    code = "import logging, ema_scheduler_redcap.ema_helper; assert not logging.getLogger().handlers, logging.getLogger().handlers"
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
