"""Production Monitoring Computing System - dashboard.

Run with:   streamlit run app.py
"""
from __future__ import annotations

import os
import time

import pandas as pd
import streamlit as st

import ui
from config import ADC_MAX, FAULTS, MACHINES, MACHINE_BY_KEY, SENSORS, SENSOR_BY_KEY, WINDOW
from core import alu, firmware, parallel, pipeline
from core.bus import SCHEMES, BusArbiter
from core.cpu import INSTRUCTION_TYPE, control_store, decode
from core.monitor import Monitor
from core.stages import STAGE_NAMES, Packet, Stages

LOG_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PAGES = ["Live monitor", "ALU lab", "Control unit", "Pipeline", "Parallel processing",
         "Bus arbitration", "Logs", "Syllabus map"]

st.set_page_config(page_title="Production monitoring", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)


def monitor() -> Monitor:
    if "monitor" not in st.session_state:
        st.session_state.monitor = Monitor(log_folder=LOG_FOLDER)
        st.session_state.last_tick = 0.0
    return st.session_state.monitor


def lead(text: str):
    st.markdown('<p class="pm-lead">%s</p>' % text, unsafe_allow_html=True)


# ================================================================ live monitor
def page_live():
    mon = monitor()
    st.title("Production line monitor")
    lead("Three machines, four sensors each. Every reading is scaled, averaged and checked "
         "against its limits by the simulated processor before it appears here.")

    with st.sidebar:
        st.subheader("Simulation")
        running = st.toggle("Run", value=True, help="Pause to freeze the readings.")
        interval = st.select_slider("Refresh every", options=[0.5, 1.0, 2.0], value=1.0,
                                    format_func=lambda s: "%g s" % s)
        mon.plant.auto_faults = st.toggle("Random faults", value=mon.plant.auto_faults,
                                          help="Lets faults start on their own now and then.")
        st.subheader("Inject a fault")
        machine_key = st.selectbox("Machine", [m.key for m in MACHINES],
                                   format_func=lambda k: "%s %s" % (k, MACHINE_BY_KEY[k].name))
        fault = st.selectbox("Fault", list(FAULTS))
        left, right = st.columns(2)
        if left.button("Inject", width="stretch", type="primary"):
            mon.plant.inject(machine_key, fault)
        if right.button("Clear faults", width="stretch"):
            mon.plant.clear()
        if st.button("Restart simulation", width="stretch"):
            mon.log.close()
            del st.session_state["monitor"]
            st.rerun()

    @st.fragment(run_every=interval if running else None)
    def panel():
        now = time.time()
        if running and now - st.session_state.last_tick >= interval * 0.7:
            mon.tick()
            st.session_state.last_tick = now
        if not mon.ticks:
            mon.tick()

        healthy = sum(mon.machine_status(m.key) == "NORMAL" for m in MACHINES)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Machines inside limits", "%d of %d" % (healthy, len(MACHINES)))
        k2.metric("Sensors outside limits", len(mon.active_alerts()))
        k3.metric("Readings processed", format(mon.readings, ","))
        k4.metric("Units made", format(int(sum(mon.units.values())), ","))

        for col, machine in zip(st.columns(len(MACHINES)), MACHINES):
            col.markdown(ui.machine_panel(mon, machine), unsafe_allow_html=True)

        st.subheader("Trends")
        chosen = st.segmented_control("Machine", [m.key for m in MACHINES], default=MACHINES[0].key,
                                      format_func=lambda k: "%s %s" % (k, MACHINE_BY_KEY[k].name),
                                      label_visibility="collapsed", key="trend_machine") or MACHINES[0].key
        cols = st.columns(2)
        for i, spec in enumerate(SENSORS):
            with cols[i % 2]:
                st.markdown("**%s**" % spec.name)
                st.altair_chart(ui.trend_chart(list(mon.history[(chosen, spec.key)]), spec), width="stretch")

        st.subheader("Status changes")
        if mon.alerts:
            df = pd.DataFrame(list(mon.alerts)[:12])
            df["to_status"] = df["to_status"].map(lambda s: "%s %s" % (ui.STATUS_GLYPH[s], ui.STATUS_LABEL[s]))
            df["from_status"] = df["from_status"].map(ui.STATUS_LABEL)
            df.columns = ["Time", "Machine", "Sensor", "Was", "Now", "Value", "Unit", "Why"]
            st.dataframe(df, width="stretch", hide_index=True)
        else:
            st.info("No status changes yet. Inject a fault from the sidebar to see one arrive here.")

        st.subheader("Work done by the processor so far")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Instructions executed", format(mon.stages.instructions, ","))
        c2.metric("Micro-operations", format(mon.stages.micro_ops, ","))
        c3.metric("Booth multiplications", format(mon.stages.multiplies, ","))
        c4.metric("Restoring divisions", format(mon.stages.divides, ","))
        st.caption("Bus arbitration: %s. %d readings rejected by validation. Log file: data/readings_log.csv"
                   % (mon.arbiter.scheme, mon.rejected))

    panel()


