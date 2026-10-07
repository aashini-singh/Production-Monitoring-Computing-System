"""Look and feel for the dashboard: colours, CSS, HTML panels and chart builders."""
from __future__ import annotations

from html import escape

import altair as alt
import pandas as pd

from config import SENSORS

# ---- colour roles (light theme)
SURFACE = "#fcfcfb"
INK = "#16202a"
SECONDARY = "#52514e"
MUTED = "#8a8985"
GRID = "#e8e7e2"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]   # fixed order, never cycled
STATUS_COLOR = {"NORMAL": "#0ca30c", "WARNING": "#fab219", "CRITICAL": "#d03b3b", "INVALID": "#8a8985"}
STATUS_GLYPH = {"NORMAL": "●", "WARNING": "▲", "CRITICAL": "■", "INVALID": "✕"}   # shape, not colour alone
STATUS_LABEL = {"NORMAL": "Normal", "WARNING": "Warning", "CRITICAL": "Critical", "INVALID": "Invalid reading"}

CSS = """
<style>
.block-container {padding-top: 2.2rem; max-width: 1280px;}
h1 {font-size: 1.9rem !important; letter-spacing: -0.01em;}
.pm-lead {color: #52514e; margin: -0.6rem 0 1.1rem 0; max-width: 70ch;}
.pm-machine {background: #ffffff; border: 1px solid #e3e2dd; border-left-width: 7px;
             border-radius: 3px; padding: 14px 16px 12px 16px; margin-bottom: 6px;}
.pm-head {display: flex; justify-content: space-between; align-items: baseline; gap: 12px;}
.pm-id {font-weight: 700; font-size: 1.25rem; color: #16202a;}
.pm-name {color: #52514e; margin-left: 6px;}
.pm-state {font-weight: 600; color: #16202a; white-space: nowrap;}
.pm-glyph {font-size: 0.85em; margin-right: 5px;}
.pm-fault {color: #52514e; font-size: 0.86rem; height: 1.4rem; line-height: 1.4rem; margin-top: 2px;}
.pm-rows {width: 100%; border-collapse: collapse; margin-top: 6px; font-variant-numeric: tabular-nums;}
.pm-rows td {padding: 6px 0; border-top: 1px solid #efeee9; border-bottom: none; border-left: none;
             border-right: none; font-size: 0.93rem; color: #16202a;}
.pm-rows td:first-child {white-space: nowrap; padding-right: 6px;}
.pm-rows td.num {text-align: right; font-weight: 600; font-size: 1.05rem; white-space: nowrap;}
.pm-rows td.num small {font-weight: 400; color: #52514e; font-size: 0.78rem;}
.pm-rows td span.avg {display: block; color: #52514e; font-size: 0.8rem; line-height: 1.2;}
.pm-rows td.st {text-align: right; white-space: nowrap; padding-left: 12px; font-size: 0.86rem; width: 1%;}
.pm-foot {display: flex; justify-content: space-between; color: #52514e; font-size: 0.84rem;
          border-top: 1px solid #efeee9; padding-top: 8px; margin-top: 2px; font-variant-numeric: tabular-nums;}
.pm-bits {font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.95rem; letter-spacing: 0.04em;}
.pm-bits .s {background: #fde3e3;} .pm-bits .e {background: #dbeafb;} .pm-bits .m {background: #e3f4ec;}
.pm-bits span {padding: 2px 4px; border-radius: 2px; margin-right: 3px;}
</style>
"""


def status_html(status: str) -> str:
    return '<span class="pm-glyph" style="color:%s">%s</span>%s' % (
        STATUS_COLOR[status], STATUS_GLYPH[status], STATUS_LABEL[status])


