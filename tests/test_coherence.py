
import unittest

from core.coherence import CoherenceSimulator


class TestCoherenceSimulator(unittest.TestCase):

    def test_msi_read_shares_cache_line(self):
        sim = CoherenceSimulator("MSI")
        sim.read("CPU0")
        sim.read("CPU1")

        self.assertEqual(sim.caches["CPU0"].state, "S")
        self.assertEqual(sim.caches["CPU1"].state, "S")
        self.assertEqual(sim.check(), [])

    def test_msi_write_invalidates_other_caches(self):
        sim = CoherenceSimulator("MSI")
        sim.read("CPU0")
        sim.read("CPU1")
        sim.write("CPU0", 7)

        self.assertEqual(sim.caches["CPU0"].state, "M")
        self.assertEqual(sim.caches["CPU1"].state, "I")
        self.assertEqual(sim.check(), [])

    def test_msi_modified_owner_supplies_latest_value(self):
        sim = CoherenceSimulator("MSI")
        sim.read("CPU0")
        sim.write("CPU0", 25)
        value = sim.read("CPU1")

        self.assertEqual(value, 25)
        self.assertEqual(sim.caches["CPU0"].state, "S")
        self.assertEqual(sim.caches["CPU1"].state, "S")
        self.assertEqual(sim.memory, 25)

    def test_vi_write_updates_memory_and_invalidates(self):
        sim = CoherenceSimulator("VI")
        sim.read("CPU0")
        sim.read("CPU1")
        sim.write("CPU0", 42)

        self.assertEqual(sim.memory, 42)
        self.assertEqual(sim.caches["CPU0"].state, "V")
        self.assertEqual(sim.caches["CPU1"].state, "I")
        self.assertEqual(sim.check(), [])

    def test_demo_finishes_without_invariant_errors(self):
        for protocol in ("VI", "MSI"):
            with self.subTest(protocol=protocol):
                sim = CoherenceSimulator(protocol)
                trace = sim.run_demo()

                self.assertEqual(len(trace), 6)
                self.assertEqual(sim.check(), [])

    def test_invalid_cpu_is_rejected(self):
        sim = CoherenceSimulator("MSI")

        with self.assertRaises(ValueError):
            sim.read("CPU5")

    
    def test_mesi_read_exclusive_then_shared(self):
        sim = CoherenceSimulator("MESI")

        sim.read("CPU0")
        self.assertEqual(sim.caches["CPU0"].state, "E")

        sim.read("CPU1")
        self.assertEqual(sim.caches["CPU0"].state, "S")
        self.assertEqual(sim.caches["CPU1"].state, "S")
        self.assertEqual(sim.check(), [])

    def test_mesi_exclusive_write_needs_no_bus_transaction(self):
        sim = CoherenceSimulator("MESI")
        sim.read("CPU0")

        sim.write("CPU0", 15)

        self.assertEqual(sim.caches["CPU0"].state, "M")
        self.assertEqual(
            sim.trace[-1]["Bus message"],
            "E-to-M: write without bus transaction"
        )
        self.assertEqual(sim.check(), [])

    def test_dragon_shared_write_updates_other_caches(self):
        sim = CoherenceSimulator("Dragon")

        sim.read("CPU0")
        sim.read("CPU1")
        sim.write("CPU0", 7)

        self.assertEqual(sim.caches["CPU0"].state, "Sm")
        self.assertEqual(sim.caches["CPU1"].state, "Sc")
        self.assertEqual(sim.caches["CPU1"].value, 7)
        self.assertEqual(sim.check(), [])

    def test_dragon_demo_finishes(self):
        sim = CoherenceSimulator("Dragon")
        trace = sim.run_demo()

        self.assertEqual(len(trace), 6)
        self.assertEqual(sim.check(), [])
        self.assertEqual(
            len({
                cpu for cpu, line in sim.caches.items()
                if line.state == "Sm"
            }),
            1
        )



if __name__ == "__main__":
    unittest.main()
