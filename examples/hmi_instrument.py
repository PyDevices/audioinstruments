# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play an instrument demo's phrase, live, with its patches and knobs open to panels.

    micropython examples/hmi_instrument.py                      # poly6, port 9000, live audio
    python examples/hmi_instrument.py --demo poly106_demo --no-live --seconds 60 --screen
    mpftp run examples/hmi_instrument.py -d COM55               # on a board, with its screen
    micropython examples/hmi_instrument.py --pump --patch-every 30 --seconds 1800

The demo module (``poly6_demo`` by default) supplies the instrument's name
and its sections: real patches in audible ranges, the same phrase
``examples/<demo>.py`` renders and checks. They loop here. The instrument
is an ``hmilink`` model (``vrack.hmi.InstrumentModel``): a panel changes
the patch, moves the macros, turns the knobs inside the voices, plugs and
unplugs cables, and every other panel follows. A phone opens
http://<host>:9000/.

Every five seconds a line says what a buffer costs.

With ``--pump`` (the default on a board that has the audio pump) the
instrument's graph is the sample the pump plays: it renders on the pump's own
thread, and this loop only takes turns at the Python side (notes, modulation,
voices parking) with ``inst.fill()``. A turn has no deadline of its own, so the
screen and the links can take their time; what the pump needs is a turn every
few blocks. The five-second line then says how many bytes the output was short
of (``starved``, after the first second's priming, which is shown on its own),
what the pump spends on a block, and how long a turn of this loop took.
"""

import gc
import struct
import sys
import time

for p in ("lib", "examples", "/lib"):
    if p not in sys.path:
        sys.path.append(p)

import audiocore  # noqa: E402
import hmilink  # noqa: E402
import vrack.adapter as adapter  # noqa: E402
from hmilink import tcp  # noqa: E402
from vrack.hmi import InstrumentModel  # noqa: E402

try:
    from time import sleep_ms, ticks_diff, ticks_us
except ImportError:  # CPython

    def ticks_us():
        return time.monotonic_ns() // 1000

    def ticks_diff(a, b):
        return a - b

    def sleep_ms(ms):
        time.sleep(ms / 1000.0)


BLOCK = 128  # frames the graph renders a pull at
ON_BOARD = sys.platform not in ("linux", "win32", "darwin")


def parse(argv):
    opts = {
        "demo": "poly6_demo",
        "port": 9000,
        "live": True,
        "seconds": 0,
        "screen": ON_BOARD,
        "page": "/lib/rackview/index.html" if ON_BOARD else "examples/rackview/index.html",
        "wav": None,
        "voices": None,  # the instrument's own count unless said; a P4 holds the Poly6 at two or three
        "telemetry_hz": 20,  # a board's screen redraws on every telemetry frame; 5 is kind to it
        "pump": None,  # the graph on the audio pump; on by default where there is one
        "patch_every": 0,  # seconds between patch changes on top of the phrase's own
        "volume": 90,
    }
    it = iter(argv)
    for arg in it:
        if arg == "--voices":
            opts["voices"] = int(next(it))
        elif arg == "--telemetry-hz":
            opts["telemetry_hz"] = int(next(it))
        elif arg == "--demo":
            opts["demo"] = next(it)
        elif arg == "--port":
            opts["port"] = int(next(it))
        elif arg == "--no-live":
            opts["live"] = False
        elif arg == "--seconds":
            opts["seconds"] = float(next(it))
        elif arg == "--screen":
            opts["screen"] = True
        elif arg == "--no-screen":
            opts["screen"] = False
        elif arg == "--page":
            opts["page"] = next(it)
        elif arg == "--wav":
            opts["wav"] = next(it)
        elif arg == "--pump":
            opts["pump"] = True
        elif arg == "--no-pump":
            opts["pump"] = False
        elif arg == "--patch-every":
            opts["patch_every"] = float(next(it))
        elif arg == "--volume":
            opts["volume"] = int(next(it))
    return opts


def phrase(demo):
    """The demo's sections as timed events, and the length of one pass."""
    events = []
    t = 0.2
    for _name, patch, write in demo.SECTIONS:
        events.append((t - 0.05, "patch", patch, 0))
        sec_events, t = write(t)
        events.extend(sec_events)
    events.sort(key=lambda e: (e[0], e[1] != "patch", e[1] == "on"))
    return events, t + 0.6


def fire(inst, ev):
    kind = ev[1]
    if kind == "patch":
        inst.program_change(ev[2])
    elif kind == "macro":
        inst.set_macro(ev[2], ev[3])
    elif kind == "control":
        inst.patch.set_control(inst.voice_pool, ev[2], ev[3])
    elif kind == "cc":
        inst.control_change(ev[2], ev[3])
    elif kind == "bend":
        inst.pitch_bend(ev[2])
    elif kind == "on":
        inst.note_on(ev[2], ev[3])
    elif kind == "off":
        inst.note_off(ev[2])


def open_pcm(rate):
    try:
        import board_config
        from audiodev import AudioFormat
    except ImportError as e:
        print("no live output:", e)
        return None
    pcm = board_config.pcm_out(AudioFormat(rate, 2, 16), latency="low")
    pcm.open()
    pcm.set_volume(90)
    pcm.mute(False)
    print("Live output: %s" % (pcm.format,))
    return pcm


def can_pump():
    """True when this build plays a sample on the audio pump and has ``audiograph``."""
    try:
        import audiograph  # noqa: F401
        from audiodev import pump

        return pump.on_board()
    except Exception:  # noqa: BLE001
        return False


class PumpPlayer:
    """The graph on the board's audio output, played by the audio pump."""

    def __init__(self, rate, graph, volume):
        from audiodev import AudioFormat, pump
        from boarddev import pcm_out

        fmt = AudioFormat(rate, 2, 16)
        transport = pcm_out(fmt)
        while transport is not None and getattr(transport, "wire", None) is None:
            transport = getattr(transport, "_inner", None)
        if transport is None:
            raise RuntimeError("no I2S output for the pump on this board")
        self._pump = pump
        self.driver = pump.BusioDriver(
            transport.wire,
            fmt,
            power=getattr(transport, "audio_power", None),
            volume=volume,
            transport=transport,
        )
        pump.owner().play(self, graph, driver=self.driver, raises=True)
        # The pump writes its status words into this bytearray. Holding it
        # keeps the words readable after the pump stops, when STACK_FREE is
        # written: the pump fills that word in only as it finishes.
        self._status = self.driver.status()
        print("Live output: the graph on the audio pump, %s" % (fmt,))

    def starved(self):
        return self.driver.starved()

    def words(self, *index):
        """Words of the pump's status block (``BLOCKS`` is 0, ``PULL_US`` 12,
        ``SINK_TIMEOUTS`` 14, ``STACK_FREE`` 19, ``MAX_PULL_US`` 20)."""
        st = self._status
        if st is None:
            return (0,) * len(index)
        return tuple(struct.unpack_from("<Q", st, 8 * i)[0] for i in index)

    def close(self):
        """Stop the pump; returns the least stack its task had free, in bytes."""
        self._pump.owner().stop(self)
        return self.words(19)[0]


def run_pump(opts, inst, events, length, device, screen):
    """The loop with the graph on the pump: a turn whenever there is one to take."""
    import audiopump

    rate = inst.sample_rate
    graph = inst.output
    player = PumpPlayer(rate, graph, opts["volume"])
    block = BLOCK
    lead = block  # a turn's notes land in the block after it
    loop_frames = int(length * rate)
    patches = len(inst.patches)
    patch = 0
    every = int(opts["patch_every"] * rate)
    next_patch = every
    base = graph.sounding()[1]
    fired = 0
    k = 0
    turns = idle = 0
    turn_max = 0
    primed = None
    started = ticks_us()
    report_at = collected = last = started
    elapsed = 0  # microseconds, summed: ticks_diff() only spans about 537 s
    last_blocks = last_pull = 0
    starved_log = []  # (seconds, starved bytes after priming), kept in RAM
    try:
        while True:
            t0 = ticks_us()
            song = (graph.sounding()[1] - base) & 0xFFFFFFFF
            target = song + lead
            busy = fired < target
            while fired < target:
                pos = fired % loop_frames
                if pos == 0:
                    k = 0
                end = min(pos + target - fired, loop_frames)
                while k < len(events) and events[k][0] * rate < end:
                    fire(inst, events[k])
                    k += 1
                fired += end - pos
                if every and fired >= next_patch:
                    next_patch += every
                    patch = (patch + 1) % patches
                    inst.program_change(patch)
            blocks = inst.fill()
            inst.hold()  # a panel's moves land together
            try:
                device.poll()
                if screen is not None:
                    screen.poll()
            finally:
                inst.commit()
            spent = ticks_diff(ticks_us(), t0)
            turns += 1
            if spent > turn_max:
                turn_max = spent
            if not blocks and not busy:
                idle += 1
                if ticks_diff(ticks_us(), collected) >= 500000:
                    # Between turns, so a collection never holds one up.
                    gc.collect()
                    collected = ticks_us()
                else:
                    sleep_ms(1)
            now = ticks_us()
            elapsed += ticks_diff(now, last)
            last = now
            if primed is None and elapsed >= 1000000:
                primed = player.starved()
                print("priming: %d bytes starved in the first second" % primed)
            if ticks_diff(now, report_at) >= 5000000:
                report_at = now
                pulled, pull_us, max_pull, sink_to = player.words(0, 12, 20, 14)
                n = pulled - last_blocks
                avg = (pull_us - last_pull) // n if n else 0
                last_blocks, last_pull = pulled, pull_us
                late = player.starved() - (primed or 0)
                secs = elapsed // 1000000
                starved_log.append((secs, late))
                q = graph.stats()
                lock = audiopump.lock_stats()
                print(
                    "t %d s: starved %d bytes, sink timeouts %d; pull %d us avg, %d max"
                    " (block %d us); "
                    "turns %d (%d idle), worst %d us; queue high %d, overflows %d, splits %d; "
                    "ctrl wait max %d us; links %d, tele %d sent %d dropped, free %s"
                    % (
                        secs,
                        late,
                        sink_to,
                        avg,
                        max_pull,
                        block * 1000000 // rate,
                        turns,
                        idle,
                        turn_max,
                        q["high_water"],
                        q["overflows"],
                        q["splits"],
                        lock[5],
                        len(device.links),
                        device.stats["tele"],
                        device.stats["tele_dropped"],
                        gc.mem_free() if hasattr(gc, "mem_free") else "-",
                    )
                )
                turns = idle = turn_max = 0
            if opts["seconds"] and elapsed >= opts["seconds"] * 1000000:
                break
    except KeyboardInterrupt:
        pass
    finally:
        stack_free = player.close()
    print("starved after priming, every 5 s:", starved_log)
    print("pump task stack: %d bytes never used" % stack_free)


def main(argv):
    opts = parse(argv)
    demo = __import__(opts["demo"])
    rate = demo.RATE
    buffer_frames = demo.BUFFER
    voice = opts["demo"].replace("_demo", "")
    on_cpython = sys.implementation.name == "cpython"
    extra = {"voices": opts["voices"]} if opts["voices"] else {}
    if opts["pump"] is None:
        opts["pump"] = opts["live"] and not on_cpython and can_pump()
    if opts["pump"]:
        inst = adapter.create(rate, voice=voice, output="graph", block_size=BLOCK, **extra)
    else:
        inst = adapter.create(
            rate, voice=voice, output="pull" if on_cpython else "ring", ring_blocks=2, **extra
        )
    events, length = phrase(demo)
    pcm = open_pcm(rate) if opts["live"] and not opts["pump"] else None
    wav = None
    if opts["wav"]:
        import play_audio

        wav = play_audio.WavWriter(opts["wav"], sample_rate=rate, channels=2)

    model = InstrumentModel(inst, name="%s: %s" % (voice, opts["demo"]))
    device = hmilink.Device(model, telemetry_hz=opts["telemetry_hz"])
    device.add(tcp.serve(opts["port"], page=opts["page"]))
    try:
        import network

        print("hmilink: http://%s:%d/" % (network.WLAN(network.STA_IF).ifconfig()[0], opts["port"]))
    except Exception:  # noqa: BLE001
        print("hmilink: serving on port %d, page %s" % (opts["port"], opts["page"]))
    print(
        "instrument: %s, %d modules, %d cables, %d patches, %d macros, phrase %.1f s"
        % (
            voice,
            len(inst.rack.modules),
            len(inst.rack.cables),
            len(inst.patches),
            len(inst.macro_labels),
            length,
        )
    )

    screen = None
    if opts["screen"]:
        try:
            from hmilink import local
            from rackview.lvgl_panel import open_local_panel

            lst = device.add(local.serve())
            screen = open_local_panel(local.connect(lst), title=voice)
            print("screen: LVGL panel on this display")
        except Exception as e:  # noqa: BLE001
            print("screen: not opened:", repr(e))

    if opts["pump"]:
        try:
            run_pump(opts, inst, events, length, device, screen)
        finally:
            device.close()
            inst.deinit()
        print("done")
        return

    us_per_buffer = buffer_frames * 1000000 // rate
    frame = 0
    k = 0
    render_us = poll_us = n = 0
    report_at = ticks_us()
    last = ticks_us()
    elapsed = 0  # microseconds, summed: ticks_diff() only spans about 537 s
    pace = ticks_us()
    loop_frames = int(length * rate)
    try:
        while True:
            pos = frame % loop_frames
            if pos == 0:
                k = 0
            end = pos + buffer_frames
            while k < len(events) and events[k][0] * rate < end:
                fire(inst, events[k])
                k += 1
            t0 = ticks_us()
            inst.fill()
            _, data = audiocore.get_buffer(inst.output)
            t1 = ticks_us()
            if pcm is not None:
                pcm.write(data)
            if wav is not None:
                wav.write(bytes(data))
            t2 = ticks_us()
            device.poll()
            if screen is not None:
                screen.poll()
            t3 = ticks_us()
            render_us += ticks_diff(t1, t0)
            poll_us += ticks_diff(t3, t2)
            n += 1
            frame += buffer_frames
            if n % 64 == 0:
                gc.collect()
            if pcm is None:
                pace += us_per_buffer
                ahead = ticks_diff(pace, ticks_us())
                if ahead > 2000:
                    sleep_ms(ahead // 1000)
            now = ticks_us()
            elapsed += ticks_diff(now, last)
            last = now
            if ticks_diff(now, report_at) >= 5000000:
                report_at = now
                print(
                    "buffer %d: render %d us, poll %d us (of %d); links %d, ops %d, tele %d sent %d dropped, free %s"
                    % (
                        n,
                        render_us // n,
                        poll_us // n,
                        us_per_buffer,
                        len(device.links),
                        device.stats["ops"],
                        device.stats["tele"],
                        device.stats["tele_dropped"],
                        gc.mem_free() if hasattr(gc, "mem_free") else "-",
                    )
                )
                render_us = poll_us = n = 0
            if opts["seconds"] and elapsed >= opts["seconds"] * 1000000:
                break
    except KeyboardInterrupt:
        pass
    finally:
        device.close()
        if wav is not None:
            wav.close()
        if pcm is not None:
            try:
                pcm.drain()
            except Exception:  # noqa: BLE001
                pass
            pcm.close()
        inst.deinit()
    print("done")


if __name__ == "__main__":
    main(getattr(sys, "argv", [None])[1:])  # a board's MicroPython has no argv
