# ema-scheduler-redcap

Creates randomized EMA (ecological momentary assessment) schedules for a longitudinal
REDCap study. It reads CSV files and writes CSV files. It never talks to REDCap.

For each EMA event, it finds participants who are due a schedule, generates random sample
times, and writes one REDCap import CSV for that event. To upload the CSV, use
`update_redcap` from [redcap-toolbox](https://pypi.org/project/redcap-toolbox/).

## Install

    pip install ema-scheduler-redcap

## Use

    ema-populate [options] <scr_csv> <config_yaml> <output_dir>

| Argument / option | Meaning|
|---|---|
| `<scr_csv>` | Screening data exported from REDCap.|
| `<config_yaml>` | Settings (events, filters, time zones, schedule shape).|
| `<output_dir>` | Folder for the import files. It must already exist.|
| `--dry-run` | Select and generate, but write nothing.|
| `--today=YYYY-MM-DD` | Pretend today is this date. Useful for testing.|
| `--seed=N` | Fix the random seed, for repeatable schedules.|
| `-v`, `--verbose` | More logging.|

Print one participant's schedule, to check the settings by eye:

    ema-gen --help

## Inputs and outputs

- The screening CSV (`scr_csv`) is the only source of who is eligible. It needs one row per
  participant. It must contain the ID column, every column named in the config's `filters`,
  and each event's start date, start time, time zone and state columns. A missing column
  stops the run with an error naming it. The state column helps with timezone-aware scheduling.
- Each event's existing EMA export is read from the **same folder as the screening CSV**.
  The file name comes from `ema_csv` in the config.
- A participant is scheduled for an event if they pass the filters, have a start date,
  are not already in that event's EMA file, and their start date falls in the scheduling
  window (`max_days_before_start` before the start through `max_days_after_start` after).
- **A missing or empty EMA file logs a warning** (`EMA file missing or empty`) and is treated
  as "nobody is scheduled yet" for that event. Watch your logs for that message: if an
  export is lost by accident, everyone who is due will be scheduled again.
- One output file per event is written to `<output_dir>`. Its name is the event's
  `output_csv` value in the config, for example `redcap__int_ema_cache.csv`. It must be a
  plain file name, not a path. If you use the `{ema_csv_name}` placeholder, it is replaced by
  the EMA file's name without extension, and the pattern must be quoted in YAML:
  `output_csv: "{ema_csv_name}_cache.csv"`.
- Output files are **overwritten on every run**, using a temporary file and a rename, so a
  failed run never leaves a half-written file. If nobody is due, no file is written.
- Times are generated in each participant's local time zone and written in REDCap's time
  zone (`default: central_tz`).

## Configuration

A YAML file with top-level settings, shared `defaults`, and an `events` section whose
entries override the defaults.

- **Top level:** 
  - `id_field`, 
  - `sample_time_field`, 
  - `central_tz`, 
  - `timezone_field`,
  - `state_field`, 
  - `timezones`, 
  - `no_dst_overrides`.
  

- **`defaults`** (any of these can also be set per event): 
  - `day_field`, 
  - `start_time_field`,
  - `start_offset_days`, 
  - `max_days_before_start`, 
  - `max_days_after_start`, 
  - `samples_per_day`,
  - `sampling_min`, 
  - `gap_min`, 
  - `max_iters`, 
  - `filters`.

- **Per event:** 
  - `start_date_field`, 
  - `days`, 
  - `ema_csv`, 
  - `output_csv`.

A full example is in the repository:
[`config/test_config.yaml`](https://github.com/uwmadison-chm/ema-scheduler-redcap/blob/main/config/test_config.yaml).

## Development

    uv sync
    uv run pytest