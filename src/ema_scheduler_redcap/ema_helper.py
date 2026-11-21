#!/usr/bin/env python

"""
CSV helpers for the EMA scheduler.

Logging is not configured here; the command-line entry point does that once.
"""

import logging
import os
from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError

logger = logging.getLogger(__name__)


def read_csv_file(path: str | Path) -> pd.DataFrame:
    """Read a CSV as text, with blanks as "". Raises if the file is missing, empty or unparsable."""
    return pd.read_csv(path, dtype=str, na_filter=False)


def read_ema_csv(path: str | Path, id_field: str) -> pd.DataFrame:
    """
    Read the EMA data. A missing or empty file is treated as "nobody scheduled yet",
    with a warning (look for "EMA file missing or empty" in the log). Note that on a
    running study this also happens if the file is lost, and everyone would then be
    scheduled again, so do check that warning.
    """
    try:
        return read_csv_file(path)
    except (FileNotFoundError, EmptyDataError):
        logger.warning(
            f"EMA file missing or empty ({path}); assuming no one is scheduled yet for this event"
        )
        return pd.DataFrame(
            columns=[
                id_field,
                "redcap_event_name",
                "redcap_repeat_instrument",
                "redcap_repeat_instance",
            ]
        )


def write_csv_file(rows: pd.DataFrame | list[dict], path: str | Path) -> Path | None:
    """Write all rows to one file, replacing any file already there.

    Returns None (and writes nothing) if there are no rows. The rows are written to
    "<name>.tmp" first and then renamed over the real name, so a crash never leaves a
    half-written import file: it is either the old file or the complete new one.
    """
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if df.empty:
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        path.name + ".tmp"
    )  # ends in .tmp, so a "*.csv" search never picks it up
    try:
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path
