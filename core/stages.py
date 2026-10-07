"""The five processing stages every reading goes through.

    1 acquire   sensor -> bus -> buffer register, time-stamped
    2 validate  reject counts the ADC cannot produce
    3 compute   CPU program COMPUTE: scale, store in history, moving average
    4 detect    CPU program DETECT: compare with limits, pick a status
    5 output    update the dashboard data, raise alerts, write the CSV log

A Packet carries a reading from stage to stage, like the latches between the
stages of a pipelined processor. Stages 3 and 4 each have their own CPU
(register set), so two different readings can be in them at the same time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config import ADC_MAX, STATUS_NAMES, MachineSpec, SensorSpec

from . import alu, firmware
from .cpu import CPU

STAGE_NAMES = ["Acquire", "Validate", "Compute", "Detect", "Output"]


@dataclass
class Packet:
    seq: int
    machine: MachineSpec
    spec: SensorSpec
    raw: int
    time: Optional[datetime] = None
    buffer: Optional[int] = None       # buffer register loaded from the bus
    valid: bool = True
    detail: str = ""
    value_t: Optional[int] = None      # tenths, as held in the CPU
    avg_t: Optional[int] = None
    value: Optional[float] = None
    avg: Optional[float] = None
    ieee: Optional[alu.IEEE754] = None
    status: str = ""
    grant_position: int = 0

    @property
    def channel(self) -> tuple:
        return (self.machine.key, self.spec.key)


class Stages:
    def __init__(self, sink=None):
        self.memory = {}                   # channel -> data-memory image
        self.compute_cpu = CPU("compute")
        self.detect_cpu = CPU("detect")
        self.sink = sink                   # called with each finished packet
        self.instructions = 0
        self.micro_ops = 0
        self.multiplies = 0
        self.divides = 0

    def memory_for(self, p: Packet) -> list:
        if p.channel not in self.memory:
            self.memory[p.channel] = firmware.new_memory(p.spec)
        return self.memory[p.channel]

    # ---- stage 1
    def acquire(self, p: Packet) -> Packet:
        p.buffer = p.raw
        p.time = p.time or datetime.now()
        return p

    # ---- stage 2
    def validate(self, p: Packet) -> Packet:
        if not isinstance(p.buffer, int) or not 0 <= p.buffer <= ADC_MAX:
            p.valid = False
            p.detail = "count %s is outside the ADC range 0-%d" % (p.buffer, ADC_MAX)
        return p

    # ---- stage 3
    def compute(self, p: Packet, trace: bool = False):
        if not p.valid:
            return p if not trace else (p, [])
        result = self.compute_cpu.run(firmware.PROGRAM, "COMPUTE", self.memory_for(p),
                                      {0: p.buffer}, trace=trace)
        p.value_t, p.avg_t = result.outputs[1], result.outputs[2]
        p.value, p.avg = p.value_t / 10.0, p.avg_t / 10.0
        p.ieee = alu.ieee754_encode(p.value)
        self._count(result)
        return p if not trace else (p, result.trace)

    # ---- stage 4
    def detect(self, p: Packet, trace: bool = False):
        if not p.valid:
            p.status = "INVALID"
            return p if not trace else (p, [])
        result = self.detect_cpu.run(firmware.PROGRAM, "DETECT", self.memory_for(p),
                                     {1: p.value_t}, trace=trace)
        p.status = STATUS_NAMES[result.outputs[0]]
        if p.status != "NORMAL":
            p.detail = _limit_text(p)
        self._count(result)
        return p if not trace else (p, result.trace)

    # ---- stage 5
    def output(self, p: Packet) -> Packet:
        if self.sink:
            self.sink(p)
        return p

    def run_all(self, p: Packet) -> Packet:
        return self.output(self.detect(self.compute(self.validate(self.acquire(p)))))

    def functions(self) -> list:
        return [self.acquire, self.validate, self.compute, self.detect, self.output]

    def _count(self, result):
        self.instructions += result.instructions
        self.micro_ops += result.micro_ops
        self.multiplies += result.multiplies
        self.divides += result.divides


def _limit_text(p: Packet) -> str:
    s, v = p.spec, p.value
    checks = [(s.hi_crit, ">=", "critical high"), (s.lo_crit, "<=", "critical low"),
              (s.hi_warn, ">=", "warning high"), (s.lo_warn, "<=", "warning low")]
    for limit, sign, label in checks:
        if limit is None:
            continue
        if (sign == ">=" and v >= limit) or (sign == "<=" and v <= limit):
            return "%.1f %s %s %s limit %.1f" % (v, s.unit, sign, label, limit)
    return ""
