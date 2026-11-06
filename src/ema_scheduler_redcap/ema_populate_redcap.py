#!/usr/bin/env python

"""
Create EMA schedules for participants who are due one.

Reads the screening CSV and one EMA CSV per event (no REDCap access) and writes
one REDCap import CSV per event, ready to upload with update_redcap. Each event's EMA
file is looked for in the same folder as the screening CSV; the file names are in the config.

For each event, a participant is scheduled if they pass the filters, have a
start date, are not already in that event's EMA file, and the start date
(start date field + offset) is inside the allowed window.

Usage:
  populate_redcap_ema.py [options] <scr_csv> <config_yaml>

Options:
  --first-run         The EMA files may be missing or empty (nobody scheduled yet)
  --dry-run           Say what would be scheduled; write nothing
  --today=<date>      Pretend today is this date (YYYY-MM-DD), for testing
  --seed=<int>        Seed the random generator, for repeatable schedules
  -v --verbose        Print debugging information
"""

import logging
import random
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from docopt import docopt

from . import ema_gen
from .ema_helper import read_csv_file, read_ema_csv, write_csv_file
from .ema_select import (
    EVENT_FIELD,
    already_scheduled_ids,
    check_columns,
    select_for_event,
)

logger = logging.getLogger(__name__)


def load_config(path):
    """Read the YAML; give every event the defaults plus its own settings."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    events = {}
    for name, ev in raw["events"].items():
        merged = {**raw["defaults"], **ev, "redcap_event_name": name}
        rules = raw["defaults"].get("filters", []) + ev.get("filters", [])
        # CSV values are text, so compare as text (YAML reads 0 as a number)
        merged["input_filters"] = [
            {**r, "value": str(r["value"])} if "value" in r else r for r in rules
        ]
        events[name] = merged
    cfg = {
        k: raw[k]
        for k in (
            "id_field",
            "sample_time_field",
            "central_tz",
            "timezone_field",
            "state_field",
        )
    }
    cfg["events"] = events
    cfg["timezones"] = {str(code): zone for code, zone in raw["timezones"].items()}
    cfg["overrides"] = {
        (str(o["zone_code"]), o["state"].upper()): o["iana"]
        for o in raw.get("no_dst_overrides", [])
    }
    return cfg


def participant_zone(row, cfg):
    """IANA zone name for this participant, or None if the code is blank/unknown."""
    code, state = (
        row[cfg["timezone_field"]].strip(),
        row[cfg["state_field"]].strip().upper(),
    )
    return cfg["overrides"].get((code, state)) or cfg["timezones"].get(code)


def to_central(local_dt, zone, central):
    """Naive local wall-clock time in `zone` -> naive time in the central zone."""
    return (
        local_dt.replace(tzinfo=ZoneInfo(zone))
        .astimezone(ZoneInfo(central))
        .replace(tzinfo=None)
    )


def schedule_event(todo, ev, cfg, today):
    """Schedule everyone in `todo`. Returns (rows, counts of what happened)."""
    id_field, sample_time_field = cfg["id_field"], cfg["sample_time_field"]
    rows, counts = [], Counter()
    for _, p in todo.iterrows():
        pid = p[id_field]
        raw_date = p[ev["start_date_field"]].strip()
        if not raw_date:
            counts["no start date"] += 1
            continue
        try:
            start = datetime.strptime(raw_date[:10], "%Y-%m-%d").date() + timedelta(
                days=ev["start_offset_days"]
            )
            start_delta = ema_gen.time_str_to_delta(p[ev["start_time_field"]].strip())
        except ValueError:
            logger.warning(
                f"{ev['redcap_event_name']} {pid}: unreadable start date {raw_date!r} or start time; skipped"
            )
            counts["bad date/time"] += 1
            continue
        zone = participant_zone(p, cfg)
        if zone is None:
            logger.warning(
                f"{ev['redcap_event_name']} {pid}: blank or unknown time zone code "
                f"{p[cfg['timezone_field']]!r}; skipped"
            )
            counts["bad time zone"] += 1
            continue
        days_away = (start - today).days
        if (
            days_away > ev["max_days_before_start"]
            or days_away < -ev["max_days_after_start"]
        ):
            logger.debug(
                f"{ev['redcap_event_name']} {pid}: start {start} is {days_away} days from today; skipped"
            )
            counts["outside window"] += 1
            continue
        times = ema_gen.generate_schedule(
            datetime.combine(start, datetime.min.time()),
            start_delta,
            ev["days"],
            ev["samples_per_day"],
            ev["sampling_min"],
            ev["gap_min"],
            ev["max_iters"],
        )
        for n, (t, day) in enumerate(times, start=1):
            rows.append(
                {
                    id_field: pid,
                    "redcap_event_name": ev["redcap_event_name"],
                    "redcap_repeat_instrument": "",
                    "redcap_repeat_instance": n,
                    sample_time_field: to_central(t, zone, cfg["central_tz"]).strftime(
                        "%Y-%m-%d %H:%M:00"
                    ),
                    ev["day_field"]: day,
                }
            )
        counts["scheduled"] += 1
    return rows, counts


def main(scr_csv, cfg_yaml, first_run=False, dry_run=False, today=None, now=None):
    """Returns {event_name: path of the import file written}."""
    today, now = today or date.today(), now or datetime.now()
    cfg = load_config(cfg_yaml)
    id_field = cfg["id_field"]
    scr_df = read_csv_file(scr_csv)

    rows_by_event = {}
    for name, ev in cfg["events"].items():
        check_columns(
            scr_df,
            {
                ev["start_date_field"],
                ev["start_time_field"],
                cfg["timezone_field"],
                cfg["state_field"],
            },
            "scr",
        )
        ema_path = (
            Path(scr_csv).parent / ev["ema_csv"]
        )  # same folder as the screening CSV
        ema_df = read_ema_csv(ema_path, id_field, first_run=first_run)
        done = already_scheduled_ids(ema_df, name, id_field)
        other = sorted(set(ema_df[EVENT_FIELD]) - {name})
        if other:
            raise ValueError(
                f"{ema_path} has rows for {other}, but this file must only hold {name}"
            )
        todo, selected = select_for_event(scr_df, ev, done, id_field)
        rows_by_event[name], counts = schedule_event(todo, ev, cfg, today)
        logger.info(
            f"{name}: {selected['passed_filters']} pass filters, "
            f"{selected['already_scheduled']} already scheduled; "
            + ", ".join(f"{k} {v}" for k, v in counts.items())
        )

    written = {}
    if dry_run:
        logger.info(
            "Dry run: "
            + ", ".join(f"{n} {len(r)} rows" for n, r in rows_by_event.items())
        )
        return written
    stamp = now.strftime(
        "%Y%m%d_%H%M%S"
    )  # all rows are generated first, so a failure writes nothing
    for name, rows in rows_by_event.items():
        out = write_csv_file(
            rows, cfg["events"][name]["output_csv"].replace("{timestamp}", stamp)
        )
        if out:
            written[name] = out
            logger.info(f"{name}: wrote {len(rows)} rows to {out}")
        else:
            logger.info(f"{name}: nothing to schedule; no file written")
    return written


def cli():
    args = docopt(__doc__)
    logging.basicConfig(
        level=logging.DEBUG if args["--verbose"] else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    if args["--seed"]:
        random.seed(int(args["--seed"]))
    today = (
        datetime.strptime(args["--today"], "%Y-%m-%d").date()
        if args["--today"]
        else None
    )
    main(
        args["<scr_csv>"],
        args["<config_yaml>"],
        args["--first-run"],
        args["--dry-run"],
        today,
    )


if __name__ == "__main__":
    cli()
