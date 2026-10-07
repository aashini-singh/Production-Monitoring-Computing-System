"""Console version of the monitor, for when you do not want the dashboard.

    python run_cli.py                 20 samples, no fault
    python run_cli.py 40 Overheat     40 samples, overheat fault on M1 from sample 10
"""
from __future__ import annotations

import os
import sys

from config import FAULTS, MACHINES, SENSORS
from core.monitor import Monitor

MARK = {"NORMAL": "ok", "WARNING": "WARN", "CRITICAL": "CRIT", "INVALID": "BAD"}


def main():
    samples = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    fault = sys.argv[2] if len(sys.argv) > 2 else None
    if fault and fault not in FAULTS:
        sys.exit("Unknown fault %r. Choose one of: %s" % (fault, ", ".join(FAULTS)))
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    mon = Monitor(seed=1, log_folder=folder)

    header = "sample  " + "  ".join("%-34s" % ("%s %s" % (m.key, m.name)) for m in MACHINES)
    print(header)
    print("        " + "  ".join("%-34s" % " ".join("%-8s" % s.key for s in SENSORS) for _ in MACHINES))
    for n in range(1, samples + 1):
        if fault and n == 10:
            mon.plant.inject("M1", fault)
            print("-- fault injected on M1: %s" % fault)
        mon.tick()
        cells = []
        for m in MACHINES:
            parts = []
            for s in SENSORS:
                p = mon.latest[(m.key, s.key)]
                text = "%.1f" % p.value if p.valid else "----"
                parts.append("%-8s" % (text + ("" if p.status == "NORMAL" else "!")))
            cells.append("%-34s" % " ".join(parts))
        print("%6d  %s" % (n, "  ".join(cells)))

    print()
    for a in reversed(mon.alerts):
        print("%s  %s %-14s %s -> %s  %s" % (a["time"], a["machine"], a["sensor"],
                                              MARK[a["from_status"]], MARK[a["to_status"]], a["detail"]))
    print()
    print("readings %d, rejected %d, instructions %d, micro-operations %d, Booth multiplications %d, divisions %d"
          % (mon.readings, mon.rejected, mon.stages.instructions, mon.stages.micro_ops,
             mon.stages.multiplies, mon.stages.divides))
    print("log written to %s" % mon.log.readings_path)
    mon.log.close()


if __name__ == "__main__":
    main()
