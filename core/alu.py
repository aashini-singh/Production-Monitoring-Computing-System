"""Arithmetic and Logic Unit (CAPP Unit 2).

Everything here works on fixed-width two's-complement words, the way a
hardware ALU does, instead of using Python's * and / operators:

    add / sub / compare      ripple addition with N, Z, C, V flags
    booth_multiply           Booth's algorithm for signed multiplication
    array_multiply           array multiplier (partial products + adder rows)
    restoring_divide         restoring division (unsigned), divide() adds signs
    ieee754_encode/decode    IEEE 754 single-precision floating point

Functions that take trace=True also return the register contents after every
step, which the dashboard shows as a step table.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction


# ---------------------------------------------------------------- helpers
def mask(bits: int) -> int:
    return (1 << bits) - 1


def to_unsigned(x: int, bits: int) -> int:
    return x & mask(bits)


def to_signed(x: int, bits: int) -> int:
    x &= mask(bits)
    return x - (1 << bits) if x >> (bits - 1) else x


def bits_str(x: int, bits: int) -> str:
    return format(x & mask(bits), "0%db" % bits)


def in_range(x: int, bits: int) -> bool:
    return -(1 << (bits - 1)) <= x <= (1 << (bits - 1)) - 1


# ---------------------------------------------------------------- flags
@dataclass(frozen=True)
class Flags:
    N: bool = False   # negative
    Z: bool = False   # zero
    C: bool = False   # carry out
    V: bool = False   # signed overflow

    # signed comparisons after "a - b"
    @property
    def lt(self) -> bool:
        return self.N != self.V

    @property
    def ge(self) -> bool:
        return self.N == self.V

    @property
    def gt(self) -> bool:
        return (not self.Z) and self.N == self.V

    @property
    def le(self) -> bool:
        return self.Z or self.N != self.V

    def __str__(self) -> str:
        return "N=%d Z=%d C=%d V=%d" % (self.N, self.Z, self.C, self.V)


# ---------------------------------------------------------------- add / sub / logic
def add(a: int, b: int, bits: int = 16, carry_in: int = 0):
    """a + b + carry_in on `bits`-wide words. Returns (signed result, Flags)."""
    ua, ub = to_unsigned(a, bits), to_unsigned(b, bits)
    total = ua + ub + carry_in
    res = total & mask(bits)
    sa, sb, sr = ua >> (bits - 1), ub >> (bits - 1), res >> (bits - 1)
    flags = Flags(N=bool(sr), Z=res == 0, C=bool(total >> bits), V=(sa == sb and sr != sa))
    return to_signed(res, bits), flags


def sub(a: int, b: int, bits: int = 16):
    """a - b, done as a + (one's complement of b) + 1."""
    return add(a, ~b, bits, carry_in=1)


def compare(a: int, b: int, bits: int = 16) -> Flags:
    return sub(a, b, bits)[1]


def logic(op: str, a: int, b: int = 0, bits: int = 16) -> int:
    ua, ub = to_unsigned(a, bits), to_unsigned(b, bits)
    if op == "AND":
        r = ua & ub
    elif op == "OR":
        r = ua | ub
    elif op == "XOR":
        r = ua ^ ub
    elif op == "NOT":
        r = ~ua
    elif op == "SHL":
        r = ua << 1
    elif op == "SHR":                      # arithmetic shift right keeps the sign bit
        r = (ua >> 1) | (ua & (1 << (bits - 1)))
    else:
        raise ValueError("unknown logic operation: %s" % op)
    return to_signed(r, bits)


# ---------------------------------------------------------------- Booth's algorithm
def booth_multiply(multiplicand: int, multiplier: int, bits: int = 16, trace: bool = False):
    """Signed multiplication with Booth's algorithm.

    Registers: A (accumulator), Q (multiplier), Q-1 (extra bit), M (multiplicand).
    Each cycle looks at the pair (Q0, Q-1):
        1 0 -> A = A - M        0 1 -> A = A + M        0 0 / 1 1 -> nothing
    then shifts A, Q, Q-1 right arithmetically. After `bits` cycles the
    2*bits-wide product sits in A:Q.

    A is kept one bit wider than the operands so the most negative
    multiplicand (-2^(bits-1)) cannot overflow it.

    Returns (product, steps).
    """
    if not (in_range(multiplicand, bits) and in_range(multiplier, bits)):
        raise ValueError("operands must fit in %d-bit signed words" % bits)
    wide = bits + 1
    M = to_unsigned(multiplicand, wide)
    A = 0
    Q = to_unsigned(multiplier, bits)
    q_1 = 0
    steps = []
    if trace:
        steps.append({"cycle": 0, "Q0 Q-1": "", "operation": "initial values",
                      "A": bits_str(A, bits), "Q": bits_str(Q, bits), "Q-1": q_1})
    for cycle in range(1, bits + 1):
        q0 = Q & 1
        if q0 == 1 and q_1 == 0:
            A = (A - M) & mask(wide)
            op = "A = A - M, then shift right"
        elif q0 == 0 and q_1 == 1:
            A = (A + M) & mask(wide)
            op = "A = A + M, then shift right"
        else:
            op = "shift right only"
        pair = "%d %d" % (q0, q_1)
        q_1 = q0
        Q = (Q >> 1) | ((A & 1) << (bits - 1))
        A = (A >> 1) | (A & (1 << (wide - 1)))
        if trace:
            steps.append({"cycle": cycle, "Q0 Q-1": pair, "operation": op,
                          "A": bits_str(A, bits), "Q": bits_str(Q, bits), "Q-1": q_1})
    product = to_signed(((A & mask(bits)) << bits) | Q, 2 * bits)
    return product, steps


# ---------------------------------------------------------------- array multiplier
def array_multiply(a: int, b: int, bits: int = 8):
    """Unsigned array multiplier.

    Row i of AND gates forms the partial product (a AND b_i) shifted left by i;
    rows of adders then sum the partial products. Returns (product, rows) where
    rows lists each partial product and the running sum.
    """
    if not (0 <= a <= mask(bits) and 0 <= b <= mask(bits)):
        raise ValueError("operands must be unsigned %d-bit values" % bits)
    total = 0
    rows = []
    for i in range(bits):
        b_i = (b >> i) & 1
        partial = (a if b_i else 0) << i
        total, _ = add(total, partial, bits=2 * bits + 1)
        rows.append({"row": i, "b_i": b_i,
                     "partial product": bits_str(partial, 2 * bits),
                     "running sum": bits_str(total, 2 * bits)})
    return total, rows


# ---------------------------------------------------------------- division
def restoring_divide(dividend: int, divisor: int, bits: int = 16, trace: bool = False):
    """Unsigned restoring division.

    Registers: A (remainder, starts at 0), Q (dividend, becomes quotient), M (divisor).
    Each cycle: shift A:Q left, A = A - M; if A went negative, restore it
    (A = A + M) and set Q0 = 0, otherwise set Q0 = 1.

    Returns (quotient, remainder, steps).
    """
    if divisor == 0:
        raise ZeroDivisionError("division by zero")
    if not (0 <= dividend <= mask(bits) and 0 < divisor <= mask(bits)):
        raise ValueError("operands must be unsigned %d-bit values" % bits)
    A, Q, M = 0, dividend, divisor
    steps = []
    if trace:
        steps.append({"cycle": 0, "operation": "initial values",
                      "A": bits_str(A, bits + 1), "Q": bits_str(Q, bits)})
    for cycle in range(1, bits + 1):
        A = (A << 1) | (Q >> (bits - 1))
        Q = (Q << 1) & mask(bits)
        A -= M
        if A < 0:
            A += M
            op = "shift left, A - M < 0: restore, Q0 = 0"
        else:
            Q |= 1
            op = "shift left, A - M >= 0: keep, Q0 = 1"
        if trace:
            steps.append({"cycle": cycle, "operation": op,
                          "A": bits_str(A, bits + 1), "Q": bits_str(Q, bits)})
    return Q, A, steps


def divide(dividend: int, divisor: int, bits: int = 16, trace: bool = False):
    """Signed division: restoring division on magnitudes, then fix the signs.

    The quotient is truncated towards zero and the remainder takes the sign of
    the dividend. Returns (quotient, remainder, steps).
    """
    q, r, steps = restoring_divide(abs(dividend), abs(divisor), bits, trace)
    if (dividend < 0) != (divisor < 0):
        q = -q
    if dividend < 0:
        r = -r
    return q, r, steps


# ---------------------------------------------------------------- IEEE 754
@dataclass(frozen=True)
class IEEE754:
    value: float
    sign: int
    exponent: int        # biased, 8 bits
    mantissa: int        # 23 bits
    notes: tuple = field(default_factory=tuple)

    @property
    def word(self) -> int:
        return (self.sign << 31) | (self.exponent << 23) | self.mantissa

    @property
    def hex(self) -> str:
        return "0x%08X" % self.word

    @property
    def bit_fields(self) -> str:
        return "%d | %s | %s" % (self.sign, bits_str(self.exponent, 8), bits_str(self.mantissa, 23))


def ieee754_encode(x: float) -> IEEE754:
    """Convert a number to IEEE 754 single precision (1 sign, 8 exponent, 23 mantissa bits).

    Done by hand (normalise to 1.f x 2^e, bias the exponent by 127, round the
    fraction to 23 bits, ties to even) rather than with the struct module.
    """
    x = float(x)
    if math.isnan(x):
        return IEEE754(x, 0, 255, 1 << 22, ("NaN: exponent all ones, mantissa non-zero",))
    sign = 1 if math.copysign(1.0, x) < 0 else 0
    if math.isinf(x):
        return IEEE754(x, sign, 255, 0, ("infinity: exponent all ones, mantissa zero",))
    if x == 0:
        return IEEE754(x, sign, 0, 0, ("zero: exponent and mantissa all zero",))

    f = Fraction(abs(x))
    e = f.numerator.bit_length() - f.denominator.bit_length()
    if Fraction(2) ** e > f:
        e -= 1                                   # now 2^e <= f < 2^(e+1)
    notes = ["sign bit = %d (%s)" % (sign, "negative" if sign else "positive")]

    if e < -126:                                 # too small to normalise: subnormal
        mant = round(f / Fraction(2) ** -149)
        if mant == 1 << 23:
            return IEEE754(x, sign, 1, 0, tuple(notes + ["rounds up to the smallest normal number"]))
        return IEEE754(x, sign, 0, mant, tuple(notes + ["subnormal: exponent field 0, no hidden 1"]))

    mant = round((f / Fraction(2) ** e - 1) * (1 << 23))
    if mant == 1 << 23:                          # rounding carried into the hidden bit
        mant, e = 0, e + 1
    if e > 127:
        return IEEE754(x, sign, 255, 0, tuple(notes + ["too large: becomes infinity"]))

    whole = int(f)
    frac = f - whole
    frac_bits = ""
    while frac and len(frac_bits) < 12:
        frac *= 2
        frac_bits += "1" if frac >= 1 else "0"
        frac -= int(frac)
    notes.append("magnitude in binary = %s.%s%s" % (bin(whole)[2:], frac_bits or "0", "..." if frac else ""))
    notes.append("normalised = 1.%s x 2^%d" % (bits_str(mant, 23).rstrip("0") or "0", e))
    notes.append("biased exponent = %d + 127 = %d = %s" % (e, e + 127, bits_str(e + 127, 8)))
    notes.append("mantissa (23 bits after the hidden 1) = %s" % bits_str(mant, 23))
    return IEEE754(x, sign, e + 127, mant, tuple(notes))


def ieee754_decode(word: int) -> float:
    sign = -1.0 if (word >> 31) & 1 else 1.0
    exponent = (word >> 23) & 0xFF
    mantissa = word & 0x7FFFFF
    if exponent == 255:
        return float("nan") if mantissa else sign * float("inf")
    if exponent == 0:
        return sign * mantissa * 2.0 ** -149
    return sign * (1 + mantissa / float(1 << 23)) * 2.0 ** (exponent - 127)