# ================================================================ ALU lab
def page_alu():
    st.title("ALU lab")
    lead("The arithmetic the monitor uses, one step at a time. The default numbers are the ones "
         "the monitor meets when it scales a temperature reading.")
    t_booth, t_array, t_div, t_ieee, t_cmp = st.tabs(
        ["Booth's multiplication", "Array multiplier", "Restoring division", "IEEE 754", "Add and compare"])

    with t_booth:
        c1, c2, c3 = st.columns(3)
        bits = c3.selectbox("Word size", [4, 8, 16], index=2, format_func=lambda b: "%d bits" % b)
        lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
        m = c1.number_input("Multiplicand (M)", lo, hi, min(563, hi), key="bm%d" % bits)
        q = c2.number_input("Multiplier (Q)", lo, hi, 1500 if bits == 16 else -3, key="bq%d" % bits)
        product, steps = alu.booth_multiply(int(m), int(q), bits, trace=True)
        st.success("%d x %d = %d. Product register A:Q = %s" % (m, q, product, alu.bits_str(product, 2 * bits)))
        st.caption("M = %s. In the monitor: raw count x full-scale span, for example 563 x 1500."
                   % alu.bits_str(int(m), bits))
        st.dataframe(pd.DataFrame(steps), width="stretch", hide_index=True)

    with t_array:
        c1, c2 = st.columns(2)
        a = c1.number_input("A (0 to 255)", 0, 255, 150)
        b = c2.number_input("B (0 to 255)", 0, 255, 13)
        product, rows = alu.array_multiply(int(a), int(b), 8)
        st.success("%d x %d = %d = %s" % (a, b, product, alu.bits_str(product, 16)))
        st.caption("Each row is one line of AND gates (A AND b_i, shifted left i places) feeding a row of adders.")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    with t_div:
        c1, c2, c3 = st.columns(3)
        bits = c3.selectbox("Word size", [8, 16, 32], index=2, format_func=lambda b: "%d bits" % b, key="dbits")
        top = (1 << bits) - 1
        dividend = c1.number_input("Dividend", 0, top, min(844500, top), key="dd%d" % bits)
        divisor = c2.number_input("Divisor", 1, top, min(1023, top), key="dv%d" % bits)
        quotient, rem, steps = alu.restoring_divide(int(dividend), int(divisor), bits, trace=True)
        st.success("%d / %d = %d remainder %d" % (dividend, divisor, quotient, rem))
        st.caption("In the monitor: (raw x span) / 1023 gives the value in tenths, e.g. 844500 / 1023 = 825 = 82.5.")
        st.dataframe(pd.DataFrame(steps), width="stretch", hide_index=True)

    with t_ieee:
        x = st.number_input("Decimal value", value=82.5, step=0.1, format="%.4f")
        enc = alu.ieee754_encode(x)
        st.success("%s  =  %s" % (x, enc.hex))
        st.markdown(ui.ieee_bits_html(enc), unsafe_allow_html=True)
        st.caption("Red: sign (1 bit). Blue: biased exponent (8 bits). Green: mantissa (23 bits).")
        for note in enc.notes:
            st.markdown("- %s" % note)
        st.caption("Decoded back: %r. Every value in the log carries this 32-bit form in the ieee754_hex column."
                   % alu.ieee754_decode(enc.word))

    with t_cmp:
        c1, c2 = st.columns(2)
        a = c1.number_input("A", -32768, 32767, 825)
        b = c2.number_input("B", -32768, 32767, 750)
        total, f_add = alu.add(int(a), int(b))
        diff, f_sub = alu.sub(int(a), int(b))
        st.dataframe(pd.DataFrame([
            {"operation": "A + B", "result": total, "binary": alu.bits_str(total, 16), "flags": str(f_add)},
            {"operation": "A - B", "result": diff, "binary": alu.bits_str(diff, 16), "flags": str(f_sub)},
            {"operation": "A AND B", "result": alu.logic("AND", int(a), int(b)),
             "binary": alu.bits_str(alu.logic("AND", int(a), int(b)), 16), "flags": ""},
            {"operation": "A OR B", "result": alu.logic("OR", int(a), int(b)),
             "binary": alu.bits_str(alu.logic("OR", int(a), int(b)), 16), "flags": ""},
            {"operation": "A XOR B", "result": alu.logic("XOR", int(a), int(b)),
             "binary": alu.bits_str(alu.logic("XOR", int(a), int(b)), 16), "flags": ""},
        ]), width="stretch", hide_index=True)
        st.caption("A >= B is decided from the flags of A - B: true when N equals V. Here: %s. "
                   "This is how 82.5 (825) is found to be over the 75.0 (750) limit." % f_sub.ge)


