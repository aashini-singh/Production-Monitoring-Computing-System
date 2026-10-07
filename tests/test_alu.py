import math
import random
import struct
import unittest

from core import alu


class BoothTests(unittest.TestCase):
    def test_every_6_bit_pair(self):
        for a in range(-32, 32):
            for b in range(-32, 32):
                self.assertEqual(alu.booth_multiply(a, b, bits=6)[0], a * b, (a, b))

    def test_random_16_bit(self):
        rng = random.Random(1)
        cases = [(rng.randint(-32768, 32767), rng.randint(-32768, 32767)) for _ in range(3000)]
        cases += [(-32768, -32768), (-32768, 32767), (32767, 32767), (0, -32768), (-32768, 1), (1023, 1500)]
        for a, b in cases:
            self.assertEqual(alu.booth_multiply(a, b)[0], a * b, (a, b))

    def test_trace_has_one_row_per_cycle(self):
        product, steps = alu.booth_multiply(7, -3, bits=4, trace=True)
        self.assertEqual(product, -21)
        self.assertEqual(len(steps), 5)

    def test_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            alu.booth_multiply(40000, 2)


class ArrayMultiplierTests(unittest.TestCase):
    def test_every_5_bit_pair(self):
        for a in range(32):
            for b in range(32):
                self.assertEqual(alu.array_multiply(a, b, bits=5)[0], a * b)


class DivisionTests(unittest.TestCase):
    def test_every_6_bit_pair(self):
        for a in range(64):
            for b in range(1, 64):
                q, r, _ = alu.restoring_divide(a, b, bits=6)
                self.assertEqual((q, r), divmod(a, b))

    def test_signed_random(self):
        rng = random.Random(2)
        for _ in range(3000):
            a, b = rng.randint(-32767, 32767), rng.randint(-32767, 32767) or 5
            q, r, _ = alu.divide(a, b)
            self.assertEqual(q, int(a / b) if abs(a) < 2 ** 50 else None)
            self.assertEqual(q * b + r, a)
            self.assertLess(abs(r), abs(b))

    def test_32_bit_dividend(self):
        q, r, _ = alu.divide(1023 * 1500, 1023, bits=32)
        self.assertEqual((q, r), (1500, 0))

    def test_divide_by_zero(self):
        with self.assertRaises(ZeroDivisionError):
            alu.restoring_divide(5, 0)


class AddSubTests(unittest.TestCase):
    def test_results_and_signed_compare(self):
        rng = random.Random(3)
        for _ in range(5000):
            a, b = rng.randint(-32768, 32767), rng.randint(-32768, 32767)
            self.assertEqual(alu.add(a, b)[0], alu.to_signed(a + b, 16))
            self.assertEqual(alu.sub(a, b)[0], alu.to_signed(a - b, 16))
            f = alu.compare(a, b)
            self.assertEqual((f.lt, f.ge, f.gt, f.le, f.Z), (a < b, a >= b, a > b, a <= b, a == b))

    def test_overflow_flag(self):
        self.assertTrue(alu.add(32767, 1)[1].V)
        self.assertTrue(alu.sub(-32768, 1)[1].V)
        self.assertFalse(alu.add(100, 200)[1].V)

    def test_logic(self):
        self.assertEqual(alu.logic("AND", 0b1100, 0b1010), 0b1000)
        self.assertEqual(alu.logic("OR", 0b1100, 0b1010), 0b1110)
        self.assertEqual(alu.logic("XOR", 0b1100, 0b1010), 0b0110)
        self.assertEqual(alu.logic("NOT", 0), -1)
        self.assertEqual(alu.logic("SHR", -8), -4)
        self.assertEqual(alu.logic("SHL", 3), 6)


class Ieee754Tests(unittest.TestCase):
    @staticmethod
    def expected(x):
        return struct.unpack(">I", struct.pack(">f", x))[0]

    def test_known_values(self):
        self.assertEqual(alu.ieee754_encode(82.5).hex, "0x42A50000")
        self.assertEqual(alu.ieee754_encode(-0.15625).hex, "0xBE200000")
        self.assertEqual(alu.ieee754_encode(1.0).hex, "0x3F800000")
        self.assertEqual(alu.ieee754_encode(0.0).word, 0)

    def test_matches_struct(self):
        rng = random.Random(4)
        values = [rng.uniform(-200, 200) for _ in range(3000)]
        values += [rng.uniform(-1, 1) * 10 ** rng.randint(-44, 38) for _ in range(3000)]
        values += [0.1, 62.4, 1e-45, 1.1754942e-38, 3.4028234e38, 16777217.0, -0.0]
        for v in values:
            self.assertEqual(alu.ieee754_encode(v).word, self.expected(v), v)

    def test_special_values(self):
        self.assertEqual(alu.ieee754_encode(float("inf")).hex, "0x7F800000")
        self.assertEqual(alu.ieee754_encode(float("-inf")).hex, "0xFF800000")
        self.assertTrue(math.isnan(alu.ieee754_decode(alu.ieee754_encode(float("nan")).word)))

    def test_round_trip(self):
        for v in (82.5, -3.75, 0.5, 1234.0):
            self.assertEqual(alu.ieee754_decode(alu.ieee754_encode(v).word), v)


if __name__ == "__main__":
    unittest.main()
