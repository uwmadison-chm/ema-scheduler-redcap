# ema-scheduler-redcap

Reads a screening CSV and one EMA CSV per event, and writes one REDCap import CSV per
event with randomized EMA schedules. 

To import data into REDCap, use `update_redcap` from `redcap-toolbox` package.

    pip install ema-scheduler-redcap
    ema-populate [--first-run] [--dry-run] [--today=YYYY-MM-DD] [--seed=N] <scr_csv> <config_yaml>
    ema-gen --help        # print one participant's schedule, for checking

See `config/test_config.yaml` for the settings.


### Tests

    pip install -e ".[test]"
    pytest