# ================================================================ control unit
def page_control():
    st.title("Control unit")
    lead("Follow one reading through the processor: each instruction is fetched, decoded and "
         "carried out as a short list of micro-operations taken from the control store.")
    c1, c2, c3 = st.columns([1, 1, 2])
    machine_key = c1.selectbox("Machine", [m.key for m in MACHINES])
    sensor_key = c2.selectbox("Sensor", [s.key for s in SENSORS], format_func=lambda k: SENSOR_BY_KEY[k].name)
    spec = SENSOR_BY_KEY[sensor_key]
    raw = c3.slider("Raw ADC count from the sensor", 0, ADC_MAX, 563,
                    help="0 is zero, 1023 is the sensor's full scale (%g %s)." % (spec.span, spec.unit))

    stages = Stages()
    p = stages.validate(stages.acquire(Packet(0, MACHINE_BY_KEY[machine_key], spec, raw)))
    p, trace_compute = stages.compute(p, trace=True)
    p, trace_detect = stages.detect(p, trace=True)
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Scaled value", "%.1f %s" % (p.value, spec.unit))
    r2.metric("Status", ui.STATUS_LABEL[p.status])
    r3.metric("Instructions", len(trace_compute) + len(trace_detect))
    r4.metric("Micro-operations", stages.micro_ops)
    st.caption("History is empty for this single run, so the moving average equals the value. %s" % p.detail)

    for title, trace in (("Stage 3, compute", trace_compute), ("Stage 4, detect", trace_detect)):
        st.subheader(title)
        df = pd.DataFrame(trace)
        df["micro-operations"] = df["micro-operations"].map(len)
        st.dataframe(df, width="stretch", hide_index=True, column_config={
            "label": st.column_config.TextColumn(width="small"),
            "instruction": st.column_config.TextColumn(width="medium"),
            "micro-operations": st.column_config.NumberColumn("micro-ops", width="small"),
            "changed": st.column_config.TextColumn("registers changed", width="large")})
        lines = []
        for row in trace:
            lines.append("#%-3d PC=%-3d %-22s %s  (%s)" % (row["#"], row["PC"], row["instruction"],
                                                          row["machine word"], row["type"]))
            lines += ["       " + op for op in row["micro-operations"]]
            if row["changed"]:
                lines.append("       => " + row["changed"])
            lines.append("")
        with st.expander("Micro-operations of every instruction in %s" % title.lower(),
                         expanded=title.startswith("Stage 4")):
            st.code("\n".join(lines), language=None, height=420)

    with st.expander("Instruction format and the full program"):
        st.code(" 31      26 25  23 22  20 19 18 17 16 15              0\n"
                " | opcode  |  Ra  |  Rb  | mode | 0 0 |    operand     |\n"
                " mode: 0 register, 1 immediate, 2 direct, 3 indexed", language=None)
        rows = []
        for addr, word in enumerate(firmware.PROGRAM.words):
            ins = decode(word)
            rows.append({"address": addr, "label": firmware.PROGRAM.label_at(addr),
                         "assembly": firmware.PROGRAM.listing[addr], "machine word": "0x%08X" % word,
                         "opcode": alu.bits_str(int(ins.op), 6), "Ra": ins.ra, "Rb": ins.rb,
                         "mode": ins.mode.name, "operand": ins.operand, "type": INSTRUCTION_TYPE[ins.op]})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    with st.expander("Control store (the microprogram)"):
        store = control_store()
        st.markdown("**Fetch, the same for every instruction**")
        st.code("\n".join("T%d: %s" % (i, t) for i, t in enumerate(store["FETCH"])), language=None)
        st.markdown("**Operand fetch, chosen by the addressing mode**")
        st.dataframe(pd.DataFrame([{"mode": k, "micro-operations": "   |   ".join(v)}
                                   for k, v in store["OPERAND"].items()]), width="stretch", hide_index=True)
        st.markdown("**Execute, chosen by the opcode**")
        st.dataframe(pd.DataFrame([{"opcode": k, "micro-operations": "   |   ".join(v) or "(none)"}
                                   for k, v in store["EXECUTE"].items()]), width="stretch", hide_index=True)
        st.caption("The control unit is microprogrammed: changing an instruction means editing this table, "
                   "not rewiring logic. A hardwired unit would generate the same signals from fixed gates.")