def machine_panel(mon, machine) -> str:
    state = mon.machine_status(machine.key)
    fault = mon.plant.fault_of(machine.key)
    rows = []
    for spec in SENSORS:
        p = mon.latest.get((machine.key, spec.key))
        if p is None:
            rows.append('<tr><td>%s</td><td class="num">-</td><td class="st"></td></tr>'
                        % escape(spec.name))
            continue
        value = "%.1f" % p.value if p.valid else "no data"
        avg = "average %.1f" % p.avg if p.valid else "rejected by validation"
        rows.append(
            '<tr><td>%s<span class="avg">%s</span></td><td class="num">%s <small>%s</small></td>'
            '<td class="st">%s</td></tr>'
            % (escape(spec.name), avg, value, escape(spec.unit) if p.valid else "", status_html(p.status)))
    return (
        '<div class="pm-machine" style="border-left-color:%s">'
        '<div class="pm-head"><div><span class="pm-id">%s</span><span class="pm-name">%s</span></div>'
        '<span class="pm-state">%s</span></div>'
        '<div class="pm-fault">%s</div>'
        '<table class="pm-rows">%s</table>'
        '<div class="pm-foot"><span>Units made %s</span><span>Availability %.1f%%</span></div>'
        '</div>'
        % (STATUS_COLOR[state], machine.key, escape(machine.name), status_html(state),
           "Fault injected: %s" % escape(fault) if fault else "",
           "".join(rows), format(int(mon.units[machine.key]), ","), mon.availability(machine.key)))


def ieee_bits_html(enc) -> str:
    from core.alu import bits_str
    return ('<div class="pm-bits"><span class="s">%d</span><span class="e">%s</span><span class="m">%s</span></div>'
            % (enc.sign, bits_str(enc.exponent, 8), bits_str(enc.mantissa, 23)))


# ---------------------------------------------------------------- charts
def _style(chart, height: int):
    return (chart.properties(height=height)
            .configure_view(stroke=None)
            .configure_axis(labelColor=SECONDARY, titleColor=SECONDARY, gridColor=GRID, domainColor=GRID,
                            tickColor=GRID, labelFontSize=11, titleFontSize=11, titleFontWeight="normal")
            .configure_legend(labelColor=INK, titleColor=SECONDARY, labelFontSize=12, symbolStrokeWidth=3)
            .configure_header(labelColor=INK, labelFontSize=12, titleColor=SECONDARY))


def trend_chart(packets: list, spec, height: int = 190):
    """Reading and moving average over time, with the alert limits drawn as reference lines."""
    rows = []
    for p in packets:
        if p.valid:
            rows.append({"time": p.time, "series": "Reading", "value": p.value})
            rows.append({"time": p.time, "series": "Moving average", "value": p.avg})
    df = pd.DataFrame(rows, columns=["time", "series", "value"])
    limits = [(spec.hi_crit, "Critical"), (spec.hi_warn, "Warning"),
              (spec.lo_warn, "Warning"), (spec.lo_crit, "Critical")]
    limits = [(v, k) for v, k in limits if v is not None]
    values = list(df["value"]) + [v for v, _ in limits]
    lo, hi = (min(values), max(values)) if values else (0, 1)
    pad = max((hi - lo) * 0.12, 0.5)
    domain = [max(lo - pad, 0), hi + pad]

    x = alt.X("time:T", axis=alt.Axis(format="%H:%M:%S", title=None, tickCount=4, grid=False))
    y = alt.Y("value:Q", scale=alt.Scale(domain=domain, nice=False, zero=False),
              axis=alt.Axis(title=spec.unit, tickCount=4))
    names = ["Reading", "Moving average"]
    lines = alt.Chart(df).mark_line(strokeWidth=2, strokeJoin="round", strokeCap="round").encode(
        x=x, y=y,
        color=alt.Color("series:N", scale=alt.Scale(domain=names, range=SERIES[:2]),
                        legend=alt.Legend(orient="top", title=None)),
        strokeDash=alt.StrokeDash("series:N", scale=alt.Scale(domain=names, range=[[1, 0], [5, 3]]), legend=None))
    hover = alt.Chart(df).mark_point(size=120, opacity=0).encode(
        x=x, y=y, tooltip=[alt.Tooltip("time:T", format="%H:%M:%S", title="Time"),
                           alt.Tooltip("series:N", title="Series"),
                           alt.Tooltip("value:Q", format=".1f", title=spec.unit)])
    layers = []
    for value, kind in limits:
        colour = STATUS_COLOR[kind.upper()]
        ldf = pd.DataFrame({"y": [value], "label": ["%s limit %g" % (kind, value)]})
        layers.append(alt.Chart(ldf).mark_rule(strokeWidth=1.5, strokeDash=[6, 4], color=colour).encode(y="y:Q"))
        layers.append(alt.Chart(ldf).mark_text(align="left", baseline="bottom", dx=4, dy=-3, fontSize=11,
                                               color=SECONDARY).encode(x=alt.value(0), y="y:Q", text="label:N"))
    return _style(alt.layer(*layers, lines, hover), height)


