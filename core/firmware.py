"""The monitoring program that runs on the CPU, and its data-memory layout.

All values inside the CPU are integers in tenths of a unit (fixed point), so
62.5 degC is stored as 625. This keeps every value inside a 16-bit register.

Scaling a raw sensor count to engineering units:

    value = raw x SPAN / 1023        (SPAN = full-scale value in tenths)

The multiply is done with Booth's algorithm and the divide with restoring
division, both inside the ALU.
"""
from __future__ import annotations

from config import ADC_MAX, WINDOW, SensorSpec

from .cpu import assemble

# data-memory addresses
SYMBOLS = {
    "SPAN": 0, "DEN": 1, "COUNT": 2, "HEAD": 3, "VALUE": 4, "AVG": 5,
    "LO_CRIT": 6, "LO_WARN": 7, "HI_WARN": 8, "HI_CRIT": 9, "WINDOW": 10,
    "HIST": 16,
}
MEM_WORDS = SYMBOLS["HIST"] + WINDOW

NO_LOW = -32768      # used when a sensor has no low limit: nothing is ever <= this
NO_HIGH = 32767      # used when a sensor has no high limit: nothing is ever >= this

SOURCE = """
; ---------- stage 3 of the pipeline: compute ----------
COMPUTE:  IN    R1, #0          ; raw ADC count from the sensor buffer
          CALL  SCALE
          CALL  PUSH
          CALL  AVERAGE
          OUT   R1, #1          ; scaled value
          OUT   R2, #2          ; moving average
          HALT

; ---------- stage 4 of the pipeline: detect ----------
DETECT:   IN    R5, #1          ; scaled value from the pipeline latch
          CALL  CLASSIFY
          OUT   R6, #0          ; 0 normal, 1 warning, 2 critical
          HALT

; value = raw x SPAN / 1023
SCALE:    MUL   R1, SPAN        ; HI:LO <- raw x span   (Booth)
          DIVL  R1, DEN         ; R1 <- HI:LO / 1023    (restoring division)
          STORE R1, VALUE
          RET

; put the new value into the ring buffer HIST[0..WINDOW-1]
PUSH:     LOAD  R3, HEAD
          STORE R1, HIST(R3)    ; indexed addressing
          INC   R3
          CMP   R3, WINDOW
          BLT   PUSH1
          LOAD  R3, #0          ; wrap around
PUSH1:    STORE R3, HEAD
          LOAD  R7, COUNT
          CMP   R7, WINDOW
          BGE   PUSH2
          INC   R7
          STORE R7, COUNT
PUSH2:    RET

; moving average = (HIST[0] + ... + HIST[COUNT-1]) / COUNT
AVERAGE:  LOAD  R2, #0          ; sum
          LOAD  R3, #0          ; index
AVG1:     LOAD  R4, HIST(R3)
          ADD   R2, R4
          INC   R3
          CMP   R3, COUNT
          BLT   AVG1
          DIV   R2, COUNT
          STORE R2, AVG
          RET

; compare the value with the four limits and pick a status
CLASSIFY: CMP   R5, HI_CRIT
          BGE   CRIT
          CMP   R5, LO_CRIT
          BLE   CRIT
          CMP   R5, HI_WARN
          BGE   WARN
          CMP   R5, LO_WARN
          BLE   WARN
          LOAD  R6, #0
          RET
WARN:     LOAD  R6, #1
          RET
CRIT:     LOAD  R6, #2
          RET
"""

PROGRAM = assemble(SOURCE, SYMBOLS)


def tenths(x: float) -> int:
    return int(round(x * 10))


def new_memory(spec: SensorSpec) -> list:
    """Data-memory image for one sensor channel (its constants, limits and history)."""
    mem = [0] * MEM_WORDS
    mem[SYMBOLS["SPAN"]] = tenths(spec.span)
    mem[SYMBOLS["DEN"]] = ADC_MAX
    mem[SYMBOLS["WINDOW"]] = WINDOW
    mem[SYMBOLS["LO_CRIT"]] = NO_LOW if spec.lo_crit is None else tenths(spec.lo_crit)
    mem[SYMBOLS["LO_WARN"]] = NO_LOW if spec.lo_warn is None else tenths(spec.lo_warn)
    mem[SYMBOLS["HI_WARN"]] = NO_HIGH if spec.hi_warn is None else tenths(spec.hi_warn)
    mem[SYMBOLS["HI_CRIT"]] = NO_HIGH if spec.hi_crit is None else tenths(spec.hi_crit)
    return mem


def reference(raw: int, spec: SensorSpec, history: list):
    """Plain-Python version of the program, used by the tests to check the CPU.

    `history` is the list of earlier scaled values (tenths) for this channel and
    is updated in place. Returns (value, average, status code).
    """
    value = raw * tenths(spec.span) // ADC_MAX
    history.append(value)
    del history[:-WINDOW]
    avg = int(sum(history) / len(history))      # truncates towards zero like the ALU
    lo_c = NO_LOW if spec.lo_crit is None else tenths(spec.lo_crit)
    lo_w = NO_LOW if spec.lo_warn is None else tenths(spec.lo_warn)
    hi_w = NO_HIGH if spec.hi_warn is None else tenths(spec.hi_warn)
    hi_c = NO_HIGH if spec.hi_crit is None else tenths(spec.hi_crit)
    if value >= hi_c or value <= lo_c:
        status = 2
    elif value >= hi_w or value <= lo_w:
        status = 1
    else:
        status = 0
    return value, avg, status
