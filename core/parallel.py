"""Parallel processing and Flynn's classification (CAPP Unit 3).

    SISD  one processor, one data stream: machines are served one after another.
    SIMD  one instruction applied to many data items at once: the same limit
          check done on a whole array of readings in a single vector operation.
    MIMD  several processors each running their own program on their own data:
          one worker (with its own CPU and memory) per machine, all at once.

Reading a sensor takes time (`io_latency`): the processor waits for the device.
That wait is what the MIMD run overlaps. It is simulated here with sleep(),
because there is no real sensor to wait for.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from config import MACHINES, SENSORS

from .sensors import Plant
from .stages import Packet, Stages

FLYNN = [
    {"class": "SISD", "instruction streams": "1", "data streams": "1",
     "in this project": "One CPU serves the machines one after another"},
    {"class": "SIMD", "instruction streams": "1", "data streams": "many",
     "in this project": "One limit check applied to an array of readings at once"},
    {"class": "MISD", "instruction streams": "many", "data streams": "1",
     "in this project": "Not used (rare in practice)"},
    {"class": "MIMD", "instruction streams": "many", "data streams": "many",
     "in this project": "One worker with its own CPU per machine, all running together"},
]


def _streams(n_streams: int, readings: int, seed: int) -> list:
    """n_streams independent machines, each with `readings` samples of every sensor."""
    streams = []
    for i in range(n_streams):
        plant = Plant(seed + i)
        machine = MACHINES[i % len(MACHINES)]
        devices = [d for d in plant.devices if d.machine.key == machine.key]
        packets = []
        for _ in range(readings):
            sample = dict((d.device_id, raw) for d, raw in plant.sample())
            for d in devices:
                packets.append(Packet(len(packets), d.machine, d.spec, sample[d.device_id]))
        streams.append(packets)
    return streams


def _serve(packets: list, io_latency: float) -> int:
    stages = Stages()                    # its own CPUs and memory: an independent processor
    alerts = 0
    for p in packets:
        time.sleep(io_latency)           # wait for the sensor
        stages.run_all(p)
        alerts += p.status != "NORMAL"
    return alerts


def run_sisd(n_streams: int, readings: int = 5, io_latency: float = 0.005, seed: int = 11) -> float:
    streams = _streams(n_streams, readings, seed)
    t0 = time.perf_counter()
    for packets in streams:
        _serve(packets, io_latency)
    return time.perf_counter() - t0


def run_mimd(n_streams: int, readings: int = 5, io_latency: float = 0.005, seed: int = 11) -> float:
    streams = _streams(n_streams, readings, seed)
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n_streams) as pool:
        list(pool.map(lambda packets: _serve(packets, io_latency), streams))
    return time.perf_counter() - t0


def benchmark(stream_counts=(1, 2, 4, 8), readings: int = 5, io_latency: float = 0.005) -> list:
    rows = []
    for n in stream_counts:
        sisd = run_sisd(n, readings, io_latency)
        mimd = run_mimd(n, readings, io_latency)
        rows.append({"machines": n, "readings": n * readings * len(SENSORS),
                     "SISD seconds": round(sisd, 3), "MIMD seconds": round(mimd, 3),
                     "speedup": round(sisd / mimd, 2)})
    return rows


def simd_demo(n: int = 200_000, limit: float = 75.0, seed: int = 3) -> dict:
    """The same limit check done one value at a time and as one vector operation.

    NumPy runs the vector version in compiled code that uses the processor's
    SIMD instructions. Note that a large part of the measured speedup also comes
    from not running a Python loop, so do not quote it as a pure SIMD figure.
    """
    import numpy as np

    values = np.random.default_rng(seed).normal(62.0, 8.0, n)
    as_list = values.tolist()

    t0 = time.perf_counter()
    scalar_hits = 0
    for v in as_list:                    # one compare per loop turn
        if v >= limit:
            scalar_hits += 1
    scalar = time.perf_counter() - t0

    t0 = time.perf_counter()
    vector_hits = int((values >= limit).sum())      # one compare over the whole array
    vector = time.perf_counter() - t0

    return {"values": n, "limit": limit, "over limit": vector_hits, "same answer": scalar_hits == vector_hits,
            "scalar seconds": scalar, "vector seconds": vector, "speedup": scalar / vector if vector else 0.0}