# ================================================================ pipeline
def page_pipeline():
    st.title("Pipeline")
    lead("The same readings pushed through the five stages twice: one reading at a time, and "
         "with every stage working on a different reading at once.")
    c1, c2, c3 = st.columns([2, 2, 1])
    n = c1.slider("Readings", 5, 30, 16)
    delay_ms = c2.slider("Time per stage (ms)", 10, 60, 25, step=5)
    c3.write("")
    run = c3.button("Run both", type="primary", width="stretch")
    if run:
        with st.spinner("Running both versions"):
            seq = pipeline.run_sequential(n, delay_ms / 1000)
            pipe = pipeline.run_pipelined(n, delay_ms / 1000)
        st.session_state.pipe_result = (n, delay_ms, seq, pipe)

    if "pipe_result" in st.session_state:
        n_run, d_run, seq, pipe = st.session_state.pipe_result
        ideal = pipeline.ideal(n_run, d_run / 1000)
        same = [(p.value_t, p.status) for p in seq.packets] == [(p.value_t, p.status) for p in pipe.packets]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Non-pipelined", "%.2f s" % seq.elapsed, help="Ideal: n x k x t = %.2f s" % ideal["non_pipelined"])
        m2.metric("Pipelined", "%.2f s" % pipe.elapsed, help="Ideal: (k + n - 1) x t = %.2f s" % ideal["pipelined"])
        m3.metric("Measured speedup", "%.2fx" % (seq.elapsed / pipe.elapsed))
        m4.metric("Ideal speedup", "%.2fx" % ideal["speedup"], help="n x k / (k + n - 1)")
        st.caption("%d readings, %d stages, %d ms per stage. Both runs gave %s results."
                   % (n_run, pipeline.K, d_run, "identical" if same else "DIFFERENT"))
        st.altair_chart(ui.gantt_chart([seq, pipe], STAGE_NAMES), width="stretch")
        with st.expander("Timing data as a table"):
            st.dataframe(pd.DataFrame(
                [{"run": t.mode, "reading": i + 1, "stage": STAGE_NAMES[s], "start (s)": round(a, 3),
                  "end (s)": round(b, 3)} for t in (seq, pipe) for i, s, a, b in t.events]),
                width="stretch", hide_index=True)
    else:
        st.info("Choose the number of readings and press Run both. It takes a few seconds.")

    st.subheader("Space-time diagram")
    st.caption("Ideal pipeline for the first 6 readings. Columns are clock cycles; R1 is the first reading.")
    st.dataframe(pd.DataFrame(pipeline.space_time(6)), width="stretch", hide_index=True)
    st.caption("The time per stage is added on purpose to stand in for real stage latency. "
               "The Python work inside each stage takes only microseconds.")


