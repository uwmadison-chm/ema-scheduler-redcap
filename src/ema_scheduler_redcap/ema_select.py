#!/usr/env/bin python

"""
Choose who needs an EMA schedule for each event.
"""

import pandas as pd

EVENT_FIELD = "redcap_event_name"
INSTANCE_FIELD = "redcap_repeat_instance"


def check_columns(df: pd.DataFrame, needed, name: str) -> None:
    missing = sorted(set(needed) - set(df.columns))
    if missing:
        raise KeyError(f"{name} data is missing columns: {missing}")


def _is_blank(col: pd.Series) -> pd.Series:
    return col.fillna("").astype(str).str.strip() == ""


def apply_filters(df: pd.DataFrame, rules: list[dict]) -> pd.DataFrame:
    """Rows where every rule matches. Rules look like {field, op, value}."""
    check_columns(df, {r["field"] for r in rules}, "input")
    mask = pd.Series(True, index=df.index)
    for r in rules:
        col, op = df[r["field"]], r["op"]
        if op == "blank":
            mask &= _is_blank(col)
        elif op == "not_blank":
            mask &= ~_is_blank(col)
        elif op == "equals":
            mask &= col == r["value"]
        elif op == "not_equals":
            mask &= col != r["value"]
        else:
            raise ValueError(f"Unknown filter op: {r}")
    return df[mask]


def already_scheduled_ids(ema_df: pd.DataFrame, event_name: str, id_field: str) -> set:
    """
    IDs that have any row in this event in the EMA data. A different event
    name does not count.
    """
    check_columns(ema_df, {id_field, EVENT_FIELD}, "ema")
    return set(ema_df.loc[ema_df[EVENT_FIELD] == event_name, id_field])


def select_for_event(scr_df: pd.DataFrame, ev: dict, scheduled_ids: set, id_field: str):
    """
    Rows of scr_df that pass this event's filters and are not scheduled yet.
    Returns (rows_to_schedule, counts). Raises, instead of guessing, if a
    participant would be scheduled twice or has no ID.
    """
    check_columns(scr_df, {id_field}, "input")
    passed = apply_filters(scr_df, ev["input_filters"])
    ids = passed[id_field]
    if _is_blank(ids).any():
        raise ValueError(
            f"{ev['redcap_event_name']}: a row with a blank {id_field} passed the filters"
        )
    dupes = sorted(set(ids[ids.duplicated()]))
    if dupes:
        raise ValueError(
            f"{ev['redcap_event_name']}: more than one row passed the filters for: {dupes}"
        )
    todo = passed[~ids.isin(scheduled_ids)]
    counts = {
        "passed_filters": len(passed),
        "already_scheduled": len(passed) - len(todo),
        "to_schedule": len(todo),
    }
    return todo, counts
