#!/usr/env/bin python

"""
CSV helpers for the EMA scheduler.

Logging is not configured here; the command-line entry point does that once.
"""

import logging
from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError

logger = logging.getLogger(__name__)


def read_csv_file(path: str | Path) -> pd.DataFrame:
    """Read a CSV as text, with blanks as "". Raises if the file is missing, empty or unparsable."""
    return pd.read_csv(path, dtype=str, na_filter=False)


def read_ema_csv(
    path: str | Path,
    id_field: str,
    first_run: bool = False,
) -> pd.DataFrame:
    """
    Read the EMA data. A missing or empty file raises, because on a normal run it
    means something went wrong and treating it as "nobody scheduled yet" would
    reschedule everyone. With first_run=True it returns an empty frame instead.
    """
    try:
        return read_csv_file(path)
    except (FileNotFoundError, EmptyDataError):
        if not first_run:
            raise
        logger.warning(
            f"--first-run: EMA file missing or empty ({path}); "
            f"treating everyone as not yet scheduled"
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
    """Write all rows to one new file.
    Returns None (and writes nothing) if there are no rows. Never overwrites."""
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if df.empty:
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, mode="x")
    return path