# ================================================================ parallel
def page_parallel():
    st.title("Parallel processing")
    lead("Flynn's classification, shown with the monitor's own workload.")
    st.dataframe(pd.DataFrame(parallel.FLYNN), width="stretch", hide_index=True)

    st.subheader("SISD against MIMD")
    c1, c2, c3 = st.columns([2, 2, 1])
    readings = c1.slider("Samples per machine", 2, 10, 5)
    latency = c2.slider("Sensor read time (ms)", 2, 20, 5)
    c3.write("")
    if c3.button("Run benchmark", type="primary", width="stretch"):
        with st.spinner("Timing 1, 2, 4 and 8 machines"):
            st.session_state.par_result = parallel.benchmark(readings=readings, io_latency=latency / 1000)
    if "par_result" in st.session_state:
        df = pd.DataFrame(st.session_state.par_result)
        st.altair_chart(ui.two_series_chart(df, "machines", ["SISD seconds", "MIMD seconds"],
                                            "seconds", "machines monitored"), width="stretch")
        st.dataframe(df, width="stretch", hide_index=True)
        st.caption("SISD time grows with every machine added. MIMD stays almost flat because each machine "
                   "has its own worker and the waits for the sensors overlap. The sensor read time is simulated.")
    else:
        st.info("Press Run benchmark to time one processor against one worker per machine.")

    st.subheader("SIMD: one limit check over many readings")
    if st.button("Run vector check"):
        st.session_state.simd_result = parallel.simd_demo()
    if "simd_result" in st.session_state:
        r = st.session_state.simd_result
        a, b, c, d = st.columns(4)
        a.metric("Readings checked", format(r["values"], ","))
        b.metric("One at a time", "%.1f ms" % (r["scalar seconds"] * 1000))
        c.metric("One vector operation", "%.2f ms" % (r["vector seconds"] * 1000))
        d.metric("Over the limit", format(r["over limit"], ","))
        st.caption("Both methods found the same %s readings over %.0f. The vector version runs in compiled "
                   "code that uses the processor's SIMD instructions; part of the gap also comes from "
                   "avoiding a Python loop, so do not quote it as a pure SIMD speedup."
                   % (format(r["over limit"], ","), r["limit"]))


# ================================================================ bus
SCHEME_LABEL = {"daisy": "Daisy chaining", "polling": "Polling", "independent": "Independent request"}


@st.cache_data
def bus_comparison(cycles: int = 240) -> pd.DataFrame:
    devices = ["%s %s" % (m.key, s.key) for m in MACHINES for s in SENSORS]
    rows = []
    for scheme in SCHEMES:
        bus = BusArbiter(len(devices), scheme)
        for _ in range(cycles):
            bus.grant_order(list(range(len(devices))), {9: 3, 4: 2})   # M3 vib critical, M2 temp warning
        for name, wait in zip(devices, bus.average_wait()):
            rows.append({"scheme": SCHEME_LABEL[scheme], "device": name, "wait": wait})
    return pd.DataFrame(rows)


def page_bus():
    mon = monitor()
    st.title("Bus arbitration")
    lead("All twelve sensors want the single data bus in the same instant. The arbiter decides who goes first.")
    scheme = st.radio("Scheme used by the live monitor", SCHEMES, index=SCHEMES.index(mon.arbiter.scheme),
                      horizontal=True, format_func=SCHEME_LABEL.get)
    mon.arbiter.scheme = scheme
    st.markdown({
        "daisy": "**Daisy chaining.** The grant signal passes from device to device, so the sensor nearest "
                 "the arbiter always wins and the last one always waits longest.",
        "polling": "**Polling.** The arbiter asks each address in turn and continues from where it stopped, "
                   "so over time every sensor waits the same.",
        "independent": "**Independent request.** Every sensor has its own request line and a priority. "
                       "Here the priority is the sensor's last status, so a sensor in alarm is served first.",
    }[scheme])

    st.subheader("How long each sensor waits")
    st.caption("240 bus cycles with all sensors requesting. In this test M3 vib is critical and M2 temp is in warning.")
    df = bus_comparison()
    st.altair_chart(ui.wait_chart(df))
    with st.expander("Same data as a table"):
        st.dataframe(df.pivot(index="device", columns="scheme", values="wait").round(2).reset_index(),
                     width="stretch", hide_index=True)

    st.subheader("Last grant order in the live monitor")
    if mon.last_grant:
        names = ["%s %s" % (d.machine.key, d.spec.key) for d in mon.plant.devices]
        st.write(",  ".join("%d. %s" % (i + 1, names[d]) for i, d in enumerate(mon.last_grant)))
    else:
        st.info("Open the Live monitor page once so the simulation takes a sample.")


