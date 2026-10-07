"""Plant configuration: machines, sensor parameters and alert limits.

The limits below are illustrative values chosen for the simulation. They are
not taken from a real plant; change them here to match your own machines.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

ADC_MAX = 1023          # 10-bit analogue-to-digital converter: raw counts 0..1023
WINDOW = 8              # moving-average window (readings)
HISTORY_POINTS = 120    # points kept per channel for the live charts


@dataclass(frozen=True)
class SensorSpec:
    key: str
    name: str
    unit: str
    span: float                 # engineering value at full ADC scale (raw = 1023)
    nominal: float              # healthy operating value
    noise: float                # random variation per tick
    lo_crit: Optional[float] = None
    lo_warn: Optional[float] = None
    hi_warn: Optional[float] = None
    hi_crit: Optional[float] = None


SENSORS = [
    SensorSpec("temp", "Temperature", "°C", span=150.0, nominal=62.0, noise=0.8,
               hi_warn=75.0, hi_crit=85.0),
    SensorSpec("vib", "Vibration", "mm/s", span=20.0, nominal=2.8, noise=0.22,
               hi_warn=4.5, hi_crit=7.1),
    SensorSpec("cur", "Motor current", "A", span=30.0, nominal=12.0, noise=0.35,
               hi_warn=16.0, hi_crit=19.0),
    SensorSpec("rate", "Output rate", "units/min", span=120.0, nominal=60.0, noise=1.4,
               lo_crit=30.0, lo_warn=45.0),
]
SENSOR_BY_KEY = {s.key: s for s in SENSORS}


@dataclass(frozen=True)
class MachineSpec:
    key: str
    name: str
    bias: float     # multiplies each sensor's nominal value so machines differ


MACHINES = [
    MachineSpec("M1", "CNC lathe", 1.00),
    MachineSpec("M2", "Hydraulic press", 1.06),
    MachineSpec("M3", "Packaging line", 0.94),
]
MACHINE_BY_KEY = {m.key: m for m in MACHINES}

# Fault scenarios: sensor key -> value the machine drifts towards while the fault is active.
FAULTS = {
    "Overheat": {"temp": 91.0, "cur": 17.2},
    "Bearing wear": {"vib": 8.3, "temp": 77.5},
    "Material jam": {"rate": 21.0, "cur": 20.4},
    "Sensor dropout": {},      # temperature sensor sends an out-of-range count
}

STATUS_NAMES = {0: "NORMAL", 1: "WARNING", 2: "CRITICAL"}
STATUS_RANK = {"NORMAL": 0, "INVALID": 1, "WARNING": 2, "CRITICAL": 3}
