"""Pipelining (CAPP Unit 3).

The same five stages are run two ways over the same readings:

    non-pipelined   a reading goes through all five stages before the next starts
    pipelined       each stage is its own worker, so five different readings can
                    be in the five stages at the same moment

Each stage is given a fixed stage time (`stage_delay`) on top of its real work,
standing in for the latency a real stage has (sensor settling, ADC conversion,
disk write...). Without it the Python work per stage is only microseconds and
the thread hand-over cost would hide the effect being shown.

Ideal figures for n readings, k stages, stage time t:

    non-pipelined time = n x k x t
    pipelined time     = (k + n - 1) x t
    speedup            = n x k / (k + n - 1)      (tends to k as n grows)
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from .sensors import Plant
from .stages import STAGE_NAMES, Packet, Stages

K = len(STAGE_NAMES)


@dataclass
class Timing:
    mode: str
    elapsed: float
    events: list        # (reading index, stage index, start s, end s)
    packets: list


def make_packets(n: int, seed: int = 7) -> list:
    plant = Plant(seed)
    packets = []
    while len(packets) < n:
        for dev, raw in plant.sample():
            if len(packets) < n:
                packets.append(Packet(len(packets), dev.machine, dev.spec, raw))
    return packets


def run_sequential(n: int, stage_delay: float = 0.02, seed: int = 7) -> Timing:
    packets = make_packets(n, seed)
    stages = Stages().functions()
    events = []
    t0 = time.perf_counter()
    for i, p in enumerate(packets):
        for s, fn in enumerate(stages):
            start = time.perf_counter() - t0
            fn(p)
            time.sleep(stage_delay)
            events.append((i, s, start, time.perf_counter() - t0))
    return Timing("non-pipelined", time.perf_counter() - t0, events, packets)


def run_pipelined(n: int, stage_delay: float = 0.02, seed: int = 7) -> Timing:
    packets = make_packets(n, seed)
    stages = Stages().functions()
    queues = [queue.Queue() for _ in range(K + 1)]
    events = []
    lock = threading.Lock()
    t0 = time.perf_counter()

    def worker(s: int):
        fn = stages[s]
        while True:
            item = queues[s].get()
            if item is None:                      # end marker: pass it on and stop
                queues[s + 1].put(None)
                return
            i, p = item
            start = time.perf_counter() - t0
            fn(p)
            time.sleep(stage_delay)
            with lock:
                events.append((i, s, start, time.perf_counter() - t0))
            queues[s + 1].put(item)

    threads = [threading.Thread(target=worker, args=(s,), daemon=True) for s in range(K)]
    for t in threads:
        t.start()
    for i, p in enumerate(packets):
        queues[0].put((i, p))
    queues[0].put(None)
    for t in threads:
        t.join()
    events.sort()
    return Timing("pipelined", time.perf_counter() - t0, events, packets)


def ideal(n: int, stage_delay: float, k: int = K) -> dict:
    return {
        "non_pipelined": n * k * stage_delay,
        "pipelined": (k + n - 1) * stage_delay,
        "speedup": n * k / (k + n - 1),
    }


def space_time(n: int, k: int = K) -> list:
    """Space-time diagram of an ideal pipeline: rows are stages, columns are clock cycles."""
    rows = []
    for s in range(k):
        row = {"stage": "%d %s" % (s + 1, STAGE_NAMES[s])}
        for cycle in range(1, k + n):
            reading = cycle - s
            row["C%d" % cycle] = "R%d" % reading if 1 <= reading <= n else ""
        rows.append(row)
    return rows
