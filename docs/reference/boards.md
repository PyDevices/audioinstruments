# Boards

Which instruments play on which board, and how much room each leaves. Every
instrument was timed on one board of each chip family, and three families
can't play them at all; the table under the first one says why.

## What plays where

Each cell is the most notes held, of 1, 6 and 10, that render inside the
block, and in brackets the share of the block left over at that count. "over"
means even one note takes longer than the block, with what one note costs.
Voices is how many the instrument was built with, up to the pump's 24, and
Heap the memory it takes once built with them, about the same on every
board, so a board needs PSRAM or SDRAM to hold more than one or two. An
instrument with one voice holds one note by design, and `poly5`, with five,
was timed with one note.

| Instrument | Voices | Heap | ESP32-P4 | STM32H747 | ESP32-S3 | ESP32 | RP2350 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `acid303` | 1 | 181 KB | 1 (65%) | 1 (88%) | 1 (33%) | 1 (2%) | 1 (38%) |
| `bass_pedals` | 1 | 188 KB | 1 (81%) | 1 (82%) | 1 (62%) | 1 (25%) | 1 (36%) |
| `clavichord` | 10 | 571 KB | 1 (68%) | 1 (66%) | over (100%) | over (179%) | over (131%) |
| `combo_organ` | 24 | 1535 KB | 10 (27%) | 10 (31%) | 6 (19%) | 1 (2%) | 1 (15%) |
| `compact_organ` | 24 | 913 KB | 6 (6%) | 1 (49%) | 1 (10%) | over (178%) | over (180%) |
| `duo20` | 8 | 608 KB | 1 (64%) | 1 (72%) | 1 (16%) | over (138%) | over (113%) |
| `duosynth` | 1 | 305 KB | 1 (60%) | 1 (62%) | 1 (17%) | over (159%) | over (154%) |
| `electric_grand70` | 10 | 590 KB | 6 (33%) | 6 (23%) | over (115%) | over (186%) | over (105%) |
| `electric_piano` | 10 | 546 KB | 10 (53%) | 10 (50%) | 1 (53%) | 1 (5%) | 1 (19%) |
| `electronic_drums5` | 8 | 588 KB | 6 (63%) | 6 (61%) | 6 (19%) | over (109%) | 1 (10%) |
| `hybrid_mono` | 8 | 468 KB | 1 (73%) | 6 (33%) | 1 (45%) | 1 (11%) | 1 (31%) |
| `mono101` | 1 | 280 KB | 1 (78%) | 1 (79%) | 1 (57%) | 1 (17%) | 1 (27%) |
| `mono_one` | 8 | 584 KB | 1 (68%) | 1 (68%) | 1 (28%) | over (135%) | over (123%) |
| `mono_synth` | 1 | 289 KB | 1 (74%) | 1 (75%) | 1 (46%) | 1 (2%) | 1 (11%) |
| `patch2600` | 8 | 1478 KB | 1 (66%) | 1 (67%) | 1 (27%) | out of memory | over (140%) |
| `poly106` | 6 | 477 KB | 6 (6%) | 6 (10%) | 1 (39%) | over (122%) | over (115%) |
| `poly5` | 5 | 495 KB | 1 (69%) | 1 (70%) | 1 (36%) | over (124%) | over (111%) |
| `poly6` | 6 | 539 KB | 1 (58%) | 1 (59%) | 1 (17%) | over (164%) | over (162%) |
| `poly8` | 8 | 712 KB | 1 (62%) | 1 (60%) | 1 (14%) | over (169%) | over (157%) |
| `poly80` | 8 | 1008 KB | 1 (4%) | 1 (40%) | over (172%) | over (314%) | over (259%) |
| `polya6` | 16 | 2119 KB | 1 (37%) | 1 (46%) | over (113%) | over (162%) | over (203%) |
| `polyxa` | 8 | 649 KB | 1 (66%) | 1 (65%) | 1 (27%) | over (144%) | over (135%) |
| `reed_piano` | 10 | 667 KB | 10 (8%) | 10 (8%) | 1 (57%) | 1 (6%) | 1 (14%) |
| `reed_piano200a` | 10 | 646 KB | 10 (57%) | 10 (54%) | 10 (3%) | 1 (25%) | 1 (31%) |
| `rhythm606` | 7 | 626 KB | 6 (64%) | 6 (64%) | 6 (17%) | 1 (19%) | 1 (33%) |
| `rhythm78` | 15 | 734 KB | 10 (48%) | 10 (46%) | 1 (49%) | over (113%) | over (102%) |
| `rhythm808` | 16 | 862 KB | 10 (11%) | 10 (11%) | 1 (50%) | over (113%) | 1 (1%) |
| `rhythm909` | 11 | 1043 KB | 6 (28%) | 6 (27%) | 1 (47%) | over (118%) | over (105%) |
| `state_variable_mono` | 8 | 840 KB | 1 (69%) | 6 (0%) | 1 (32%) | over (130%) | over (113%) |
| `string_ensemble` | 24 | 992 KB | 1 (50%) | 6 (6%) | over (102%) | over (206%) | over (211%) |
| `tonewheel3` | 16 | 940 KB | 6 (15%) | 6 (20%) | 1 (13%) | over (180%) | over (160%) |
| `vocoder330` | 12 | 1468 KB | 1 (48%) | 1 (47%) | over (106%) | out of memory | over (223%) |
| `west_coast_synth` | 8 | 810 KB | 1 (74%) | 6 (1%) | 1 (46%) | over (106%) | 1 (4%) |


