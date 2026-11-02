# Atlas system overview

Application starts at [main.py](../app/main.py).

The central [configuration](../config/settings.json) is consumed by the [report](../reports/quarterly.md) and the website.

The [metrics module](../app/core/metrics.py) drives the [report builder](../app/core/report.py).
