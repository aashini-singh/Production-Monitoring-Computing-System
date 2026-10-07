"""A small 16-bit processor (CAPP Units 1 and 3).

Unit 1: general registers R0-R7, PC, IR, MAR, MBR, a register stack with SP,
        data memory, four addressing modes, input/output ports.
Unit 3: 32-bit instruction format, fetch-decode-execute cycle, micro-operations,
        program control (branches, CALL/RET) and a microprogrammed control unit:
        every instruction is a list of micro-operations held in a control store.

Instruction format (32 bits):

    31      26 25  23 22  20 19 18 17 16 15              0
    | opcode  |  Ra  |  Rb  | mode | 0 0 |    operand     |

Addressing modes: REG (operand is Rb), IMM (operand is the value),
DIR (operand is a memory address), IDX (address = operand + Rb).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum

from . import alu

WORD = 16
STACK_WORDS = 16


class Op(IntEnum):
    NOP = 0
    IN = 1
    OUT = 2
    LOAD = 3
    STORE = 4
    ADD = 5
    SUB = 6
    MUL = 7
    DIVL = 8
    DIV = 9
    CMP = 10
    INC = 11
    JMP = 12
    BEQ = 13
    BNE = 14
    BLT = 15
    BGE = 16
    BGT = 17
    BLE = 18
    CALL = 19
    RET = 20
    HALT = 21


class Mode(IntEnum):
    REG = 0
    IMM = 1
    DIR = 2
    IDX = 3


INSTRUCTION_TYPE = {
    Op.NOP: "control", Op.HALT: "control",
    Op.IN: "input/output", Op.OUT: "input/output",
    Op.LOAD: "data transfer", Op.STORE: "data transfer",
    Op.ADD: "arithmetic", Op.SUB: "arithmetic", Op.MUL: "arithmetic",
    Op.DIVL: "arithmetic", Op.DIV: "arithmetic", Op.CMP: "arithmetic", Op.INC: "arithmetic",
    Op.JMP: "program control", Op.BEQ: "program control", Op.BNE: "program control",
    Op.BLT: "program control", Op.BGE: "program control", Op.BGT: "program control",
    Op.BLE: "program control", Op.CALL: "program control", Op.RET: "program control",
}

NEEDS_SOURCE = {Op.LOAD, Op.ADD, Op.SUB, Op.MUL, Op.DIVL, Op.DIV, Op.CMP}
JUMPS = {Op.JMP, Op.BEQ, Op.BNE, Op.BLT, Op.BGE, Op.BGT, Op.BLE, Op.CALL}
BRANCH_TEST = {
    Op.BEQ: ("Z = 1", lambda f: f.Z), Op.BNE: ("Z = 0", lambda f: not f.Z),
    Op.BLT: ("N != V", lambda f: f.lt), Op.BGE: ("N = V", lambda f: f.ge),
    Op.BGT: ("Z = 0 and N = V", lambda f: f.gt), Op.BLE: ("Z = 1 or N != V", lambda f: f.le),
}


# ---------------------------------------------------------------- instruction format
@dataclass(frozen=True)
class Instr:
    op: Op
    ra: int = 0
    rb: int = 0
    mode: Mode = Mode.IMM
    operand: int = 0


def encode(i: Instr) -> int:
    return ((int(i.op) << 26) | (i.ra << 23) | (i.rb << 20) | (int(i.mode) << 18)
            | alu.to_unsigned(i.operand, 16))


def decode(word: int) -> Instr:
    return Instr(Op((word >> 26) & 0x3F), (word >> 23) & 7, (word >> 20) & 7,
                 Mode((word >> 18) & 3), alu.to_signed(word & 0xFFFF, 16))


# ---------------------------------------------------------------- assembler
@dataclass
class Program:
    words: list
    labels: dict
    listing: list          # source text of each instruction, by address
    symbols: dict

    def label_at(self, addr: int) -> str:
        for name, a in self.labels.items():
            if a == addr:
                return name
        return ""


_REG = re.compile(r"^R([0-7])$")
_IDX = re.compile(r"^(\w+)\(R([0-7])\)$")


def assemble(source: str, symbols: dict) -> Program:
    """Two-pass assembler: pass 1 collects labels, pass 2 encodes instructions."""
    lines = []
    labels = {}
    for raw in source.splitlines():
        text = raw.split(";")[0].strip()
        if not text:
            continue
        if ":" in text:
            label, text = text.split(":", 1)
            labels[label.strip()] = len(lines)
            text = text.strip()
            if not text:
                continue
        lines.append(text)

    def number(tok: str) -> int:
        if tok in symbols:
            return symbols[tok]
        return int(tok, 0)

    words, listing = [], []
    for text in lines:
        parts = text.replace(",", " ").split()
        op = Op[parts[0].upper()]
        args = parts[1:]
        if op in (Op.NOP, Op.RET, Op.HALT):
            ins = Instr(op)
        elif op in JUMPS:
            ins = Instr(op, mode=Mode.IMM, operand=labels[args[0]])
        elif op == Op.INC:
            ins = Instr(op, ra=int(_REG.match(args[0]).group(1)), mode=Mode.REG)
        else:
            ra = int(_REG.match(args[0]).group(1))
            src = args[1]
            if _REG.match(src):
                ins = Instr(op, ra, int(_REG.match(src).group(1)), Mode.REG)
            elif src.startswith("#"):
                ins = Instr(op, ra, 0, Mode.IMM, number(src[1:]))
            elif _IDX.match(src):
                m = _IDX.match(src)
                ins = Instr(op, ra, int(m.group(2)), Mode.IDX, number(m.group(1)))
            else:
                ins = Instr(op, ra, 0, Mode.DIR, number(src))
        words.append(encode(ins))
        listing.append(" ".join([parts[0].upper().ljust(5), ", ".join(args)]).strip())
    return Program(words, labels, listing, dict(symbols))


# ---------------------------------------------------------------- control store
# Each micro-operation is (register-transfer text, action). The action is what
# the control signals of that step do to the datapath.
def _u_mar_pc(c):
    c.MAR = c.PC


def _u_fetch(c):
    c.MBR = c.program.words[c.MAR]
    c.PC += 1


def _u_ir(c):
    c.IR = c.MBR
    c.dec = decode(c.IR)


FETCH = [
    ("MAR <- PC", _u_mar_pc),
    ("MBR <- PM[MAR], PC <- PC + 1", _u_fetch),
    ("IR <- MBR, decode", _u_ir),
]


def _u_tmp_reg(c):
    c.TMP = c.R[c.dec.rb]


def _u_tmp_imm(c):
    c.TMP = c.dec.operand


def _u_mar_dir(c):
    c.MAR = c.dec.operand


def _u_mar_idx(c):
    c.MAR = c.dec.operand + c.R[c.dec.rb]


def _u_read(c):
    c.MBR = c.mem[c.MAR]


def _u_tmp_mbr(c):
    c.TMP = c.MBR


# source-operand micro-routines, one per addressing mode
OPERAND = {
    Mode.REG: [("TMP <- R[b]", _u_tmp_reg)],
    Mode.IMM: [("TMP <- IR[15:0]", _u_tmp_imm)],
    Mode.DIR: [("MAR <- IR[15:0]", _u_mar_dir), ("MBR <- M[MAR]", _u_read), ("TMP <- MBR", _u_tmp_mbr)],
    Mode.IDX: [("MAR <- IR[15:0] + R[b]", _u_mar_idx), ("MBR <- M[MAR]", _u_read), ("TMP <- MBR", _u_tmp_mbr)],
}
# effective-address micro-routines for STORE
ADDRESS = {
    Mode.DIR: [("MAR <- IR[15:0]", _u_mar_dir)],
    Mode.IDX: [("MAR <- IR[15:0] + R[b]", _u_mar_idx)],
}


def _x_in(c):
    c.R[c.dec.ra] = alu.to_signed(c.inputs[c.dec.operand], WORD)


def _x_out(c):
    c.outputs[c.dec.operand] = c.R[c.dec.ra]


def _x_load(c):
    c.R[c.dec.ra] = c.TMP


def _x_mbr_ra(c):
    c.MBR = c.R[c.dec.ra]


def _x_write(c):
    c.mem[c.MAR] = c.MBR


def _x_add(c):
    c.R[c.dec.ra], c.flags = alu.add(c.R[c.dec.ra], c.TMP, WORD)


def _x_sub(c):
    c.R[c.dec.ra], c.flags = alu.sub(c.R[c.dec.ra], c.TMP, WORD)


def _x_cmp(c):
    c.flags = alu.compare(c.R[c.dec.ra], c.TMP, WORD)


def _x_inc(c):
    c.R[c.dec.ra], c.flags = alu.add(c.R[c.dec.ra], 1, WORD)


def _x_mul(c):
    product, _ = alu.booth_multiply(c.R[c.dec.ra], c.TMP, WORD)
    c.HI = alu.to_signed(product >> WORD, WORD)
    c.LO = alu.to_signed(product, WORD)
    c.muls += 1


def _x_divl(c):
    dividend = (c.HI << WORD) | alu.to_unsigned(c.LO, WORD)
    q, r, _ = alu.divide(dividend, c.TMP, 2 * WORD)
    c.flags = alu.Flags(N=q < 0, Z=q == 0, V=not alu.in_range(q, WORD))
    c.LO, c.HI = alu.to_signed(q, WORD), alu.to_signed(r, WORD)
    c.divs += 1


def _x_div(c):
    q, r, _ = alu.divide(c.R[c.dec.ra], c.TMP, WORD)
    c.flags = alu.Flags(N=q < 0, Z=q == 0)
    c.LO, c.HI = q, r
    c.divs += 1


def _x_ra_lo(c):
    c.R[c.dec.ra] = c.LO


def _x_jump(c):
    c.PC = c.dec.operand


def _x_branch(c):
    if BRANCH_TEST[c.dec.op][1](c.flags):
        c.PC = c.dec.operand


def _x_push_sp(c):
    c.SP -= 1


def _x_push_pc(c):
    c.stack[c.SP] = c.PC


def _x_pop_pc(c):
    c.PC = c.stack[c.SP]


def _x_pop_sp(c):
    c.SP += 1


def _x_halt(c):
    c.halted = True


EXECUTE = {
    Op.NOP: [],
    Op.IN: [("R[a] <- INPUT[port]", _x_in)],
    Op.OUT: [("OUTPUT[port] <- R[a]", _x_out)],
    Op.LOAD: [("R[a] <- TMP", _x_load)],
    Op.STORE: [("MBR <- R[a]", _x_mbr_ra), ("M[MAR] <- MBR", _x_write)],
    Op.ADD: [("R[a] <- R[a] + TMP, set flags", _x_add)],
    Op.SUB: [("R[a] <- R[a] - TMP, set flags", _x_sub)],
    Op.CMP: [("flags <- R[a] - TMP", _x_cmp)],
    Op.INC: [("R[a] <- R[a] + 1", _x_inc)],
    Op.MUL: [("HI:LO <- R[a] x TMP (Booth)", _x_mul), ("R[a] <- LO", _x_ra_lo)],
    Op.DIVL: [("LO <- HI:LO / TMP, HI <- remainder (restoring)", _x_divl), ("R[a] <- LO", _x_ra_lo)],
    Op.DIV: [("LO <- R[a] / TMP, HI <- remainder (restoring)", _x_div), ("R[a] <- LO", _x_ra_lo)],
    Op.JMP: [("PC <- IR[15:0]", _x_jump)],
    Op.CALL: [("SP <- SP - 1", _x_push_sp), ("STACK[SP] <- PC", _x_push_pc), ("PC <- IR[15:0]", _x_jump)],
    Op.RET: [("PC <- STACK[SP]", _x_pop_pc), ("SP <- SP + 1", _x_pop_sp)],
    Op.HALT: [("halt", _x_halt)],
}
for _op, (_cond, _) in BRANCH_TEST.items():
    EXECUTE[_op] = [("if %s then PC <- IR[15:0]" % _cond, _x_branch)]


def microroutine(ins: Instr) -> list:
    """The micro-operations that follow the fetch for one decoded instruction."""
    steps = []
    if ins.op in NEEDS_SOURCE:
        steps += OPERAND[ins.mode]
    elif ins.op == Op.STORE:
        steps += ADDRESS[ins.mode]
    return steps + EXECUTE[ins.op]


def control_store() -> dict:
    """Readable copy of the control store, for the dashboard."""
    return {
        "FETCH": [t for t, _ in FETCH],
        "OPERAND": {m.name: [t for t, _ in steps] for m, steps in OPERAND.items()},
        "EXECUTE": {op.name: [t for t, _ in steps] for op, steps in EXECUTE.items()},
    }


# ---------------------------------------------------------------- processor
@dataclass
class RunResult:
    outputs: dict
    instructions: int
    micro_ops: int
    multiplies: int
    divides: int
    trace: list = field(default_factory=list)


class CPU:
    def __init__(self, name: str = "CPU"):
        self.name = name
        self.R = [0] * 8
        self.PC = self.IR = self.MAR = self.MBR = self.TMP = self.HI = self.LO = 0
        self.SP = STACK_WORDS
        self.stack = [0] * STACK_WORDS
        self.flags = alu.Flags()
        self.halted = False
        self.dec = Instr(Op.NOP)
        self.program = None
        self.mem = None
        self.inputs = {}
        self.outputs = {}
        self.muls = self.divs = 0

    def _snapshot(self) -> dict:
        snap = {"R%d" % i: v for i, v in enumerate(self.R)}
        snap.update(HI=self.HI, LO=self.LO, SP=self.SP, flags=str(self.flags))
        return snap

    def run(self, program: Program, entry: str, mem: list, inputs: dict,
            trace: bool = False, max_instructions: int = 5000) -> RunResult:
        """Run from label `entry` until HALT, using `mem` as data memory."""
        self.program, self.mem, self.inputs, self.outputs = program, mem, inputs, {}
        self.PC = program.labels[entry]
        self.SP = STACK_WORDS
        self.halted = False
        self.muls = self.divs = 0
        count = uops = 0
        log = []
        while not self.halted:
            if count >= max_instructions:
                raise RuntimeError("program did not halt")
            pc = self.PC
            before = self._snapshot() if trace else None
            texts = []
            for text, action in FETCH:
                action(self)
                texts.append(text)
            for text, action in microroutine(self.dec):
                action(self)
                texts.append(text)
            count += 1
            uops += len(texts)
            if trace:
                after = self._snapshot()
                changed = ", ".join("%s=%s" % (k, after[k]) for k in after if after[k] != before[k])
                log.append({
                    "#": count, "PC": pc, "label": program.label_at(pc),
                    "instruction": program.listing[pc],
                    "machine word": "0x%08X" % program.words[pc],
                    "type": INSTRUCTION_TYPE[self.dec.op],
                    "micro-operations": [("T%d: %s" % (t, s)) for t, s in enumerate(texts)],
                    "changed": changed,
                })
        return RunResult(dict(self.outputs), count, uops, self.muls, self.divs, log)