# ================================================================ logs
def page_logs():
    mon = monitor()
    st.title("Logs")
    lead("Everything the monitor has written to disk. These CSV files are the evidence for the report.")
    if mon.log:
        mon.log.flush()
    t1, t2 = st.tabs(["Readings", "Status changes"])
    for tab, path, label in ((t1, mon.log.readings_path, "readings"), (t2, mon.log.alerts_path, "alerts")):
        with tab:
            if not os.path.exists(path) or os.path.getsize(path) == 0:
                st.info("Nothing logged yet.")
                continue
            df = pd.read_csv(path)
            if df.empty:
                st.info("Nothing logged yet. Open the Live monitor page to start sampling.")
                continue
            c1, c2, c3 = st.columns([2, 2, 1])
            machines = c1.multiselect("Machine", sorted(df["machine"].unique()), key=label + "m")
            col = "status" if label == "readings" else "to_status"
            states = c2.multiselect("Status", sorted(df[col].unique()), key=label + "s")
            if machines:
                df = df[df["machine"].isin(machines)]
            if states:
                df = df[df[col].isin(states)]
            c3.metric("Rows", format(len(df), ","))
            st.dataframe(df.tail(500).iloc[::-1], width="stretch", hide_index=True)
            st.caption("Newest first, up to 500 rows shown. The download has every row that matches the filters.")
            st.download_button("Download %s CSV" % label, df.to_csv(index=False).encode("utf-8"),
                               file_name="%s_log.csv" % label, mime="text/csv")


# ================================================================ syllabus map
def page_syllabus():
    st.title("Syllabus map")
    lead("Where each CAPP topic is used in this project, and where to see it running.")
    rows = [
        ("1", "Functional units and interconnection", "core/sensors.py, stages.py, logger.py", "Live monitor"),
        ("1", "Buses, bus and memory transfer", "core/cpu.py (MAR, MBR, memory read and write)", "Control unit"),
        ("1", "Bus arbitration: daisy chaining, polling, independent request", "core/bus.py", "Bus arbitration"),
        ("1", "Registers, general register organisation", "core/cpu.py (R0-R7, PC, IR, HI, LO)", "Control unit"),
        ("1", "Stack organisation", "core/cpu.py (CALL, RET, SP)", "Control unit"),
        ("1", "Addressing modes", "core/cpu.py (register, immediate, direct, indexed)", "Control unit"),
        ("2", "Signed multiplication, Booth's algorithm", "core/alu.py booth_multiply", "ALU lab"),
        ("2", "Array multiplier", "core/alu.py array_multiply", "ALU lab"),
        ("2", "Division", "core/alu.py restoring_divide", "ALU lab"),
        ("2", "Arithmetic and logic operations, ALU design", "core/alu.py add, sub, compare, logic", "ALU lab"),
        ("2", "Floating point, IEEE 754", "core/alu.py ieee754_encode", "ALU lab, Logs"),
        ("3", "Instruction types and formats", "core/cpu.py encode, decode", "Control unit"),
        ("3", "Instruction cycle, micro-operations", "core/cpu.py CPU.run, FETCH, EXECUTE", "Control unit"),
        ("3", "Program control", "core/firmware.py (CMP, branches, CALL)", "Control unit"),
        ("3", "RISC and CISC", "Fixed 32-bit format like RISC; memory operands and multi-cycle MUL/DIV like CISC", "Control unit"),
        ("3", "Pipelining", "core/pipeline.py", "Pipeline"),
        ("3", "Hardwired and microprogrammed control", "core/cpu.py control store", "Control unit"),
        ("3", "Flynn's classification", "core/parallel.py", "Parallel processing"),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["Unit", "Topic", "Where in the code", "Dashboard page"]),
                 width="stretch", hide_index=True, height=670)
    st.caption("Moving-average window: %d readings. ADC resolution: 10 bits (0 to %d)." % (WINDOW, ADC_MAX))


# ================================================================ navigation
with st.sidebar:
    st.markdown("### Production monitoring")
    page = st.radio("Page", PAGES, label_visibility="collapsed")
    st.divider()

{"Live monitor": page_live, "ALU lab": page_alu, "Control unit": page_control, "Pipeline": page_pipeline,
 "Parallel processing": page_parallel, "Bus arbitration": page_bus, "Logs": page_logs,
 "Syllabus map": page_syllabus}[page]()
