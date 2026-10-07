"""CSV logging (output unit): every reading and every status change is written to disk."""
from __future__ import annotations

import csv
import os

READING_FIELDS = ["time", "machine", "sensor", "raw_count", "valid", "value", "unit",
                  "moving_avg", "status", "ieee754_hex"]
ALERT_FIELDS = ["time", "machine", "sensor", "from_status", "to_status", "value", "unit", "detail"]


class CsvLog:
    def __init__(self, folder: str):
        os.makedirs(folder, exist_ok=True)
        self.readings_path = os.path.join(folder, "readings_log.csv")
        self.alerts_path = os.path.join(folder, "alerts_log.csv")
        self._readings = self._open(self.readings_path, READING_FIELDS)
        self._alerts = self._open(self.alerts_path, ALERT_FIELDS)

    @staticmethod
    def _open(path: str, fields: list):
        is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        handle = open(path, "a", newline="", encoding="utf-8")
        writer = csv.DictWriter(handle, fieldnames=fields)
        if is_new:
            writer.writeheader()
        return handle, writer

    def reading(self, row: dict):
        self._readings[1].writerow(row)

    def alert(self, row: dict):
        self._alerts[1].writerow(row)
        self._alerts[0].flush()

    def flush(self):
        self._readings[0].flush()

    def close(self):
        self._readings[0].close()
        self._alerts[0].close()
