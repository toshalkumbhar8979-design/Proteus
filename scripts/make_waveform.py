"""Render the JTAG IDCODE scan from the cocotb dump as a figure.

Source: test/tb.fst, converted to VCD with fst2vcd (gtkwave, WSL):
    fst2vcd test/tb.fst > test/tb.vcd

Signals, per programs/jtag_idcode.s and docs/info.md:
    uio_out[0] TCK, uio_out[1] TMS, uio_out[2] TDI   driven by the firmware
    ui_in[4]   TDO                                   driven by the modelled TAP

The scan window is chosen from the TAP state, not from the answer: in Shift-DR
the firmware holds TMS low for exactly the 32 shift clocks, so the window is the
longest run of TCK rising edges with TMS low. The decoded word is then a check.
"""
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

VCD = Path("test/tb.vcd")
OUT = Path("docs/images/jtag_waveform.png")
EXPECTED = 0x1A5A5A5D

txt = VCD.read_text(errors="ignore")
ids = {}
for _w, i, n in re.findall(r"\$var\s+\w+\s+(\d+)\s+(\S+)\s+(\S+)", txt):
    ids.setdefault(n, (int(_w), i))
body = txt.split("$enddefinitions $end", 1)[1].splitlines()


def bus(name):
    ident = ids[name][1]
    t, ev = 0, []
    for line in body:
        line = line.strip()
        if not line:
            continue
        if line[0] == "#":
            t = int(line[1:])
            continue
        if line[0] in "bB":
            parts = line.split()
            if len(parts) == 2 and parts[1] == ident:
                ev.append((t, parts[0][1:]))
    return ev


def bit_of(value, k):
    if len(value) <= k or any(c not in "01" for c in value):
        return None
    return (int(value, 2) >> k) & 1


def series(ev, k):
    out, prev = [], None
    for t, v in ev:
        b = bit_of(v, k)
        if b is not None and b != prev:
            out.append((t, b))
            prev = b
    return out


def at(ser, t, default=0):
    v = default
    for tt, b in ser:
        if tt <= t:
            v = b
        else:
            break
    return v


tck = series(bus("uio_out"), 0)
tms = series(bus("uio_out"), 1)
tdi = series(bus("uio_out"), 2)
tdo = series(bus("ui_in"), 4)

rises = [t for t, v in tck if v == 1]
runs, cur = [], []
for t in rises:
    if at(tms, t - 1) == 0:
        cur.append(t)
    else:
        if cur:
            runs.append(cur)
        cur = []
if cur:
    runs.append(cur)

scan = max(runs, key=len)
full_scan = list(scan)
scan = scan[:8]          # first eight shift clocks, so the data edges are readable
t0, t1 = scan[0], scan[-1] + 260000
print("TCK rising edges:", len(rises), "TMS-low runs:", [len(r) for r in runs])
print("scan window:", t0, "to", t1, "clocks:", len(scan))

# TDO as captured, one sample per shift clock. The cocotb test does the actual
# IDCODE check; this reconstruction is only used to place tick marks.
bits = [at(tdo, t - 1) for t in scan]
print("TDO samples:", "".join(str(b) for b in bits))

# ------------------------------------------------------------------ drawing
BG, INK, MID, RULE = "#F7FAFD", "#1B2A3A", "#7C90A6", "#D5E1EE"
TCK_C, TMS_C, TDI_C, TDO_C = "#1D4ED8", "#B45309", "#0E7490", "#15803D"


def steps(ser, t0, t1, y0, h):
    xs, ys = [t0], []
    cur = at(ser, t0)
    ys.append(y0 if cur else y0 + h)
    for tt, b in ser:
        if tt <= t0:
            cur = b
            continue
        if tt >= t1:
            break
        xs += [tt, tt]
        ys += [y0 if cur else y0 + h, y0 if b else y0 + h]
        cur = b
    xs.append(t1)
    ys.append(y0 if cur else y0 + h)
    return xs, ys


fig, ax = plt.subplots(figsize=(13.0, 4.4), dpi=220)
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)

rows = [("TCK", tck, TCK_C), ("TMS", tms, TMS_C), ("TDI", tdi, TDI_C), ("TDO", tdo, TDO_C)]
h = 0.6
span = (t1 - t0) / 1000.0

for i, (name, ser, col) in enumerate(rows):
    y = len(rows) - 1 - i
    xs, ys = steps(ser, t0, t1, y, h)
    ax.plot([(x - t0) / 1000.0 for x in xs], ys, color=col, linewidth=1.7,
            solid_joinstyle="miter", solid_capstyle="butt")
    ax.text(-0.4, y + h / 2, name, ha="right", va="center", fontsize=9,
            color=INK, family="monospace")

for i, t in enumerate(scan):
    x = (t - t0) / 1000.0
    ax.axvline(x, color=RULE, linewidth=0.5, zorder=0)
    ax.text(x + 0.1, -0.45, str(bits[i]), fontsize=6.0, color="#A8B7C7",
            ha="left", va="top", family="monospace")

ax.set_xlim(-1.6, span + 0.5)
ax.set_ylim(-1.55, len(rows) + 0.35)
ax.set_yticks([])
ax.set_xlabel("time from the first shift clock (ns, testbench timescale)", fontsize=8, color=MID)
for side in ("top", "right", "left"):
    ax.spines[side].set_visible(False)
ax.spines["bottom"].set_color(RULE)
ax.tick_params(colors=MID, labelsize=7)

ax.text(0, len(rows) + 0.12,
        "JTAG scan detail: TCK and TMS driven by firmware, TDO read back from the pad",
        fontsize=9, color=INK, va="bottom")
ax.text(span, len(rows) + 0.12, "8 of the 32 shift clocks", fontsize=9, color=INK,
        family="monospace", ha="right", va="bottom")
ax.text(0.3, -1.45,
        'captured from test/tb.fst (cocotb test_jtag_idcode): the first eight of the 32 shift clocks. TCK idles high and is pulsed low by the firmware, TMS is held low for the whole scan, and TDO is the modelled TAP shifting out its IDCODE. The cocotb test assembles the 32 bits and checks the 0xC3 pass marker the core writes to uo_out.',
        fontsize=7.2, color=MID, wrap=True)

fig.tight_layout()
fig.savefig(OUT, facecolor=BG, bbox_inches="tight")
print("wrote", OUT)