The boards, all on development builds of MicroPython 1.30 with audiodsp 0.6.16
compiled in, at 48 kHz in 128-frame blocks, so 2667 µs a block:

| Column | Board | Clock | Memory |
| --- | --- | --- | --- |
| ESP32-P4 | Waveshare ESP32-P4-WIFI6-DEV-KIT | 400 MHz, two cores | 32 MB PSRAM |
| STM32H747 | Arduino GIGA R1 WiFi | 480 MHz Cortex-M7 | 8 MB SDRAM |
| ESP32-S3 | Waveshare ESP32-S3-Touch-LCD-7 | 240 MHz, two cores | 8 MB PSRAM |
| ESP32 | Adafruit QT Py ESP32 Pico | 240 MHz, two cores | 2 MB PSRAM |
| RP2350 | Pimoroni Pico Plus 2 W | 150 MHz Cortex-M33 | 8 MB PSRAM |

On the ESP32 the instruments ran from `.mpy` files on the board's file
system rather than frozen into the firmware, so their code took heap as well,
and with 2 MB of PSRAM `polya6` built six voices, `patch2600` had no room
for its graph, and `vocoder330` didn't fit at all.

On the ESP32, S3 and P4 the instrument renders on its own core, so the space
left over is spare. On the STM32H747 and the RP2350 the instrument shares
the only core with your program, so the space left is all your program gets.

## Chips that can't play them

| Chip | Board tried | Why not |
| --- | --- | --- |
| RP2040 | Waveshare RP2040-Touch-LCD-1.28 | 264 KB of RAM, of which about 224 KB is free once audiodsp is in, and no floating point unit. `acid303` and `bass_pedals` fit and take 509% and 708% of the block for one note; every other instrument needs more heap than the chip has. |
| nRF52840 | Seeed XIAO nRF52840 Sense | 1 MB of flash: audiodsp with ulab is 382 KB larger than the space for firmware, before an instrument. |
| SAMD51 | Adafruit NeoTrellis M4, on CircuitPython | CircuitPython has no `audiograph`, the node the instruments render on, and its 127 KB of free heap is under the 180 KB or so the smallest instrument takes. |

## How it was measured

[performance.md](../how-it-works/performance.md#on-a-board) has the method,
and [board-timings.csv](board-timings.csv) every figure behind the table: per
board, instrument and note count, the voices built, the heap taken, and the
µs a block for the graph and for the whole `step()`.