def gantt_chart(timings: list, stage_names: list, height_per_row: int = 13):
    """One row per reading, one bar per stage, for the non-pipelined and pipelined runs."""
    rows = []
    for t in timings:
        for i, s, start, end in t.events:
            rows.append({"run": t.mode, "reading": "R%02d" % (i + 1), "stage": stage_names[s],
                         "start": start, "end": end})
    df = pd.DataFrame(rows)
    n = df["reading"].nunique()
    xmax = float(df["end"].max())
    charts = []
    for t in timings:
        sub = df[df["run"] == t.mode]
        charts.append(alt.Chart(sub).mark_bar(stroke=SURFACE, strokeWidth=1, cornerRadius=1).encode(
            x=alt.X("start:Q", scale=alt.Scale(domain=[0, xmax]), axis=alt.Axis(title="seconds", tickCount=6)),
            x2="end:Q",
            y=alt.Y("reading:N", sort=None, axis=alt.Axis(title=None, labelFontSize=9)),
            color=alt.Color("stage:N", scale=alt.Scale(domain=stage_names, range=SERIES),
                            legend=alt.Legend(orient="top", title="Stage")),
            tooltip=["reading:N", "stage:N", alt.Tooltip("start:Q", format=".3f"), alt.Tooltip("end:Q", format=".3f")],
        ).properties(height=max(n * height_per_row, 90),
                     title=alt.TitleParams("%s: %.2f s" % (t.mode.capitalize(), t.elapsed),
                                           anchor="start", fontSize=13, color=INK, fontWeight="normal")))
    chart = alt.vconcat(*charts).resolve_scale(color="shared")
    return (chart.configure_view(stroke=None)
            .configure_axis(labelColor=SECONDARY, titleColor=SECONDARY, gridColor=GRID, domainColor=GRID,
                            tickColor=GRID, titleFontWeight="normal")
            .configure_legend(labelColor=INK, titleColor=SECONDARY))


def two_series_chart(df: pd.DataFrame, x: str, series: list, y_title: str, x_title: str, height: int = 260):
    long = df.melt(id_vars=[x], value_vars=series, var_name="series", value_name="value")
    enc = dict(
        x=alt.X("%s:O" % x, axis=alt.Axis(title=x_title, labelAngle=0, grid=False)),
        y=alt.Y("value:Q", axis=alt.Axis(title=y_title, tickCount=5)),
        color=alt.Color("series:N", scale=alt.Scale(domain=series, range=SERIES[:len(series)]),
                        legend=alt.Legend(orient="top", title=None)))
    line = alt.Chart(long).mark_line(strokeWidth=2).encode(**enc)
    dots = alt.Chart(long).mark_point(size=70, filled=True, opacity=1, stroke=SURFACE, strokeWidth=2).encode(
        tooltip=["series:N", alt.Tooltip("%s:O" % x, title=x_title), alt.Tooltip("value:Q", format=".3f", title=y_title)],
        **enc)
    return _style(line + dots, height)


def wait_chart(df: pd.DataFrame, height: int = 250):
    """Average bus wait per device for each arbitration scheme (small multiples, one series)."""
    order = list(dict.fromkeys(df["device"]))
    chart = alt.Chart(df).mark_bar(size=11, cornerRadiusEnd=4, color=SERIES[0]).encode(
        x=alt.X("wait:Q", axis=alt.Axis(title="average wait (bus cycles)", tickCount=4)),
        y=alt.Y("device:N", sort=order, axis=alt.Axis(title=None)),
        tooltip=["scheme:N", "device:N", alt.Tooltip("wait:Q", format=".2f", title="Average wait")],
    ).properties(height=height, width=230).facet(
        column=alt.Column("scheme:N", sort=list(dict.fromkeys(df["scheme"])), title=None))
    return (chart.configure_view(stroke=None)
            .configure_axis(labelColor=SECONDARY, titleColor=SECONDARY, gridColor=GRID, domainColor=GRID,
                            tickColor=GRID, titleFontWeight="normal")
            .configure_header(labelColor=INK, labelFontSize=13))
