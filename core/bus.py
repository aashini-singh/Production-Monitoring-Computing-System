"""Shared data bus with an arbiter (CAPP Unit 1: bus arbitration and its types).

Every sensor wants to put its reading on the one data bus at the same time.
The arbiter decides the order. Three schemes are implemented:

    daisy        daisy chaining: the grant passes down the chain, so the device
                 nearest the arbiter always goes first (fixed priority).
    polling      the arbiter polls device addresses in turn and carries on from
                 where it stopped last time (fair, rotating order).
    independent  independent request: each device has its own request line and
                 the arbiter uses a priority value per device. Here the priority
                 is the device's last status, so alerting sensors go first.
"""
from __future__ import annotations

SCHEMES = ("daisy", "polling", "independent")


class BusArbiter:
    def __init__(self, n_devices: int, scheme: str = "polling"):
        if scheme not in SCHEMES:
            raise ValueError("scheme must be one of %s" % (SCHEMES,))
        self.n = n_devices
        self.scheme = scheme
        self.next_poll = 0
        self.total_wait = [0] * n_devices     # bus cycles each device has waited so far
        self.cycles = 0

    def grant_order(self, requests: list, priority: dict = None) -> list:
        """Order in which the requesting device ids get the bus this cycle."""
        requests = sorted(requests)
        if self.scheme == "daisy":
            order = requests
        elif self.scheme == "polling":
            order = sorted(requests, key=lambda d: (d - self.next_poll) % self.n)
            if order:
                self.next_poll = (order[0] + 1) % self.n
        else:
            priority = priority or {}
            order = sorted(requests, key=lambda d: (-priority.get(d, 0), d))
        for position, dev in enumerate(order):
            self.total_wait[dev] += position
        self.cycles += 1
        return order

    def average_wait(self) -> list:
        return [w / self.cycles if self.cycles else 0.0 for w in self.total_wait]
