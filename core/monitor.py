"""The monitoring engine: ties the plant, the bus, the five stages and the log together.

Call tick() once per sampling interval. Everything the dashboard shows is read
from the attributes of this object.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime

from config import HISTORY_POINTS, MACHINES, SENSORS, STATUS_RANK

from .bus import BusArbiter
from .logger import CsvLog
from .sensors import Plant
from .stages import Packet, Stages


class Monitor:
    def __init__(self, seed=None, log_folder=None, arbitration: str = "polling"):
        self.plant = Plant(seed)
        self.arbiter = BusArbiter(len(self.plant.devices), arbitration)
        self.stages = Stages(sink=self._store)
        self.log = CsvLog(log_folder) if log_folder else None
        self.history = {(m.key, s.key): deque(maxlen=HISTORY_POINTS) for m in MACHINES for s in SENSORS}
        self.latest = {}                 # channel -> last Packet
        self.status = {}                 # channel -> last status text
        self.alerts = deque(maxlen=200)  # newest first
        self.ticks = 0
        self.readings = 0
        self.rejected = 0
        self.units = {m.key: 0.0 for m in MACHINES}
        self.critical_ticks = {m.key: 0 for m in MACHINES}
        self.tick_seconds = 1.0
        self.last_grant = []             # device ids in the order they got the bus
        self._seq = 0

    # ---- one sampling interval
    def tick(self, now: datetime = None) -> list:
        now = now or datetime.now()
        samples = self.plant.sample()
        by_id = {dev.device_id: (dev, raw) for dev, raw in samples}
        priority = {dev.device_id: STATUS_RANK.get(self.status.get((dev.machine.key, dev.spec.key), "NORMAL"), 0)
                    for dev, _ in samples}
        self.last_grant = self.arbiter.grant_order(list(by_id), priority)
        done = []
        for position, dev_id in enumerate(self.last_grant):
            dev, raw = by_id[dev_id]
            self._seq += 1
            packet = Packet(self._seq, dev.machine, dev.spec, raw, time=now, grant_position=position)
            done.append(self.stages.run_all(packet))
        self.ticks += 1
        for m in MACHINES:
            rate = self.latest.get((m.key, "rate"))
            if rate is not None and rate.valid:
                self.units[m.key] += rate.value * self.tick_seconds / 60.0
            if self.machine_status(m.key) == "CRITICAL":
                self.critical_ticks[m.key] += 1
        if self.log:
            self.log.flush()
        return done

    # ---- stage 5 sink
    def _store(self, p: Packet):
        self.readings += 1
        if not p.valid:
            self.rejected += 1
        self.history[p.channel].append(p)
        self.latest[p.channel] = p
        previous = self.status.get(p.channel, "NORMAL")
        if p.status != previous:
            event = {
                "time": p.time.strftime("%H:%M:%S"), "machine": p.machine.key, "sensor": p.spec.name,
                "from_status": previous, "to_status": p.status,
                "value": "" if p.value is None else "%.1f" % p.value, "unit": p.spec.unit,
                "detail": p.detail or "back inside limits",
            }
            self.alerts.appendleft(event)
            if self.log:
                self.log.alert(dict(event, time=p.time.isoformat(timespec="seconds")))
        self.status[p.channel] = p.status
        if self.log:
            self.log.reading({
                "time": p.time.isoformat(timespec="seconds"), "machine": p.machine.key,
                "sensor": p.spec.key, "raw_count": p.raw, "valid": int(p.valid),
                "value": "" if p.value is None else "%.1f" % p.value, "unit": p.spec.unit,
                "moving_avg": "" if p.avg is None else "%.1f" % p.avg, "status": p.status,
                "ieee754_hex": "" if p.ieee is None else p.ieee.hex,
            })

    # ---- summaries
    def machine_status(self, machine_key: str) -> str:
        states = [self.status.get((machine_key, s.key), "NORMAL") for s in SENSORS]
        return max(states, key=lambda s: STATUS_RANK[s])

    def active_alerts(self) -> list:
        return [p for p in self.latest.values() if p.status != "NORMAL"]

    def availability(self, machine_key: str) -> float:
        """Share of sampling intervals in which the machine was not in a critical state."""
        if not self.ticks:
            return 100.0
        return 100.0 * (1 - self.critical_ticks[machine_key] / self.ticks)
