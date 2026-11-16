"""Render the multi-protocol demonstration as an animated GIF.

Every frame is drawn from a cocotb dump of the test that proves the behaviour, so
the animation is a recording of the simulation rather than an illustration. This
mirrors scripts/make_waveform.py, which renders one static JTAG scan the same way.

Produce the dumps first (gtkwave's fst2vcd is needed):

    cd test
    for t in test_uart_tx test_i2c_master test_ps2_device \
             test_usb_data_packet test_capture_roll; do
        make -B TESTCASE=$t && fst2vcd tb.fst > /tmp/$t.vcd
    done
    cd ..

then

    python3 scripts/make_demo_animation.py

Windows are found from the shape of the protocol rather than from the answer: the
UART window begins at the first falling edge on the TX pin that stays low for a
whole bit time (the loader also drives that pin, so a bare edge is not enough),
the I2C window at the first SDA falling edge with SCL high, the USB window at the
first bit strobe, and the capture window at the first pin change. The values
printed in the log panel are then checks on the window, not its definition.

A GIF, not an MP4: GitHub renders GIFs inline in markdown and does not autoplay
video, so a GIF is the only form that plays in a README.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DUMPS = Path("/tmp") if Path("/tmp").is_dir() else ROOT
OUT = ROOT / "docs/images/demo.gif"
FRAMES_DIR = ROOT / "build/anim"

BG = "#0E1726"
INK = "#E8F0FA"
MID = "#93A7BF"
RULE = "#26374F"
BLUE = "#4FA3FF"
AMBER = "#F2B134"
GREEN = "#6EE7A8"
VIOLET = "#C084FC"
SLATE = "#7C8DA6"

W, H = 6.6, 3.6
DPI = 100
FRAMES = 34
HOLD = 12


class Vcd:
    def __init__(self, path: Path) -> None:
        text = path.read_text(errors="ignore")
        head, body = text.split("$enddefinitions $end", 1)
        self.ids: dict[str, str] = {}
        for _w, ident, name in re.findall(r"\$var\s+\w+\s+(\d+)\s+(\S+)\s+(\S+)", head):
            self.ids.setdefault(name, ident)
        self.body = body.splitlines()

    def events(self, name: str) -> list[tuple[int, str]]:
        ident = self.ids[name]
        t, out = 0, []
        for line in self.body:
            line = line.strip()
            if not line:
                continue
            if line[0] == "#":
                t = int(line[1:])
            elif line[0] in "bB":
                parts = line.split()
                if len(parts) == 2 and parts[1] == ident:
                    out.append((t, parts[0][1:]))
            elif line[-1] == ident and line[0] in "01xz":
                out.append((t, line[0]))
        return out


def bit_series(events, k: int) -> list[tuple[int, int]]:
    out, prev = [], None
    for t, v in events:
        if len(v) <= k or any(c not in "01" for c in v):
            continue
        b = (int(v, 2) >> k) & 1
        if b != prev:
            out.append((t, b))
            prev = b
    return out


def sample(ser, times, default: int = 0) -> list[int]:
    out, j, cur = [], 0, default
    for t in times:
        while j < len(ser) and ser[j][0] <= t:
            cur = ser[j][1]
            j += 1
        out.append(cur)
    return out


def load(name: str, signal: str, bit: int = 0, default: int = 0):
    """Per-clock samples of one pad bit, plus the rising clock edges."""
    path = DUMPS / f"{name}.vcd"
    vcd = Vcd(path)
    edges = [t for t, v in bit_series(vcd.events("clk"), 0) if v == 1]
    values = sample(bit_series(vcd.events(signal), bit), edges, default)
    return values, edges


def run_start(name: str) -> int:
    """First clock after the last loader frame: CS_N (ui_in[7]) goes back high.

    The loader drives the same pins the firmware later uses, and the core is held
    in reset while CS_N is low, so every window must start after this point.
    """
    cs, _ = load(name, "ui_in", 7, default=1)
    lows = [i for i, v in enumerate(cs) if v == 0]
    return (lows[-1] + 1) if lows else 0


def first(values, pred, start=60):
    for i in range(max(start, 1), len(values)):
        if pred(values, i):
            return i
    return None


class Scene:
    def __init__(self, title, sub, rows, log, footer, grid=0, cell=""):
        self.title, self.sub, self.rows, self.log = title, sub, rows, log
        self.footer, self.grid, self.cell = footer, grid, cell


# ---------------------------------------------------------------------- scenes
def uart_scene() -> Scene:
    tx, _ = load("test_uart_tx", "uo_out", 7, default=1)
    bit = 417
    # A real start bit holds the line low for a whole bit time; the loader's MISO
    # readback toggles that same pin in short bursts before the core runs.
    # The line must be idle high for a while and then fall for a whole bit time:
    # that excludes the loader's MISO readback, which also drives this pin.
    start = first(tx, lambda v, i: v[i] == 0 and v[i - 1] == 1
                  and all(c == 0 for c in v[i:i + 320]),
                  start=run_start("test_uart_tx"))
    if start is None:
        raise SystemExit("no start bit")
    a, b = max(start - 20, 0), min(start + 10 * bit + 20, len(tx))
    byte = sum(tx[start + bit * (k + 1) + 120] << k for k in range(8))
    print(f"uart start {start}, byte 0x{byte:02X}")
    log = [(0.02, "start bit: line falls and holds for 417 clocks"),
           (0.42, "8 data bits, LSB first, sampled at each bit centre"),
           (0.80, f"stop bit -> 0x{byte:02X} '{chr(byte)}'")]
    return Scene("UART 8N1, transmitter",
                 "76.8 kbaud at 32 MHz: one WAIT per bit, 417 clocks, no UART block",
                 [("TX", BLUE, tx[a:b])], log,
                 "test_uart_tx · programs/uart_tx.s", grid=bit, cell="bit cell = 417 clocks")


def i2c_scene() -> Scene:
    scl, _ = load("test_i2c_master", "scl_bus")
    sda, _ = load("test_i2c_master", "sda_bus")
    start = first(scl, lambda v, i: v[i] == 1 and sda[i] == 0 and sda[i - 1] == 1,
                  start=run_start("test_i2c_master"))
    if start is None:
        raise SystemExit("no START")
    a, b = max(start - 30, 0), min(start + 3300, len(scl))
    log = [(0.01, "START: SDA falls while SCL is high"),
           (0.30, "address 0x28 + write bit, driven open-drain"),
           (0.80, "target pulls SDA low for the ACK")]
    return Scene("I2C controller, open-drain",
                 "~100 kHz at 32 MHz: per-bit output enable, no dedicated I2C logic",
                 [("SCL", AMBER, scl[a:b]), ("SDA", GREEN, sda[a:b])], log,
                 "test_i2c_master · programs/i2c_master.s", grid=312, cell="SCL period ~312 clocks")


def ps2_scene() -> Scene:
    out = Vcd(DUMPS / "test_ps2_device.vcd").events("uio_out")
    oe = Vcd(DUMPS / "test_ps2_device.vcd").events("uio_oe")
    edges = [t for t, v in bit_series(Vcd(DUMPS / "test_ps2_device.vcd").events("clk"), 0) if v == 1]
    clk_low = sample(bit_series(out, 1), edges)
    clk_oe = sample(bit_series(oe, 1), edges)
    dat_low = sample(bit_series(out, 0), edges)
    dat_oe = sample(bit_series(oe, 0), edges)
    # Open-drain with pull-ups: the bus is low only when the device pulls it low.
    ps2_clk = [0 if (clk_oe[i] and not clk_low[i]) else 1 for i in range(len(edges))]
    ps2_dat = [0 if (dat_oe[i] and not dat_low[i]) else 1 for i in range(len(edges))]
    start = first(ps2_clk, lambda v, i: v[i] == 0 and v[i - 1] == 1,
                  start=run_start("test_ps2_device"))
    if start is None:
        raise SystemExit("no PS/2 clock edge")
    a, b = max(start - 100, 0), min(start + 16500, len(ps2_clk))
    log = [(0.02, "device pulls the clock low after idle"),
           (0.35, "one full 11-bit frame: start, 8 data, odd parity, stop"),
           (0.78, "bit period 9 x WAIT 167 = 1503 clocks, ~10.5 kHz")]
    return Scene("PS/2 device, open-drain",
                 "device-to-host frame, no dedicated PS/2 logic, no external adapter",
                 [("CLK", AMBER, ps2_clk[a:b]), ("DATA", GREEN, ps2_dat[a:b])], log,
                 "test_ps2_device · programs/ps2_device.s", grid=1503, cell="bit cell = 1503 clocks")


def usb_scene() -> Scene:
    line, _ = load("test_usb_data_packet", "uio_out", 0)
    strobe, _ = load("test_usb_data_packet", "uo_out", 0)
    first_beat = first(strobe, lambda v, i: v[i] == 1 and v[i - 1] == 0,
                       start=run_start("test_usb_data_packet"))
    if first_beat is None:
        raise SystemExit("no bit strobe")
    # The last rising edge of the strobe, not the last cycle it happens to be high:
    # the pin can be left at 1 by later testbench activity.
    last_beat = max(i for i in range(1, len(strobe))
                    if strobe[i] == 1 and strobe[i - 1] == 0)
    a, b = max(first_beat - 15, 0), min(last_beat + 25, len(line))
    log = [(0.01, "SYNC 0x80: eight bits, LSB first"),
           (0.20, "PID 0xC3 (DATA0), then payload 0x11 0x22"),
           (0.62, "CRC-16/USB over the payload, complemented, low byte first"),
           (0.86, "NRZI: 0 is a transition, 1 holds; a 0 is stuffed after six ones")]
    print(f"usb window {a}..{b} cycles, {len(line)} sampled, "
          f"line toggles {sum(1 for k in range(a + 1, b) if line[k] != line[k - 1])}")
    return Scene("Low-speed USB data packet",
                 "line coding and checksum in hardware; firmware only picks the bytes",
                 [("line", VIOLET, line[a:b])], log,
                 "test_usb_data_packet · programs/usb_data_tx.s",
                 grid=168, cell="byte = 168 clocks (21 per bit) at 1.52 Mbit/s")


def capture_scene() -> Scene:
    ui, _ = load("test_capture_roll", "ui_in", 0)
    start = first(ui, lambda v, i: v[i] != v[i - 1],
                  start=run_start("test_capture_roll"))
    if start is None:
        raise SystemExit("no pin change")
    a, b = max(start - 30, 0), min(start + 1300, len(ui))
    log = [(0.02, "the pin changes; the capture engine samples it every clock"),
           (0.30, "each edge is stored as {timer byte, uio_in, ui_in}"),
           (0.70, "49 edges into 32 slots: roll mode overwrites the oldest"),
           (0.90, "so the window that just happened is still there to drain")]
    return Scene("Capture buffer, roll mode",
                 "the same chip records a live bus instead of driving it",
                 [("ui[0]", BLUE, ui[a:b])], log,
                 "test_capture_roll · programs/capture_demo.s", grid=0,
                 cell="32 entries, 8-bit timestamps")


# ---------------------------------------------------------------------- drawing
def frame(scene: Scene, play: float) -> Image.Image:
    fig = plt.figure(figsize=(W, H), dpi=DPI)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.10, 0.17, 0.86, 0.40])
    ax.set_facecolor(BG)

    n = len(scene.rows[0][2])
    h = 0.62
    cut = max(int(play * n), 2)
    for r, (label, colour, values) in enumerate(scene.rows):
        y = len(scene.rows) - 1 - r
        xs = np.arange(n)
        ys = np.array(values, dtype=float) * h + y
        ax.step(xs, ys, where="post", color=RULE, linewidth=2.3)
        ax.step(xs[:cut], ys[:cut], where="post", color=colour, linewidth=2.3)
        ax.annotate(label, xy=(0, y + h / 2), xycoords=("axes fraction", "data"),
                    xytext=(-8, 0), textcoords="offset points",
                    ha="right", va="center", fontsize=9, color=INK,
                    family="monospace")

    if scene.grid:
        for x in range(0, n, scene.grid):
            ax.axvline(x, color=RULE, linewidth=0.7, zorder=0)
    ax.axvline(play * n, color=INK, linewidth=1.0, alpha=0.5)

    ax.set_xlim(0, n)
    ax.set_ylim(-0.30, len(scene.rows) + 0.30)
    ax.set_xticks([])
    ax.set_yticks([])
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)

    fig.text(0.05, 0.935, scene.title, fontsize=13, color=INK, weight="bold")
    fig.text(0.05, 0.892, scene.sub, fontsize=8.2, color=MID)
    if scene.cell:
        fig.text(0.95, 0.940, scene.cell, fontsize=7.0, color=MID, ha="right",
                 family="monospace")

    # Log lines: each appears when the playhead reaches it, so the animation
    # explains the waveform as it draws rather than all at once.
    for k, (at, text) in enumerate(scene.log):
        if play >= at:
            fig.text(0.05, 0.60 - 0.043 * k, text, fontsize=7.4, color=INK,
                     family="monospace")

    fig.text(0.05, 0.075, scene.footer, fontsize=7.0, color=MID)
    fig.patches.append(plt.Rectangle((0.05, 0.035), 0.90, 0.007,
                                     transform=fig.transFigure, color=RULE))
    fig.patches.append(plt.Rectangle((0.05, 0.035), 0.90 * play, 0.007,
                                     transform=fig.transFigure, color=BLUE))

    fig.canvas.draw()
    img = Image.fromarray(np.asarray(fig.canvas.buffer_rgba())[:, :, :3])
    plt.close(fig)
    return img


def main() -> int:
    scenes = []
    for build in (uart_scene, i2c_scene, ps2_scene, usb_scene, capture_scene):
        try:
            scenes.append(build())
        except (SystemExit, FileNotFoundError) as exc:
            print(f"skip {build.__name__}: {exc}")
    if not scenes:
        print("no dumps found; see the docstring")
        return 1

    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    frames: list[Image.Image] = []
    for i, scene in enumerate(scenes):
        for k in range(FRAMES):
            frames.append(frame(scene, k / (FRAMES - 1)))
        frames += [frames[-1]] * HOLD
        frames[-1].save(FRAMES_DIR / f"scene{i + 1}.png")
        print(f"scene {i + 1}: {scene.title}")

    frames[0].save(OUT, save_all=True, append_images=frames[1:],
                   duration=95, loop=0, optimize=True)
    print("wrote", OUT, f"{len(frames)} frames, {OUT.stat().st_size // 1024} KiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
