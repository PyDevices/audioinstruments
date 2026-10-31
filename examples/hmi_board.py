# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The rack on a board, open to front panels over Wi-Fi, with its own screen.

    mpftp run examples/hmi_board.py -d COM55          # starts and returns

Builds play_audio's movement 4 (Modular55: two VCOs, the ladder, the
envelope, the VCA) without importing the other nineteen instruments, plays
it through ``board_config.pcm_out``, loops the pattern, serves panels on
port 9000 (a phone opens http://<board>:9000/), and opens the LVGL panel on
the board's own display over the in-process transport. The screen and the
phone follow each other through the device, which is the point.

Prints a status line every five seconds with the cost of a block.
"""

import gc
import sys
import time

if "/lib" not in sys.path:
    sys.path.append("/lib")

import hmilink  # noqa: E402
from audioinstruments._rack import (  # noqa: E402
    MidiCVModule,
    Modular55Envelope,
    Modular55LowPass,
    Modular55VCA,
    Modular55VCO,
    Rack,
)
from audioinstruments._rack.core.signal import INT16_DTYPE, np  # noqa: E402
from audioinstruments._rack.hmi import RackModel  # noqa: E402
from hmilink import local, tcp  # noqa: E402

SAMPLE_RATE = 48000
BLOCK_SIZE = 64
BLOCKS_PER_SECOND = SAMPLE_RATE / BLOCK_SIZE
PORT = 9000
PAGE = "/lib/rackview/index.html"
SCREEN = True
US_PER_BLOCK = BLOCK_SIZE * 1000000 // SAMPLE_RATE


def set_params(module, **params):
    for name, value in params.items():
        module.set_param(name, value)


def note_events(midi, pattern, step_blocks, hold, velocity):
    events = []
    for idx, pitch in enumerate(pattern):
        t_on = idx * step_blocks
        t_off = t_on + int(step_blocks * hold)
        events.append((t_on, lambda p=pitch: midi.note_on(p, velocity)))
        events.append((t_off, lambda p=pitch: midi.note_off(p)))
    return events


def movement_04():
    """Modular55: two VCOs into the low-pass ladder and the VCA (play_audio's movement 4)."""
    rack = Rack(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE)
    midi = rack.add_module(MidiCVModule("midi_cv"))
    vco1 = rack.add_module(Modular55VCO("vco1"))
    vco2 = rack.add_module(Modular55VCO("vco2"))
    lpf = rack.add_module(Modular55LowPass("lpf"))
    env = rack.add_module(Modular55Envelope("env"))
    vca = rack.add_module(Modular55VCA("vca"))
    rack.connect(midi.pitch_out, vco1.freq_cv1, color="#9b59b6")
    rack.connect(midi.pitch_out, vco2.freq_cv1, color="#9b59b6")
    rack.connect(midi.gate_out, env.trigger_in, color="#3498db")
    set_params(vco1, range=1.0, fine=0.0)
    set_params(vco2, range=0.0, pw=0.40, fine=0.02)
    rack.connect(vco1.saw_out, lpf.audio_in, color="#e74c3c")
    rack.connect(lpf.audio_out, vca.audio_in_pos, color="#2ecc71")
    rack.connect(vco2.rect_out, vca.audio_in_neg, color="#3498db")
    rack.connect(env.env_out, lpf.cv1_in, color="#f1c40f")
    set_params(lpf, fixed_cv=-0.4, regen=0.65, drive=1.6)
    rack.connect(env.env_out, vca.cv1_in, color="#f39c12")
    set_params(vca, mode=1.0, fixed_cv=0.0)
    set_params(env, t1=0.006, t2=0.22, es=0.18, t3=0.15)
    rack.connect(vca.audio_out_pos, rack.master_left_in, color="#2ecc71")
    rack.connect(vca.audio_out_pos, rack.master_right_in, color="#2ecc71")
    pattern = [43, 43, 46, 48, 43, 41, 43, 55, 53, 50, 48, 46]
    seconds = (len(pattern) * 85) / BLOCKS_PER_SECOND + 0.6
    return rack, note_events(midi, pattern, 85, 0.72, 125), seconds


def open_pcm():
    try:
        import board_config
        from audiodev import AudioFormat
    except ImportError as e:
        print("no live output:", e)
        return None
    pcm = board_config.pcm_out(AudioFormat(SAMPLE_RATE, 2, 16), latency="low")
    pcm.open()
    pcm.set_volume(90)
    pcm.mute(False)
    print("Live output: %s" % (pcm.format,))
    return pcm


def main():
    rack, events, seconds = movement_04()
    loop_blocks = int(seconds * BLOCKS_PER_SECOND)
    queue = sorted(events, key=lambda e: e[0])
    pcm = open_pcm()
    channels = pcm.format.channels if pcm is not None else 2
    ba = bytearray(BLOCK_SIZE * channels * 2)
    interleaved = np.frombuffer(ba, dtype=INT16_DTYPE)
    view_l = interleaved[0::2]
    view_r = interleaved[1::2]

    model = RackModel(rack, name="movement 4: modular55")
    device = hmilink.Device(model)
    device.add(tcp.serve(PORT, page=PAGE))
    try:
        import network

        print("hmilink: http://%s:%d/" % (network.WLAN(network.STA_IF).ifconfig()[0], PORT))
    except Exception as e:  # noqa: BLE001
        print("hmilink: port %d (%s)" % (PORT, e))

    screen = None
    if SCREEN:
        try:
            from rackview.lvgl_panel import open_local_panel

            lst = device.add(local.serve())
            screen = open_local_panel(local.connect(lst), title="DEV-KIT")
            print("screen: LVGL panel on the board's display")
        except Exception as e:  # noqa: BLE001
            print("screen: not opened:", repr(e))

    block = 0
    next_event = 0
    step_us = poll_us = n = 0
    report_at = time.ticks_us()
    pace = time.ticks_us()
    while True:
        pos = block % loop_blocks
        if pos == 0:
            next_event = 0
        while next_event < len(queue) and queue[next_event][0] <= pos:
            queue[next_event][1]()
            next_event += 1
        t0 = time.ticks_us()
        rack.step()
        t1 = time.ticks_us()
        view_l[:] = np.clip(rack.output_buffer_left * 27000.0, -27000.0, 27000.0)
        view_r[:] = np.clip(rack.output_buffer_right * 27000.0, -27000.0, 27000.0)
        if pcm is not None:
            pcm.write(ba)
        t2 = time.ticks_us()
        device.poll()
        if screen is not None:
            screen.poll()
        t3 = time.ticks_us()
        step_us += time.ticks_diff(t1, t0)
        poll_us += time.ticks_diff(t3, t2)
        n += 1
        block += 1
        if block % 128 == 0:
            gc.collect()
        if pcm is None:
            pace += US_PER_BLOCK
            ahead = time.ticks_diff(pace, time.ticks_us())
            if ahead > 2000:
                time.sleep_ms(ahead // 1000)
        now = time.ticks_us()
        if time.ticks_diff(now, report_at) >= 5000000:
            report_at = now
            print(
                "block %d: step %d us, poll %d us (of %d); links %d, ops %d, tele %d sent %d dropped, free %d"
                % (
                    block,
                    step_us // n,
                    poll_us // n,
                    US_PER_BLOCK,
                    len(device.links),
                    device.stats["ops"],
                    device.stats["tele"],
                    device.stats["tele_dropped"],
                    gc.mem_free(),
                )
            )
            step_us = poll_us = n = 0


main()
