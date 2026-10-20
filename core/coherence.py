
"""Unit 4: Cache coherence using a shared bus."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CacheLine:
    state: str = "I"
    value: Optional[int] = None


class CoherenceSimulator:
    """Simulate cache coherence for three CPUs and one memory location."""

    CPUS = ("CPU0", "CPU1", "CPU2")

    VALID_PROTOCOLS = ("VI", "MSI", "MESI", "Dragon")

    def __init__(self, protocol="MSI", initial_value=0):
        if protocol not in self.VALID_PROTOCOLS:
            raise ValueError(
                "Protocol must be VI, MSI, MESI or Dragon"
            )

        self.protocol = protocol
        self.memory = initial_value
        self.caches = {
            cpu: CacheLine() for cpu in self.CPUS
        }
        self.trace = []

    def _record(self, cpu, operation, message):
        self.trace.append({
            "CPU": cpu,
            "Operation": operation,
            "Bus message": message,
            "Memory": self.memory,
            "States": {
                name: line.state
                for name, line in self.caches.items()
            },
            "Values": {
                name: line.value
                for name, line in self.caches.items()
            }
        })

        errors = self.check()
        if errors:
            raise AssertionError("; ".join(errors))

    def check(self):
        """Check stable-state coherence invariants."""
        errors = []
        protocol = self.protocol

        valid = [
            (cpu, line)
            for cpu, line in self.caches.items()
            if line.state != "I"
        ]

        states = {
            "VI": {"I", "V"},
            "MSI": {"I", "S", "M"},
            "MESI": {"I", "S", "E", "M"},
            "Dragon": {"I", "Sc", "Sm", "E", "M"},
        }

        for cpu, line in self.caches.items():
            if line.state not in states[protocol]:
                errors.append(
                    f"Invalid {protocol} state {line.state} at {cpu}"
                )

            if line.state != "I" and line.value is None:
                errors.append(f"Valid cache at {cpu} has no value")

        modified = [
            cpu for cpu, line in valid
            if line.state == "M"
        ]

        if modified and len(valid) > 1:
            errors.append(
                "Modified cache coexists with another valid copy"
            )

        if len(modified) > 1:
            errors.append("Multiple Modified owners")

        if protocol == "VI":
            for cpu, line in valid:
                if line.value != self.memory:
                    errors.append(f"Stale VI cache at {cpu}")

        elif protocol == "MSI":
            # M must be the only valid copy.
            pass

        elif protocol == "MESI":
            exclusive = [
                cpu for cpu, line in valid
                if line.state == "E"
            ]

            if exclusive and len(valid) > 1:
                errors.append(
                    "Exclusive cache coexists with another valid copy"
                )

            if len(exclusive) > 1:
                errors.append("Multiple Exclusive owners")

        elif protocol == "Dragon":
            # Shared copies must agree, including the Sm owner.
            values = {
                line.value for _, line in valid
            }

            if len(values) > 1:
                errors.append("Dragon shared cache values disagree")

            exclusive = [
                cpu for cpu, line in valid
                if line.state == "E"
            ]

            if exclusive and len(valid) > 1:
                errors.append(
                    "Exclusive cache coexists with another valid copy"
                )

        return errors

    def read(self, cpu):
        if cpu not in self.caches:
            raise ValueError(f"Unknown CPU: {cpu}")

        line = self.caches[cpu]

        # Cache hit.
        if line.state != "I":
            self._record(
                cpu, "READ", "Cache hit; no bus transaction"
            )
            return line.value

        sharers = [
            name for name, other in self.caches.items()
            if name != cpu and other.state != "I"
        ]

        if self.protocol == "VI":
            line.state = "V"
            line.value = self.memory
            message = "BusRd: memory supplies block"

        elif self.protocol == "MSI":
            dirty_owner = next(
                (
                    name for name in sharers
                    if self.caches[name].state == "M"
                ),
                None
            )

            if dirty_owner is not None:
                owner_line = self.caches[dirty_owner]
                self.memory = owner_line.value
                owner_line.state = "S"
                message = f"BusRd: {dirty_owner} supplies modified data"
            else:
                message = "BusRd: fetch block"

            line.state = "S"
            line.value = self.memory

            for name in sharers:
                self.caches[name].state = "S"
                self.caches[name].value = self.memory

        elif self.protocol == "MESI":
            dirty_owner = next(
                (
                    name for name in sharers
                    if self.caches[name].state == "M"
                ),
                None
            )

            if dirty_owner is not None:
                self.memory = self.caches[dirty_owner].value
                self.caches[dirty_owner].state = "S"
                line.state = "S"
                line.value = self.memory
                message = f"BusRd: {dirty_owner} supplies modified data"

            elif not sharers:
                line.state = "E"
                line.value = self.memory
                message = "BusRd: memory supplies block; enter E"

            else:
                # An E owner becomes S when another CPU reads.
                for name in sharers:
                    self.caches[name].state = "S"
                    self.caches[name].value = self.memory

                line.state = "S"
                line.value = self.memory
                message = "BusRd: shared copy; enter S"

        else:  # Dragon
            dirty_owner = next(
                (
                    name for name in sharers
                    if self.caches[name].state in ("M", "Sm")
                ),
                None
            )

            if dirty_owner is not None:
                owner_line = self.caches[dirty_owner]
                self.memory = owner_line.value
                owner_line.state = "Sm"
                line.value = owner_line.value
                line.state = "Sc"
                message = f"BusRd: {dirty_owner} supplies shared data"

            elif not sharers:
                line.state = "E"
                line.value = self.memory
                message = "BusRd: memory supplies block; enter E"

            else:
                for name in sharers:
                    if self.caches[name].state == "E":
                        self.caches[name].state = "Sc"

                line.state = "Sc"
                line.value = self.memory
                message = "BusRd: shared copy; enter Sc"

        self._record(cpu, "READ", message)
        return line.value

    def write(self, cpu, value):
        if cpu not in self.caches:
            raise ValueError(f"Unknown CPU: {cpu}")

        line = self.caches[cpu]

        if self.protocol == "VI":
            # Write-through and invalidate other copies.
            self.memory = value

            for name in self.CPUS:
                if name != cpu:
                    self.caches[name] = CacheLine()

            line.state = "V"
            line.value = value
            message = "BusWr: write-through; invalidate other copies"

        elif self.protocol == "MSI":
            if line.state == "M":
                line.value = value
                message = "Write hit in M; no bus transaction"
            else:
                for name in self.CPUS:
                    if name != cpu:
                        self.caches[name] = CacheLine()

                line.state = "M"
                line.value = value
                message = "BusRdX/BusUpgr: invalidate other copies"

        elif self.protocol == "MESI":
            if line.state == "M":
                line.value = value
                message = "Write hit in M; no bus transaction"

            elif line.state == "E":
                line.state = "M"
                line.value = value
                message = "E-to-M: write without bus transaction"

            else:
                for name in self.CPUS:
                    if name != cpu:
                        self.caches[name] = CacheLine()

                line.state = "M"
                line.value = value
                message = "BusRdX/BusUpgr: invalidate other copies"

        else:  # Dragon: write-update rather than invalidating sharers
            if line.state in ("M", "E") and not any(
                other.state != "I"
                for name, other in self.caches.items()
                if name != cpu
            ):
                line.state = "M"
                line.value = value
                message = "Local write; no bus transaction"

            
           
            elif line.state in ("Sc", "Sm"):
                # Update all valid copies and keep one Sm owner.
                for name, other in self.caches.items():
                    if other.state != "I":
                        other.value = value
                        other.state = "Sm" if name == cpu else "Sc"

                line.state = "Sm"
                self.memory = value
                message = "BusUpd: update all shared copies"



            else:
                # I or an E line with other valid copies (defensive case).
                for name, other in self.caches.items():
                    if name != cpu and other.state != "I":
                        other.value = value
                        other.state = "Sc"

                line.state = "Sm" if any(
                    other.state != "I"
                    for name, other in self.caches.items()
                    if name != cpu
                ) else "M"

                line.value = value
                self.memory = value
                message = "BusUpd/Bus ownership: write new value"

        self._record(cpu, "WRITE", message)

    def run_demo(self):
        """Run a repeatable read/write trace."""
        self.trace = []

        self.read("CPU0")
        self.read("CPU1")
        self.write("CPU0", 7)
        self.read("CPU2")
        self.write("CPU1", 9)
        self.read("CPU0")

        return self.trace
