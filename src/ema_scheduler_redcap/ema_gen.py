#!/usr/env/bin python

"""
Random EMA sample times.
Datetimes are naive (no timezone / DST handling).
Timezone-aware computation is in ema_populate_redcap
"""

import csv
import random
import sys
from datetime import datetime, timedelta
from itertools import pairwise

from docopt import docopt


def random_minute_offsets(num_samples, total_minutes, gap_minutes, max_iters=1000):
    """
    num_samples minute offsets within total_minutes, more than gap_minutes apart.
    The window is split into num_samples equal parts with one random sample in
    each; if two land too close together it re-rolls, up to max_iters times.
    """
    part = total_minutes // num_samples
    for _ in range(max_iters):
        offsets = [random.randrange(part) + i * part for i in range(num_samples)]
        if all(b - a > gap_minutes for a, b in pairwise(offsets)):
            return offsets
    raise ValueError(
        f"No valid schedule found in {max_iters} tries "
        f"(samples={num_samples}, window={total_minutes} min, gap={gap_minutes} min)"
    )


def time_str_to_delta(time_string):
    """'15:00', '3:00 pm' or '3:00PM' -> timedelta from midnight."""
    s = time_string.upper().replace(" ", "")
    parsed = datetime.strptime(s, "%I:%M%p" if "M" in s else "%H:%M")
    return timedelta(hours=parsed.hour, minutes=parsed.minute)


def generate_schedule(
    start_date,
    start_delta,
    days,
    samples_per_day,
    sampling_min,
    gap_min,
    max_iters=1000,
):
    """[(datetime, day_number)]: samples_per_day per day for `days` days, from start_date (midnight datetime)."""
    schedule = []
    for day in range(days):
        day_start = start_date + timedelta(days=day) + start_delta
        offsets = random_minute_offsets(
            samples_per_day, sampling_min, gap_min, max_iters
        )
        schedule += [(day_start + timedelta(minutes=m), day + 1) for m in offsets]
    return schedule


CLI_DOC = """
Print one participant's EMA schedule as REDCap import CSV (naive local times,
no timezone conversion). Handy for checking the random schedules by eye.

Usage:
  ema_gen.py [options] <record_id> <sched_field> <sched_field_days> <start_time> <days> <samples_per_day> <sampling_min> <gap_min>

Options:
  --rec-field=<str>         Name of the record_id field [default: record_id]
  --event-name=<str>        Written as redcap_event_name (and redcap_repeat_instrument unless --instrument-field is given)
  --instrument-field=<str>  Value for redcap_repeat_instrument
  --start-date=<date>       First day, YYYY-MM-DD, or "tomorrow" [default: tomorrow]
  --seed=<int>              Seed the random generator, for repeatable output
"""


def cli(argv=None):
    a = docopt(CLI_DOC, argv)
    if a["--seed"]:
        random.seed(int(a["--seed"]))
    day = (
        datetime.now().date() + timedelta(days=1)
        if a["--start-date"] == "tomorrow"
        else datetime.strptime(a["--start-date"], "%Y-%m-%d").date()
    )
    schedule = generate_schedule(
        datetime.combine(day, datetime.min.time()),
        time_str_to_delta(a["<start_time>"]),
        int(a["<days>"]),
        int(a["<samples_per_day>"]),
        int(a["<sampling_min>"]),
        int(a["<gap_min>"]),
    )
    event = a["--event-name"]
    instrument = a["--instrument-field"] or event
    rows = []
    for n, (t, d) in enumerate(schedule, start=1):
        row = {a["--rec-field"]: a["<record_id>"]}
        if event:
            row["redcap_event_name"] = event
        if instrument:
            row["redcap_repeat_instrument"] = instrument
        row["redcap_repeat_instance"] = n
        row[a["<sched_field>"]] = t.strftime("%Y-%m-%d %H:%M:00")
        row[a["<sched_field_days>"]] = d
        rows.append(row)
    writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)


if __name__ == "__main__":
    cli()
