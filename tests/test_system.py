import os
import random
import tempfile
import unittest

from config import ADC_MAX, SENSORS, SENSOR_BY_KEY, MACHINES
from core import firmware, pipeline, parallel
from core.bus import BusArbiter
from core.cpu import CPU, Instr, Mode, Op, decode, encode
from core.monitor import Monitor
from core.stages import Packet, Stages


class InstructionFormatTests(unittest.TestCase):
    def test_encode_decode_round_trip(self):
        rng = random.Random(5)
        for _ in range(2000):
            ins = Instr(rng.choice(list(Op)), rng.randint(0, 7), rng.randint(0, 7),
                        rng.choice(list(Mode)), rng.randint(-32768, 32767))
            self.assertEqual(decode(encode(ins)), ins)

    def test_program_assembles(self):
        self.assertEqual(firmware.PROGRAM.labels["COMPUTE"], 0)
        self.assertEqual(len(firmware.PROGRAM.words), len(firmware.PROGRAM.listing))


class CpuAgainstReferenceTests(unittest.TestCase):
    def test_program_matches_plain_python(self):
        rng = random.Random(6)
        for spec in SENSORS:
            stages, history = Stages(), []
            for seq in range(400):
                raw = rng.randint(0, ADC_MAX)
                p = stages.run_all(Packet(seq, MACHINES[0], spec, raw))
                value, avg, status = firmware.reference(raw, spec, history)
                self.assertEqual((p.value_t, p.avg_t, p.status),
                                 (value, avg, ("NORMAL", "WARNING", "CRITICAL")[status]), (spec.key, raw))

    def test_limits(self):
        temp = SENSOR_BY_KEY["temp"]         # warning 75, critical 85, span 150
        rate = SENSOR_BY_KEY["rate"]         # warning <= 45, critical <= 30, span 120
        def status(spec, value):
            raw = round(value / spec.span * ADC_MAX)
            return Stages().run_all(Packet(0, MACHINES[0], spec, raw)).status
        self.assertEqual(status(temp, 62), "NORMAL")
        self.assertEqual(status(temp, 80), "WARNING")
        self.assertEqual(status(temp, 90), "CRITICAL")
        self.assertEqual(status(rate, 60), "NORMAL")
        self.assertEqual(status(rate, 40), "WARNING")
        self.assertEqual(status(rate, 20), "CRITICAL")

    def test_invalid_reading_is_rejected(self):
        p = Stages().run_all(Packet(0, MACHINES[0], SENSORS[0], 4095))
        self.assertFalse(p.valid)
        self.assertEqual(p.status, "INVALID")
        self.assertIsNone(p.value)

    def test_trace_lists_fetch_micro_operations(self):
        stages = Stages()
        p = stages.validate(stages.acquire(Packet(0, MACHINES[0], SENSORS[0], 563)))
        p, trace = stages.compute(p, trace=True)
        self.assertEqual(trace[0]["instruction"].split()[0], "IN")
        self.assertEqual(trace[0]["micro-operations"][0], "T0: MAR <- PC")
        self.assertEqual(trace[-1]["instruction"], "HALT")
        self.assertEqual(p.value_t, 563 * 1500 // 1023)

    def test_stack_returns_to_caller(self):
        cpu = CPU()
        mem = firmware.new_memory(SENSORS[0])
        out = cpu.run(firmware.PROGRAM, "DETECT", mem, {1: 900})
        self.assertEqual(out.outputs[0], 2)
        self.assertEqual(cpu.SP, 16)


class BusTests(unittest.TestCase):
    def test_daisy_is_fixed_priority(self):
        bus = BusArbiter(4, "daisy")
        self.assertEqual(bus.grant_order([3, 1, 0, 2]), [0, 1, 2, 3])
        self.assertEqual(bus.grant_order([3, 1, 0, 2]), [0, 1, 2, 3])

    def test_polling_rotates(self):
        bus = BusArbiter(4, "polling")
        firsts = [bus.grant_order([0, 1, 2, 3])[0] for _ in range(4)]
        self.assertEqual(firsts, [0, 1, 2, 3])
        self.assertEqual(len(set(bus.average_wait())), 1)

    def test_independent_request_uses_priority(self):
        bus = BusArbiter(4, "independent")
        self.assertEqual(bus.grant_order([0, 1, 2, 3], {2: 3, 1: 2}), [2, 1, 0, 3])


class MonitorTests(unittest.TestCase):
    def test_fault_raises_alert_and_writes_log(self):
        with tempfile.TemporaryDirectory() as folder:
            mon = Monitor(seed=1, log_folder=folder)
            for _ in range(10):
                mon.tick()
            self.assertEqual(mon.machine_status("M1"), "NORMAL")
            mon.plant.inject("M1", "Overheat")
            for _ in range(25):
                mon.tick()
            self.assertEqual(mon.machine_status("M1"), "CRITICAL")
            self.assertEqual(mon.machine_status("M2"), "NORMAL")
            mon.plant.clear()
            for _ in range(40):
                mon.tick()
            self.assertEqual(mon.machine_status("M1"), "NORMAL")
            self.assertTrue(any(a["to_status"] == "CRITICAL" for a in mon.alerts))
            mon.log.close()
            with open(os.path.join(folder, "readings_log.csv")) as f:
                self.assertEqual(len(f.readlines()), 1 + 75 * 12)

    def test_dropout_is_flagged_invalid(self):
        mon = Monitor(seed=2)
        mon.plant.inject("M2", "Sensor dropout")
        mon.tick()
        self.assertEqual(mon.status[("M2", "temp")], "INVALID")
        self.assertEqual(mon.rejected, 1)


class PipelineTests(unittest.TestCase):
    def test_same_results_and_faster(self):
        n, delay = 12, 0.01
        seq = pipeline.run_sequential(n, delay)
        pipe = pipeline.run_pipelined(n, delay)
        self.assertEqual([(p.value_t, p.avg_t, p.status) for p in seq.packets],
                         [(p.value_t, p.avg_t, p.status) for p in pipe.packets])
        self.assertEqual(len(pipe.events), n * pipeline.K)
        self.assertGreater(seq.elapsed / pipe.elapsed, 2.0)

    def test_ideal_formula(self):
        self.assertAlmostEqual(pipeline.ideal(20, 0.01)["speedup"], 100 / 24)
        self.assertEqual(pipeline.space_time(3)[2]["C3"], "R1")


class ParallelTests(unittest.TestCase):
    def test_mimd_faster_than_sisd(self):
        self.assertLess(parallel.run_mimd(4, 3, 0.005), parallel.run_sisd(4, 3, 0.005))

    def test_simd_same_answer(self):
        self.assertTrue(parallel.simd_demo(20000)["same answer"])


if __name__ == "__main__":
    unittest.main()
