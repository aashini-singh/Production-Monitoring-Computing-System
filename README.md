# Production Monitoring Computing System

A production-line monitor written in Python. Three simulated machines send sensor
readings; a small simulated processor scales each reading, averages it, checks it
against limits and raises alerts; a dashboard shows everything live and writes a CSV log.

The point of the project is that the monitoring is done the way a computer does it
internally, so each CAPP topic (Units 1 to 3) is something you can run and show,
not only describe.

## Run it

You need Python 3.10 or newer.

```
pip install -r requirements.txt
streamlit run app.py
```

The dashboard opens in the browser at http://localhost:8501.
Run both commands from inside this folder.

Without the dashboard:

```
python run_cli.py 40 Overheat      # 40 samples, overheat fault on M1 from sample 10
python -m unittest discover -s tests -t .      # 32 tests
```

## What is real and what is simulated

Say this plainly in the report and the viva.

| Part | Status |
|---|---|
| ALU: Booth's multiplication, array multiplier, restoring division, IEEE 754, flags | Real algorithms, written out bit by bit and checked against Python's own arithmetic in the tests |
| Processor: registers, instruction format, fetch-decode-execute, micro-operations, control store, stack | A software simulation of a 16-bit processor. It really runs the monitoring program for every reading |
| Sensors and machines | Simulated. There is no hardware. Values are generated with random noise |
| Alert limits (75 °C and so on) | Illustrative numbers chosen for the demo, not from a real plant. Change them in `config.py` |
| Pipeline and parallel timings | Measured on your computer, but the stage time and the sensor read time are added with `sleep()` to stand in for real hardware latency |
| SIMD timing | Real measurement, but much of the gap comes from avoiding a Python loop, so it is not a pure SIMD figure |

## Dashboard pages

| Page | What to show on it |
|---|---|
| Live monitor | Inject a fault from the sidebar and watch a machine go Warning then Critical |
| ALU lab | Step tables for Booth's algorithm, division and IEEE 754 for any numbers you type |
| Control unit | One reading traced instruction by instruction, with every micro-operation |
| Pipeline | Non-pipelined against pipelined timing chart, and the space-time diagram |
| Parallel processing | Flynn's classification, SISD against MIMD timing |
| Bus arbitration | Daisy chaining, polling and independent request compared |
| Logs | The CSV files, with filters and download |
| Syllabus map | Topic to code file to dashboard page |

## How one reading is processed

```
sensor -> [1 acquire] -> [2 validate] -> [3 compute] -> [4 detect] -> [5 output]
           bus, buffer    range check     CPU: scale,    CPU: compare   dashboard,
           register                       history, avg   with limits    alerts, CSV
```

Stage 3 and stage 4 run this program on the simulated processor (`core/firmware.py`):

```
value   = raw x SPAN / 1023        MUL uses Booth's algorithm, DIVL uses restoring division
average = sum of last 8 values / count
status  = critical, warning or normal, from CMP and conditional branches
```

Values inside the processor are whole numbers in tenths (82.5 is stored as 825) so
they fit in 16-bit registers.

## Files

```
app.py              dashboard (Streamlit)
ui.py               colours, panels and charts for the dashboard
run_cli.py          console version
config.py           machines, sensors, limits, fault scenarios
core/
  alu.py            Unit 2: add, sub, flags, Booth, array multiplier, division, IEEE 754
  cpu.py            Units 1 and 3: registers, instruction format, assembler, control store, CPU
  firmware.py       the monitoring program in assembly, and its memory layout
  bus.py            Unit 1: bus arbitration schemes
  sensors.py        simulated machines, sensors and faults
  stages.py         the five processing stages
  monitor.py        the engine that runs one sampling interval
  pipeline.py       Unit 3: pipelined against non-pipelined run
  parallel.py       Unit 3: Flynn's classification benchmarks
  logger.py         CSV logging
tests/              32 unit tests
data/               CSV logs appear here when the monitor runs
docs/screenshots/   sample screenshots from a test run
```

## Syllabus map

| Unit | Topic | Where |
|---|---|---|
| 1 | Functional units and interconnection | `sensors.py`, `stages.py`, `logger.py` |
| 1 | Buses, bus and memory transfer | `cpu.py`: MAR, MBR, memory read and write |
| 1 | Bus arbitration and its types | `bus.py` |
| 1 | Registers, general register organisation | `cpu.py`: R0-R7, PC, IR, HI, LO |
| 1 | Stack organisation | `cpu.py`: CALL, RET, SP |
| 1 | Addressing modes | `cpu.py`: register, immediate, direct, indexed |
| 2 | Signed multiplication, Booth's algorithm | `alu.py` `booth_multiply` |
| 2 | Array multiplier | `alu.py` `array_multiply` |
| 2 | Division | `alu.py` `restoring_divide`, `divide` |
| 2 | Arithmetic and logic operations, ALU design | `alu.py` `add`, `sub`, `compare`, `logic` |
| 2 | Floating point, IEEE 754 | `alu.py` `ieee754_encode`, `ieee754_decode` |
| 3 | Instruction types and formats | `cpu.py` `encode`, `decode`, `INSTRUCTION_TYPE` |
| 3 | Instruction cycle and micro-operations | `cpu.py` `CPU.run`, `FETCH`, `EXECUTE` |
| 3 | Program control | `firmware.py`: CMP, branches, CALL |
| 3 | RISC and CISC | Fixed 32-bit format like RISC; memory operands and multi-cycle MUL/DIV like CISC |
| 3 | Pipelining | `pipeline.py` |
| 3 | Hardwired and microprogrammed control | `cpu.py`: the control store |
| 3 | Flynn's classification | `parallel.py` |

Not covered: horizontal against vertical microprogramming is not modelled (the
control store lists micro-operations, not control-signal bit patterns), and
nothing from Unit 4.

## Figures from one test run

Measured in the build environment on 7 Oct 2026. Yours will differ; run it and
use your own numbers in the report.

| Measurement | Result |
|---|---|
| Unit tests | 32 of 32 pass |
| Instructions per reading | about 78 (about 420 micro-operations) |
| Pipeline, 16 readings, 25 ms per stage | 2.03 s non-pipelined, 0.51 s pipelined, 3.95x (ideal 4.00x) |
| SISD against MIMD, 8 machines | 0.89 s against 0.12 s |

## Suggested split for five members

| Member | Module | Can explain |
|---|---|---|
| 1 | `sensors.py`, `bus.py`, `logger.py` | Functional units, bus arbitration |
| 2 | `alu.py` | Booth's algorithm, division, IEEE 754 |
| 3 | `cpu.py`, `firmware.py` | Instruction cycle, micro-operations, addressing modes |
| 4 | `pipeline.py`, `parallel.py` | Pipelining, Flynn's classification |
| 5 | `app.py`, `ui.py`, tests, report | Dashboard, results, testing |

## Evidence for the progress report

1. Run the dashboard, inject each fault, and take your own screenshots.
2. Download the CSVs from the Logs page.
3. Run the Pipeline and Parallel benchmarks and note your numbers.
4. Run the tests and screenshot the result.
