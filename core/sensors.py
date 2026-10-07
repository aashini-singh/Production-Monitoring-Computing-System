"""Simulated plant: machines with sensors that produce raw ADC counts (input unit).

There is no hardware in this project, so each sensor is a small model:
the value drifts towards a target (its healthy value, or a fault value while
a fault is active) with some random noise, and is then converted to a 10-bit
count exactly as an analogue-to-digital converter would report it.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from config import ADC_MAX, FAULTS, MACHINES, SENSORS, MachineSpec, SensorSpec

OUT_OF_RANGE_COUNT = 4095     # what a disconnected sensor reports


@dataclass
class SensorDevice:
    device_id: int            # position on the bus
    machine: MachineSpec
    spec: SensorSpec
    true_value: float

    @property
    def healthy_value(self) -> float:
        return self.spec.nominal * self.machine.bias


class Plant:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.devices = []
        for machine in MACHINES:
            for spec in SENSORS:
                dev = SensorDevice(len(self.devices), machine, spec, 0.0)
                dev.true_value = dev.healthy_value
                self.devices.append(dev)
        self.active_faults = {}        # machine key -> [fault name, ticks left or None]
        self.auto_faults = False

    # ---- faults
    def inject(self, machine_key: str, fault: str, ticks=None):
        if fault not in FAULTS:
            raise KeyError(fault)
        self.active_faults[machine_key] = [fault, ticks]

    def clear(self, machine_key=None):
        if machine_key is None:
            self.active_faults.clear()
        else:
            self.active_faults.pop(machine_key, None)

    def fault_of(self, machine_key: str):
        entry = self.active_faults.get(machine_key)
        return entry[0] if entry else None

    def _age_faults(self):
        for key in list(self.active_faults):
            left = self.active_faults[key][1]
            if left is not None:
                if left <= 1:
                    del self.active_faults[key]
                else:
                    self.active_faults[key][1] = left - 1
        if self.auto_faults and self.rng.random() < 0.03:
            idle = [m.key for m in MACHINES if m.key not in self.active_faults]
            if idle:
                self.inject(self.rng.choice(idle), self.rng.choice(list(FAULTS)),
                            ticks=self.rng.randint(14, 24))

    # ---- one sampling instant
    def sample(self) -> list:
        """Advance every sensor one tick. Returns [(device, raw count), ...]."""
        self._age_faults()
        out = []
        for dev in self.devices:
            fault = self.fault_of(dev.machine.key)
            target = FAULTS.get(fault, {}).get(dev.spec.key, dev.healthy_value)
            dev.true_value += 0.22 * (target - dev.true_value) + self.rng.gauss(0, dev.spec.noise)
            dev.true_value = min(max(dev.true_value, 0.0), dev.spec.span)
            raw = int(round(dev.true_value / dev.spec.span * ADC_MAX))
            if fault == "Sensor dropout" and dev.spec.key == "temp":
                raw = OUT_OF_RANGE_COUNT
            out.append((dev, raw))
        return out
