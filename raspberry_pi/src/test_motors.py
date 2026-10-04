#!/usr/bin/env python3
"""
test_motors.py — L298N + 4 motors, 4-wheel car test rig for Raspberry Pi 4 (BCM2711).

WHAT THIS IS
------------
A configurable motion-test harness for a 4-wheel skid-steer ("car") chassis driven by a
single L298N dual H-bridge: forward / reverse, spins, arcs, slalom, square, figure-8,
a brake-vs-coast demonstration, a wiring self-check, and interactive teleop.

THE 4-MOTORS-ON-2-CHANNELS REALITY (read this first)
----------------------------------------------------
An L298N has TWO H-bridges, not four. To drive four wheels you wire the two motors on
each side IN PARALLEL onto one channel:

    channel A (ENA, IN1, IN2 -> OUT1, OUT2)  =  LEFT  pair   (both left motors)
    channel B (ENB, IN3, IN4 -> OUT3, OUT4)  =  RIGHT pair   (both right motors)

So this script thinks in LEFT and RIGHT, not in four wheels. That is exactly right for
skid-steer: turning is done by driving the two sides at different speeds, and a spin in
place is one side forward while the other reverses. If you later want four independent
wheels you need a second L298N (or one driver per motor) — the config is written so that
`pins` describes two sides and would accept a second pair.

Speed control needs the ENA/ENB **jumpers removed** from the L298N so the Pi's PWM
reaches the enable pins. With the jumpers left in, speed is 100% or nothing.

WIRING (chosen and verified free on this exact machine — see "PIN SAFETY" below)
------------------------------------------------------------------------------
    signal          GPIO    header pin      L298N terminal
    LEFT  ENA        12        32              ENA
    LEFT  IN1        17        11              IN1
    LEFT  IN2        27        13              IN2
    RIGHT IN3        22        15              IN3
    RIGHT IN4        23        16              IN4
    RIGHT ENB        13        33              ENB
    GND             (any)      6,9,14,..      GND     <-- MANDATORY, common ground

Power:
  * Motor supply into the L298N's +12V/VS screw terminal from a **separate battery pack**
    (2S Li-ion 7.4 V, or 6xAA 9 V). The L298N drops ~1.8-2 V, so 7.4 V in -> ~5.5 V at the
    motors. That is normal and fine for 6 V TT motors.
  * If VS >= 7 V, keep the onboard 5V regulator jumper fitted and the L298N makes its own
    logic 5 V. Do NOT also connect the L298N's +5V pin to the Pi's 5V pin.
  * NEVER power the motors from the Pi's 5V pin. Ever.
  * Ground must be shared between the Pi and the L298N or the PWM signal has no reference.
  * Current: an L298N channel is good for ~2 A continuous with its heatsink. Two small
    motors in parallel stall well above that. Keep `limits.max_duty` conservative, fit the
    heatsink, and expect the chip to run hot — it is a 1980s bipolar part.

PIN SAFETY (why the defaults are what they are, and what was actually checked)
------------------------------------------------------------------------------
Checked on this machine with `gpioinfo`, `/sys/kernel/debug/gpio` and
`/sys/kernel/debug/pinctrl/*/pinmux-pins`: every header pin 0-27 is currently unclaimed
by any driver and carries no alternate function. The pins below are still avoided,
because they are reserved by *configuration* rather than by a live claim:

    GPIO 0/1    ID_SDA / ID_SCL  — HAT ID EEPROM i2c
    GPIO 14/15  TXD0 / RXD0      — the serial console

GPIO 14/15 deserve a note, because nothing in the runtime state hints at them:
`console=serial0,115200` in cmdline.txt resolves through the `serial0` alias to the
**mini-UART (ttyS0)** on GPIO14/15, and the mini-UART's pin mux is set by the firmware
externally to Linux. So `gpioinfo` and `/sys/kernel/debug/gpio` both report those lines
as free and unclaimed — a runtime check *cannot* see the conflict. That is precisely why
this script enforces a policy list instead of trusting a probe.

Discouraged (usable, but normally something else's): GPIO 2/3 (I2C1), GPIO 4 (GPCLK0 /
default 1-Wire), GPIO 7-11 (SPI0), GPIO 18-21 (PCM/I2S; the cmdline has
`snd_bcm2835.enable_hdmi=1`).

A TRAP WORTH KNOWING ABOUT. There are two GPIO chips on this Pi 4:

    gpiochip0  pinctrl-bcm2711       58 lines   <-- the 40-pin header
    gpiochip1  raspberrypi-exp-gpio   8 lines   <-- the firmware expander, NOT the header

The expander's lines 5 and 6 are named "CAM_GPIO" (consumer: regulator-cam1) and
"SD_PWR_ON" (consumer: regulator-sd-vcc) — the camera rail and the microSD power switch.
Those are *not* header pins 5 and 6. Reading a plain `gpioinfo` listing without checking
which chip a line belongs to is misleading: the header's own GPIO5/GPIO6 are perfectly
ordinary free pins, while the expander's are load-bearing. This script auto-detects the
SoC chip by device-tree label, never selects the expander, and refuses `--chip` values
that point at it. `--list-chips` prints the enumeration.

The pin defaults are verified free and conflict-free; the script refuses the two
reserved pairs and warns about everything in the discouraged list. Run `--list-reserved`
for the table, `--wiring` for the full wiring and power checklist.

QUICK START
-----------
    # 1. Sanity-check the logic with no hardware attached at all:
    /usr/bin/python3 src/test_motors.py -m forward --dry-run

    # 2. See every maneuver and the live pin map:
    /usr/bin/python3 src/test_motors.py --list
    /usr/bin/python3 src/test_motors.py --wiring

    # 3. Wire it up, wheels OFF the ground, then identify the sides:
    /usr/bin/python3 src/test_motors.py -m wiring

    # 4. Full demo, then drive it by hand:
    /usr/bin/python3 src/test_motors.py -m dance
    /usr/bin/python3 src/test_motors.py --teleop

Single-action maneuvers take --speed and --duration and do exactly one thing:

    -m forward    -m reverse    -m left    -m right    -m stop

`-m left` / `-m right` rotate in place. Skid steer is the only kind of steering a
4-wheel car like this has: one side drives forward while the other reverses. `-m spin`
and `-m arc` are the demo versions that do both directions in sequence; use `-m left` or
`-m right` when you want only one. For turning while also moving, teleop's `q`/`e` veer
left/right, and `a`/`d` spin in place.

CHAINING STEPS (a sequence)
---------------------------
`--sequence` chains motions inside one run — no stop, no re-claiming the pins and no
process startup between them:

    /usr/bin/python3 src/test_motors.py --sequence "forward 5 60, left 3 50, brake 2"

Each step is `<action> <seconds> [speed%] [turn%]`, separated by commas or semicolons;
`#` starts a comment. Values may also be named: `forward seconds=5 speed=60`.

    forward   f     straight forward           veerleft   arc forward-left
    reverse   b     straight back              veerright  arc forward-right
    left      l     spin in place (CCW)        backleft   arc backward-left
    right     r     spin in place (CW)         backright  arc backward-right
    stop      s     hold still (coasts)        brake      hold, outputs shorted
                                               coast      hold, outputs floating

Speed and turn default to motion.speed / motion.turn_rate when omitted:

    --sequence "f 2, veerright 4 60 40, s 1, l 1.5 50, b 2 45"
    --sequence-file steps.json     # list of DSL strings, or {"action":...} objects

Steps run back to back: each step's target replaces the previous one and the control loop
ramps across the join. When a step reverses a side (forward then left, say) the change
travels through zero because of the reversal guard, so expect roughly 0.3 s per side to
swing across. Insert `stop 0.5` if you want a visible pause between moves.

PULSED CONTROL (move / stop / move / stop)
------------------------------------------
Wrap steps in `repeat <count> { ... }` to pulse them, or use `--repeat` to repeat the whole
list. `--repeat 0` loops until you stop it — Ctrl+C, or the `--max-runtime` watchdog
(default 240 s):

    --sequence "repeat 20 { forward 0.5 60, stop 0.5 }"    # 20 pulses, 10 s of motion
    --sequence "forward 0.5 60, stop 0.5" --repeat 0       # pulse until interrupted
    --sequence "repeat 5 { forward 0.4 70, stop 0.6 }"     # 40% duty cycle, 70% speed

Groups nest: `repeat 3 { repeat 4 { forward 0.2, stop 0.2 } }` is 12 pulses. Sequences
also accept the group form in JSON: `{"repeat": 20, "steps": ["forward 0.5", "stop 0.5"]}`.

A caveat that matters for short pulses: every on-pulse has to ramp up at limits.accel and
the stop ramps down at limits.decel, so a pulse shorter than roughly 0.35 s never reaches
the commanded duty. At the defaults (accel 180 %/s) a pulse needs about 0.5 s to be crisp.
Use longer pulses, or raise `--accel`, if the wheels seem lazy.

Run with the system Python (`/usr/bin/python3`). `lgpio` is a Debian package rather than a
pip one, so the system interpreter is the safe choice; the repo venv happens to see it on
this machine too, but a differently-built venv would not.

CONFIGURATION
-------------
Defaults are in DEFAULT_CONFIG below. Override precedence, lowest to highest:

    DEFAULT_CONFIG  <  --config motor_config.json  <  individual CLI flags

    --print-config            dump the effective config as JSON
    --write-config FILE       write the effective config out for editing
    --list-reserved           show the pin-safety table
    --wiring                  show the wiring + power checklist

Everything tunable has a CLI flag: pins, invert, trim, deadband, duty limits, slew rates,
PWM frequency, idle mode (coast/brake), control rate, turn calibration, timeouts, CSV log.

CALIBRATING IT FOR YOUR CHASSIS
-------------------------------
* `--trim-left` / `--trim-right` (0.0-1.5): if the car pulls to one side, reduce that side.
* `--invert-left` / `--invert-right`: use when a side drives the wrong way. Fixing it here
  is equivalent to swapping that side's two motor wires.
* `limits.min_duty` (default 22): the duty below which an L298N + gearmotor just hums.
* `limits.deadband` (default 0.12): commanded speeds smaller than this stop the motors.
* `geometry.turn_ms_90` / `geometry.turn_speed`: measure a spin in place, then set these so
  `square` and `figure8` come out right. `-m spin` prints the current numbers.

Exit codes: 0 ok, 1 usage/config error, 2 hardware/backend error, 130 interrupted.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import select
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

__version__ = "1.0.0"

# --------------------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    "chip": None,  # None = auto-detect by DT label; integer to force (0 is normal on Pi 4)
    "pins": {
        "left": {"en": 12, "in1": 17, "in2": 27, "invert": False},
        "right": {"en": 13, "in3": 22, "in4": 23, "invert": False},
    },
    "geometry": {
        "motors_per_channel": 2,  # informational: 2 motors paralleled per L298N channel
        "wheel_track_m": 0.15,  # left-to-right wheel spacing, informational
        "turn_ms_90": 700.0,  # measured ms for a 90 deg spin at turn_speed
        "turn_speed": 65.0,  # % duty used for that spin
    },
    "limits": {
        "max_duty": 90.0,  # never exceed this duty on either side
        "min_duty": 22.0,  # L298N + gearmotor deadband floor
        "deadband": 0.12,  # commanded |v| below this = stop (normalised units)
        "accel": 180.0,  # duty %/second while increasing
        "decel": 320.0,  # duty %/second while decreasing (stopping is faster)
        "reversal_max_duty": 8.0,  # direction may only flip below this duty
    },
    "trim": {"left": 1.0, "right": 1.0},
    "control": {
        "rate_hz": 50.0,  # servo/control loop rate
        "pwm_freq": 1000.0,  # PWM frequency in Hz (50-2000 is a good range for DC motors)
        "idle_mode": "coast",  # "coast" (freewheel) or "brake" (outputs shorted)
        "log_hz": 20.0,  # telemetry sample rate when --log is used
    },
    "safety": {
        "max_runtime_s": 240.0,  # hard stop for the whole run, 0 = unlimited
        "settle_timeout_s": 3.0,  # max wait for a commanded stop to complete
    },
    "motion": {
        "speed": 60.0,  # default forward/arc speed, %
        "duration_s": 3.0,  # default straight-line hold
        "turn_rate": 35.0,  # turn bias (% of full) used by arc/slalom/figure8
        "pulse_ms": 400.0,  # default single-side pulse for the wiring check
        "pause_s": 0.7,  # gap between steps in a sequence
        "repeat": 1,  # sequence cycles; 0 = loop until stopped
    },
    "logging": {"csv": None},  # e.g. "motor_log.csv"
}

FORBIDDEN_PINS: Dict[int, str] = {
    0: "ID_SDA  — HAT ID EEPROM i2c",
    1: "ID_SCL  — HAT ID EEPROM i2c",
    14: "TXD0    — serial console (serial0 = ttyS0 mini-UART, console=ttyS0,115200)",
    15: "RXD0    — serial console (the mini-UART mux is invisible to gpioinfo)",
}

DISCOURAGED_PINS: Dict[int, str] = {
    2: "SDA1    — I2C1",
    3: "SCL1    — I2C1",
    4: "GPCLK0 / default 1-Wire pin",
    7: "SPI0 CE1",
    8: "SPI0 CE0",
    9: "SPI0 MISO",
    10: "SPI0 MOSI",
    11: "SPI0 SCLK",
    18: "PCM_CLK / I2S (audio)",  # snd_bcm2835.enable_hdmi=1 on this machine
    19: "PCM_FS / I2S (audio)",
    20: "PCM_DIN / I2S (audio)",
    21: "PCM_DOUT / I2S (audio)",
}

# GPIO -> physical pin on the 40-way header (BCM numbering), header lines only.
GPIO_TO_PHYS: Dict[int, int] = {
    0: 27, 1: 28, 2: 3, 3: 5, 4: 7, 5: 29, 6: 31, 7: 26, 8: 24, 9: 21, 10: 19,
    11: 23, 12: 32, 13: 33, 14: 8, 15: 10, 16: 36, 17: 11, 18: 12, 19: 35, 20: 38,
    21: 40, 22: 15, 23: 16, 24: 18, 25: 22, 26: 37, 27: 13,
}

MAX_HEADER_GPIO = 27


class MotorError(RuntimeError):
    """Configuration or hardware problem that should stop the run."""


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else (high if value > high else value)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge `override` into a copy of `base`."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def bar(fraction: float, width: int = 18) -> str:
    """A small ASCII duty meter, e.g. 0.4 -> '████████░░░░░░░░░░'."""
    filled = int(round(clamp(fraction, 0.0, 1.0) * width))
    return "█" * filled + "░" * (width - filled)


def phys(pin: int) -> str:
    return f"pin {GPIO_TO_PHYS[pin]}" if pin in GPIO_TO_PHYS else "not on header"


def board_model() -> str:
    """Board identification straight from the device tree."""
    try:
        with open("/proc/device-tree/model", "r") as handle:
            return handle.read().strip("\x00").strip()
    except OSError:
        return "unknown board"


def _check(code: Any, what: str) -> Any:
    """Turn an lgpio negative return code into an exception with context."""
    if isinstance(code, int) and code < 0:
        raise MotorError(f"{what} failed (lgpio error {code})")
    return code


# --------------------------------------------------------------------------------------
# gpioinfo preflight: who already owns the pins we want?
# --------------------------------------------------------------------------------------


def gpioinfo_map(timeout: float = 3.0) -> Dict[int, Tuple[str, Optional[str]]]:
    """
    Parse `gpioinfo` into {gpio: (dt_name, consumer)}.

    Used purely as a *preflight* safety net: it tells us a line is already owned by
    firmware/another process before we try to claim it. Missing gpioinfo is not fatal.
    """
    try:
        proc = subprocess.run(
            ["gpioinfo"], capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    found: Dict[int, Tuple[str, Optional[str]]] = {}
    for line in proc.stdout.splitlines():
        match = re.match(r"\s*line\s+(\d+):\s*(.*)$", line)
        if not match:
            continue
        pin, rest = int(match.group(1)), match.group(2)
        name = re.search(r'"([^"]*)"', rest)
        consumer = re.search(r'consumer="([^"]*)"', rest)
        previous = found.get(pin)
        entry = (name.group(1) if name else "", consumer.group(1) if consumer else None)
        # The "named lines" block is printed after the base block; prefer the entry that
        # actually names a consumer.
        if previous is None or (entry[1] and not previous[1]):
            found[pin] = entry
    return found


# --------------------------------------------------------------------------------------
# Backends — everything that touches (or pretends to touch) hardware
# --------------------------------------------------------------------------------------


class Backend:
    """Minimal GPIO surface the rest of the program needs."""

    name = "abstract"

    def claim_output(self, pin: int, level: int = 0) -> None:
        raise NotImplementedError

    def write(self, pin: int, level: int) -> None:
        raise NotImplementedError

    def tx_pwm(self, pin: int, frequency: float, duty: float) -> None:
        raise NotImplementedError

    def stop_pwm(self, pin: int) -> None:
        raise NotImplementedError

    def release(self, pin: int) -> None:
        raise NotImplementedError

    def flush_if_due(self) -> None:
        """Optional hook: render pending state. Only the dry-run backend implements it."""

    def close(self) -> None:
        pass


def chip_info(lgpio_mod: Any, handle: int) -> Dict[str, Any]:
    """Normalise lgpio.gpio_get_chip_info, which is a list on Debian's bindings."""
    try:
        raw = lgpio_mod.gpio_get_chip_info(handle)
    except Exception:  # pragma: no cover - depends on binding version
        return {}
    if isinstance(raw, dict):
        return {
            "id": raw.get("id"),
            "lines": raw.get("lines"),
            "name": raw.get("name"),
            "label": raw.get("label"),
        }
    if isinstance(raw, (list, tuple)):
        return {
            "id": raw[0] if len(raw) > 0 else None,
            "lines": raw[1] if len(raw) > 1 else None,
            "name": raw[2] if len(raw) > 2 else None,
            "label": raw[3] if len(raw) > 3 else None,
        }
    return {}


class LgpioBackend(Backend):
    """Real hardware via lgpio (works on both Pi 4/BCM2711 and Pi 5/RP1)."""

    name = "lgpio"

    #: DT labels we will accept when auto-detecting. Pi 4 = pinctrl-bcm2711,
    #: Pi 5 = pinctrl-rp1, earlier Pis = pinctrl-bcm283x.
    LABELS = ("pinctrl-bcm2711", "pinctrl-rp1", "pinctrl-bcm2835", "pinctrl-bcm2836")

    def __init__(self, chip: Optional[int] = None) -> None:
        try:
            import lgpio  # type: ignore
        except ImportError as exc:
            raise MotorError(
                "lgpio is not importable. It is a Debian package, not a PyPI one:\n"
                "    sudo apt install python3-lgpio\n"
                "and run this script with the system interpreter:\n"
                "    /usr/bin/python3 src/test_motors.py --list\n"
                "(a venv without --system-site-packages will not see it. Or add --dry-run.)"
            ) from exc

        self.lgpio = lgpio
        self.handle, self.chip_id, self.info = self._open(chip)
        self.name = f"lgpio (gpiochip{self.chip_id} '{self.info.get('label')}')"

    def _open(self, wanted: Optional[int]) -> Tuple[int, int, Dict[str, Any]]:
        if wanted is not None:
            handle = self.lgpio.gpiochip_open(int(wanted))  # raises on failure
            info = chip_info(self.lgpio, handle)
            label = str(info.get("label", ""))
            if label and not any(want in label for want in self.LABELS):
                self.lgpio.gpiochip_close(handle)
                raise MotorError(
                    f"gpiochip{wanted} is '{label}', which is not the SoC GPIO controller.\n"
                    "  On a Pi 4 the 40-pin header is gpiochip0 (pinctrl-bcm2711); gpiochip1 is\n"
                    "  the firmware expander, whose lines 5/6 are CAM_GPIO and SD_PWR_ON - the\n"
                    "  camera rail and the microSD power switch. Do not aim motor pins at it.\n"
                    "  Omit --chip and the script will pick the SoC chip by itself."
                )
            return handle, int(wanted), info

        first_open: Optional[Tuple[int, int, Dict[str, Any]]] = None
        for number in range(0, 8):
            try:
                handle = self.lgpio.gpiochip_open(number)
            except Exception:
                continue
            info = chip_info(self.lgpio, handle)
            if first_open is None:
                first_open = (handle, number, info)
            label = str(info.get("label", ""))
            if any(want in label for want in self.LABELS):
                return handle, number, info
            self.lgpio.gpiochip_close(handle)

        if first_open is not None:
            return first_open
        raise MotorError("no usable gpiochip found (is this a Raspberry Pi?)")

    def claim_output(self, pin: int, level: int = 0) -> None:
        _check(
            self.lgpio.gpio_claim_output(self.handle, pin, level),
            f"claim GPIO{pin} as output",
        )

    def write(self, pin: int, level: int) -> None:
        _check(self.lgpio.gpio_write(self.handle, pin, 1 if level else 0), f"write GPIO{pin}")

    def tx_pwm(self, pin: int, frequency: float, duty: float) -> None:
        _check(self.lgpio.tx_pwm(self.handle, pin, frequency, duty), f"PWM on GPIO{pin}")

    def stop_pwm(self, pin: int) -> None:
        # lgpio: frequency 0 stops software PWM on that line.
        try:
            self.lgpio.tx_pwm(self.handle, pin, 0, 0)
        except Exception:
            pass

    def release(self, pin: int) -> None:
        try:
            self.lgpio.gpio_free(self.handle, pin)
        except Exception:
            pass
        # gpio_free() leaves the pad configured as an output at whatever level it last
        # held; it does not return the pin to input. Restoring it is a two-step dance:
        # claim the line as an input, then free it again.
        try:
            self.lgpio.gpio_claim_input(self.handle, pin)
            self.lgpio.gpio_free(self.handle, pin)
        except Exception:
            pass

    def close(self) -> None:
        if getattr(self, "handle", None) is not None:
            try:
                self.lgpio.gpiochip_close(self.handle)
            except Exception:
                pass
            self.handle = None


class DryRunBackend(Backend):
    """
    No hardware. Records the pin state and prints a compact, rate-limited trace.

    This is the default when lgpio is unavailable, and it is how you validate motion
    sequences, ramps, trims and safety limits before a single wire is connected.
    """

    name = "dry-run (no hardware)"

    def __init__(self, roles: Dict[int, str], min_interval: float = 0.25) -> None:
        self.roles = dict(roles)
        self.levels: Dict[int, int] = {}
        self.pwm: Dict[int, Tuple[float, float]] = {}
        self.claimed: List[int] = []
        self._min_interval = min_interval
        self._last_print = 0.0
        self._dirty = False
        self._printed_anything = False
        self.lock = threading.Lock()

    # -- Backend API ----------------------------------------------------------------
    def claim_output(self, pin: int, level: int = 0) -> None:
        self.levels[pin] = 1 if level else 0
        self.claimed.append(pin)

    def write(self, pin: int, level: int) -> None:
        level = 1 if level else 0
        if self.levels.get(pin) != level:
            self.levels[pin] = level
            self._maybe_print()

    def tx_pwm(self, pin: int, frequency: float, duty: float) -> None:
        current = self.pwm.get(pin)
        if current is not None and abs(current[1] - duty) < 0.25 and current[0] == frequency:
            return
        self.pwm[pin] = (frequency, duty)
        self._maybe_print()

    def stop_pwm(self, pin: int) -> None:
        if pin in self.pwm:
            self.pwm.pop(pin)
            self._maybe_print()

    def release(self, pin: int) -> None:
        self.pwm.pop(pin, None)

    # -- Rendering ------------------------------------------------------------------
    def _maybe_print(self) -> None:
        # Never render from inside a GPIO write: one tick touches several pins, so the
        # caller flushes once per tick when both sides agree.
        with self.lock:
            self._dirty = True

    def flush_if_due(self) -> None:
        now = time.monotonic()
        with self.lock:
            if self._dirty and now - self._last_print >= self._min_interval:
                self._flush(now)

    def _flush(self, now: Optional[float] = None) -> None:
        if not self._dirty:
            return
        now = now or time.monotonic()
        self._last_print = now
        self._dirty = False
        self._printed_anything = True
        print("      " + self.render(), flush=True)

    def flush(self) -> None:
        with self.lock:
            self._flush()

    def render(self) -> str:
        parts: List[str] = []
        for side, keys in (("L", ("en", "in1", "in2")), ("R", ("en", "in3", "in4"))):
            en = self._role_pin(side, keys[0])
            in_a = self._role_pin(side, keys[1])
            in_b = self._role_pin(side, keys[2])
            if en is None:
                continue
            duty = self.pwm.get(en, (0.0, 0.0))[1]
            a, b = self.levels.get(in_a, 0), self.levels.get(in_b, 0)
            if duty <= 0.0 and a == 0 and b == 0:
                state = "coast "
            elif duty <= 0.0 and a == 1 and b == 1:
                state = "BRAKE "
            elif a == 1 and b == 0:
                state = "fwd"
            elif a == 0 and b == 1:
                state = "rev"
            else:
                state = "?? "
            parts.append(f"{side} [{bar(duty / 100.0)}] {duty:5.1f}% {state}")
        freq = next((v[0] for v in self.pwm.values()), 0.0)
        return f"{parts[0]}   {parts[1]}   {freq:.0f}Hz" if len(parts) == 2 else " ".join(parts)

    def _role_pin(self, side: str, key: str) -> Optional[int]:
        for pin, role in self.roles.items():
            if role == f"{side}.{key}":
                return pin
        return None

    def close(self) -> None:
        self.flush()


# --------------------------------------------------------------------------------------
# Pin objects
# --------------------------------------------------------------------------------------


class DigitalPin:
    def __init__(self, backend: Backend, pin: int) -> None:
        self.backend, self.pin = backend, pin
        backend.claim_output(pin, 0)
        self.level = 0

    def write(self, level: int) -> None:
        level = 1 if level else 0
        if level != self.level:
            self.backend.write(self.pin, level)
            self.level = level


class PwmPin:
    """
    An enable pin that can be either PWM-driven or held statically high/low.

    The distinction matters on an L298N: `brake()` needs EN held HIGH with both IN pins
    high so the bridge shorts the motor; `coast()` needs EN low so the outputs float.
    A PWM duty of 0% is *not* the same as EN low for braking purposes.
    """

    def __init__(self, backend: Backend, pin: int, frequency: float) -> None:
        self.backend, self.pin, self.frequency = backend, pin, frequency
        backend.claim_output(pin, 0)
        self.mode = "low"  # low | high | pwm
        self.duty = 0.0

    def set_duty(self, duty: float) -> None:
        duty = clamp(duty, 0.0, 100.0)
        if duty <= 0.0:
            self.low()
            return
        if self.mode != "pwm":
            self.backend.tx_pwm(self.pin, self.frequency, duty)
            self.mode, self.duty = "pwm", duty
        elif abs(duty - self.duty) >= 0.25:
            self.backend.tx_pwm(self.pin, self.frequency, duty)
            self.duty = duty

    def low(self) -> None:
        if self.mode == "pwm":
            self.backend.stop_pwm(self.pin)
        if self.mode != "low":
            self.backend.write(self.pin, 0)
        self.mode, self.duty = "low", 0.0

    def high(self) -> None:
        if self.mode == "pwm":
            self.backend.stop_pwm(self.pin)
        if self.mode != "high":
            self.backend.write(self.pin, 1)
        self.mode, self.duty = "high", 100.0


class Side:
    """One L298N channel = one side of the car (two motors in parallel)."""

    def __init__(
        self, backend: Backend, name: str, en: int, in_a: int, in_b: int, invert: bool, freq: float
    ) -> None:
        self.name = name
        self.enable = PwmPin(backend, en, freq)
        self.in_a = DigitalPin(backend, in_a)
        self.in_b = DigitalPin(backend, in_b)
        self.invert = invert
        self.direction = 0
        self.pin_numbers = (en, in_a, in_b)

    def apply(self, duty: float) -> None:
        """duty is signed and already shaped/limited: -100..100 (negative = reverse)."""
        duty = -duty if self.invert else duty
        direction = 1 if duty > 0.0 else (-1 if duty < 0.0 else 0)

        if direction != self.direction:
            # Never reverse the bridge while current is flowing: drop to 0 first.
            self.enable.set_duty(0.0)
            self.in_a.write(1 if direction > 0 else 0)
            self.in_b.write(1 if direction < 0 else 0)
            self.direction = direction

        self.enable.set_duty(abs(duty))

    def coast(self) -> None:
        self.direction = 0
        self.in_a.write(0)
        self.in_b.write(0)
        self.enable.low()

    def brake(self) -> None:
        self.direction = 0
        self.enable.set_duty(0.0)
        self.in_a.write(1)
        self.in_b.write(1)
        self.enable.high()

    def release(self, backend: Backend) -> None:
        """
        Hand the lines back to the system.

        Note that free() returns a line to input (floating), so the L298N's own input
        pull-downs decide the state from here on. Deliberately does NOT re-park: that
        would silently undo the idle_mode that Drive.close() just applied.
        """
        for pin in self.pin_numbers:
            backend.release(pin)


# --------------------------------------------------------------------------------------
# Drive: kinematics + the slew-limited control loop
# --------------------------------------------------------------------------------------


class Drive:
    """
    Owns the pins and runs a fixed-rate control loop.

    Maneuvers only ever set a *target* (normalised -1..1 per side); the loop ramps the
    actual duty toward it at the configured slew rate, so the motor driver never sees a
    step change and the gearbox never sees a slam. The loop is the single writer of GPIO
    state, which keeps brake/coast/PWM from racing with each other.
    """

    def __init__(self, cfg: Dict[str, Any], backend: Backend, verbose: bool = True) -> None:
        self.cfg = cfg
        self.backend = backend
        self.verbose = verbose

        pins = cfg["pins"]
        freq = float(cfg["control"]["pwm_freq"])
        self.left = Side(
            backend, "left",
            pins["left"]["en"], pins["left"]["in1"], pins["left"]["in2"],
            bool(pins["left"]["invert"]), freq,
        )
        self.right = Side(
            backend, "right",
            pins["right"]["en"], pins["right"]["in3"], pins["right"]["in4"],
            bool(pins["right"]["invert"]), freq,
        )

        limits = cfg["limits"]
        self.max_duty = float(limits["max_duty"])
        self.min_duty = float(limits["min_duty"])
        self.deadband = float(limits["deadband"])
        self.accel = float(limits["accel"])
        self.decel = float(limits["decel"])
        self.reversal_max_duty = float(limits["reversal_max_duty"])
        self.trim = (float(cfg["trim"]["left"]), float(cfg["trim"]["right"]))
        self.idle_mode = str(cfg["control"]["idle_mode"])
        self.rate_hz = float(cfg["control"]["rate_hz"])
        self.settle_timeout = float(cfg["safety"]["settle_timeout_s"])
        self.max_runtime = float(cfg["safety"]["max_runtime_s"])

        self._target = [0.0, 0.0]  # normalised, signed
        self._current = [0.0, 0.0]  # normalised, signed (post-slew, pre-shaping)
        self._duty = [0.0, 0.0]
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._abort = threading.Event()
        self._parked: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._started = time.monotonic()
        self._last_duty_key: Optional[Tuple[float, float]] = None
        self._log_writer: Optional[csv.writer] = None
        self._log_file = None
        self._log_every = max(1, int(round(self.rate_hz / max(1.0, float(cfg["control"]["log_hz"])))))
        self._tick = 0

    # -- lifecycle -------------------------------------------------------------------
    def start(self) -> None:
        csv_path = self.cfg["logging"].get("csv")
        if csv_path:
            self._log_file = open(csv_path, "w", newline="")
            self._log_writer = csv.writer(self._log_file)
            self._log_writer.writerow(
                ["t", "target_left", "target_right", "left", "right", "duty_left", "duty_right"]
            )
            if self.verbose:
                print(f"  telemetry -> {csv_path}")
        self._thread = threading.Thread(target=self._loop, name="drive-loop", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        # Park the bridge in a known state, then hand the lines back.
        try:
            if self.idle_mode == "brake":
                self.left.brake()
                self.right.brake()
            else:
                self.left.coast()
                self.right.coast()
        except Exception:
            pass
        self._parked = None
        self.left.release(self.backend)
        self.right.release(self.backend)
        self.backend.close()
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    # -- public API ------------------------------------------------------------------
    def set(self, left: float, right: float) -> None:
        with self._lock:
            self._target = [clamp(left, -1.0, 1.0), clamp(right, -1.0, 1.0)]

    def steer(self, linear: float, turn: float) -> None:
        """
        Arcade-drive mixing for a skid-steer car.

        linear: -1 (full reverse) .. +1 (full forward)
        turn:   -1 (rotate right / clockwise) .. +1 (rotate left / counter-clockwise)

        Both sides stay within +-1; when the mix would exceed that, both are scaled down
        together so the commanded turn ratio is preserved.
        """
        left = clamp(linear, -1.0, 1.0) - clamp(turn, -1.0, 1.0)
        right = clamp(linear, -1.0, 1.0) + clamp(turn, -1.0, 1.0)
        peak = max(abs(left), abs(right))
        if peak > 1.0:
            left, right = left / peak, right / peak
        self.set(left, right)

    def stop(self, mode: Optional[str] = None, wait: bool = True) -> None:
        if mode is not None:
            self.idle_mode = mode
        self.set(0.0, 0.0)
        if wait:
            self.wait_settled()

    def brake(self) -> None:
        self.stop("brake")

    def coast(self) -> None:
        self.stop("coast")

    def abort(self) -> None:
        """Ask every maneuver to unwind at the next opportunity (used by SIGTERM)."""
        self._abort.set()

    @property
    def aborted(self) -> bool:
        return self._abort.is_set()

    def expired(self) -> bool:
        return self.max_runtime > 0 and (time.monotonic() - self._started) > self.max_runtime

    def nap(self, seconds: float) -> bool:
        """Interruptible sleep. Returns False if the run was aborted or timed out."""
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            if self._abort.is_set() or self.expired():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            if self._stop.wait(timeout=min(0.05, remaining)):
                return False

    def wait_settled(self, timeout: Optional[float] = None) -> bool:
        timeout = self.settle_timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                idle_target = self._target == [0.0, 0.0]
            if idle_target and max(abs(self._current[0]), abs(self._current[1])) < 0.005:
                return True
            time.sleep(0.01)
        return False

    def park_now(self, mode: Optional[str] = None) -> None:
        """Force an immediate electrical park regardless of the ramp state."""
        if mode is not None:
            self.idle_mode = mode
        with self._lock:
            self._target = [0.0, 0.0]
            self._current = [0.0, 0.0]
        self._parked = None
        self._park()

    # -- internals -------------------------------------------------------------------
    def _park(self) -> None:
        if self._parked == self.idle_mode:
            return
        if self.idle_mode == "brake":
            self.left.brake()
            self.right.brake()
        else:
            self.left.coast()
            self.right.coast()
        self._parked = self.idle_mode

    def _shape(self, value: float, side: int) -> float:
        """Normalised command -> signed duty %, with deadband remap, trim and cap."""
        magnitude = abs(value)
        if magnitude < self.deadband:
            return 0.0
        span = 1.0 - self.deadband
        duty = self.min_duty + (self.max_duty - self.min_duty) * ((magnitude - self.deadband) / span)
        duty *= self.trim[side]
        return math.copysign(min(duty, self.max_duty), value)

    def _loop(self) -> None:
        period = 1.0 / max(1.0, self.rate_hz)
        previous = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            dt = min(0.25, max(0.0, now - previous))
            previous = now
            self._step(dt)
            self._stop.wait(timeout=period)

    def _step(self, dt: float) -> None:
        with self._lock:
            targets = list(self._target)

        for index in range(2):
            target = targets[index]
            current = self._current[index]

            if target == current:
                continue

            # Refuse to reverse while moving: aim at zero until the bridge is quiet.
            if current * target < 0.0 and abs(current) * 100.0 > self.reversal_max_duty:
                effective, rate = 0.0, self.decel
            else:
                effective = target
                rate = self.accel if abs(target) > abs(current) else self.decel

            step = rate * dt / 100.0
            delta = effective - current
            self._current[index] = (
                effective if abs(delta) <= step else current + math.copysign(step, delta)
            )

        duty = [
            self._shape(self._current[0], 0),
            self._shape(self._current[1], 1),
        ]

        if duty[0] == 0.0 and duty[1] == 0.0 and targets == [0.0, 0.0]:
            self._park()
        else:
            self._parked = None
            self.left.apply(duty[0])
            self.right.apply(duty[1])

        self._duty = duty
        self._tick += 1
        self.backend.flush_if_due()
        if self._log_writer is not None and self._tick % self._log_every == 0:
            self._log_writer.writerow(
                [
                    f"{time.monotonic() - self._started:.3f}",
                    f"{targets[0]:.3f}", f"{targets[1]:.3f}",
                    f"{self._current[0]:.3f}", f"{self._current[1]:.3f}",
                    f"{duty[0]:.1f}", f"{duty[1]:.1f}",
                ]
            )

    def status(self) -> str:
        left, right = self._duty
        return f"L {left:6.1f}%  R {right:6.1f}%"


# --------------------------------------------------------------------------------------
# Maneuvers
# --------------------------------------------------------------------------------------

MANEUVERS: Dict[str, Tuple[Callable[["Drive", Dict[str, Any], argparse.Namespace], None], str]] = {}


def maneuver(name: str, description: str):
    def register(func):
        MANEUVERS[name] = (func, description)
        return func

    return register


def _sep(title: str = "") -> None:
    if title:
        print("\n=== " + title + " " + "=" * max(0, 62 - len(title)))
    else:
        print("\n" + "=" * 66)


def _speed(args: argparse.Namespace) -> float:
    return clamp(float(args.speed) / 100.0, 0.0, 1.0)


@maneuver("stop", "park the outputs immediately and exit (safe default)")
def m_stop(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    print(f"Parking ({drive.idle_mode}).")


@maneuver("pulse", "brief pulse of each side, then both directions (quick wiring sanity)")
def m_pulse(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    seconds = float(cfg["motion"]["pulse_ms"]) / 1000.0
    speed = _speed(args)
    for label, left, right in (
        ("LEFT side forward", speed, 0.0),
        ("RIGHT side forward", 0.0, speed),
        ("both forward", speed, speed),
        ("both reverse", -speed, -speed),
    ):
        print(f"  {label}  ({seconds * 1000:.0f} ms)")
        drive.set(left, right)
        drive.nap(seconds)
        drive.stop()
        drive.nap(float(cfg["motion"]["pause_s"]))


@maneuver("wiring", "guided self-check: identifies each side, direction and trim")
def m_wiring(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    seconds = float(cfg["motion"]["pulse_ms"]) / 1000.0
    print("  Wheels OFF the ground. Watch which wheels turn, and which way.")
    for label, left, right, expect in (
        ("LEFT side forward", 0.55, 0.0, "left pair turns; car would veer right"),
        ("RIGHT side forward", 0.0, 0.55, "right pair turns; car would veer left"),
        ("both forward", 0.55, 0.55, "all four turn the same way (car drives forward)"),
        ("both reverse", -0.55, -0.55, "all four reverse"),
        ("spin left", -0.55, 0.55, "left pair backwards + right pair forwards"),
        ("spin right", 0.55, -0.55, "left pair forwards + right pair backwards"),
    ):
        print(f"\n  >> {label}  — expect: {expect}")
        drive.set(left, right)
        drive.nap(seconds * 2)
        drive.stop()
        drive.nap(float(cfg["motion"]["pause_s"]))
    print("\n  If a side turned the wrong way: re-run with --invert-left / --invert-right.")
    print("  If a side never moved: check its ENA/ENB jumper is removed and its IN pins.")


@maneuver("forward", "drive straight forward, hold, then stop")
def m_forward(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    speed = _speed(args)
    print(f"  forward at {args.speed:.0f}% for {args.duration:.1f} s")
    drive.steer(speed, 0.0)
    if drive.nap(float(args.duration)):
        drive.stop()


@maneuver("reverse", "drive straight back, hold, then stop")
def m_reverse(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    speed = _speed(args)
    print(f"  reverse at {args.speed:.0f}% for {args.duration:.1f} s")
    drive.steer(-speed, 0.0)
    if drive.nap(float(args.duration)):
        drive.stop()


@maneuver("left", "rotate in place to the left (counter-clockwise), then stop")
def m_left(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    speed = _speed(args)
    print(f"  spinning left at {args.speed:.0f}% for {args.duration:.1f} s")
    print("  (left wheels reverse, right wheels drive forward)")
    drive.steer(0.0, speed)
    if drive.nap(float(args.duration)):
        drive.stop()


@maneuver("right", "rotate in place to the right (clockwise), then stop")
def m_right(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    speed = _speed(args)
    print(f"  spinning right at {args.speed:.0f}% for {args.duration:.1f} s")
    print("  (left wheels drive forward, right wheels reverse)")
    drive.steer(0.0, -speed)
    if drive.nap(float(args.duration)):
        drive.stop()


@maneuver("spin", "rotate in place, left then right (also prints the turn calibration)")
def m_spin(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    speed = clamp(float(cfg["geometry"]["turn_speed"]) / 100.0, 0.0, 1.0)
    turn_s = float(cfg["geometry"]["turn_ms_90"]) / 1000.0
    print(f"  spin left  ({speed * 100:.0f}%, {turn_s:.2f} s — config says that is 90 deg)")
    drive.steer(0.0, speed)
    drive.nap(turn_s)
    drive.stop()
    drive.nap(float(cfg["motion"]["pause_s"]))
    print("  spin right")
    drive.steer(0.0, -speed)
    drive.nap(turn_s)
    drive.stop()
    print(
        f"\n  If the car did not turn exactly 90 deg, scale geometry.turn_ms_90 "
        f"(now {cfg['geometry']['turn_ms_90']:.0f} ms) by (target / actual)."
    )


@maneuver("arc", "forward-left arc then forward-right arc")
def m_arc(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    speed = _speed(args)
    rate = clamp(float(args.turn_rate) / 100.0, 0.0, 1.0)
    for label, turn in (("left", rate), ("right", -rate)):
        print(f"  arcing {label} at {args.speed:.0f}% with {args.turn_rate:.0f}% turn bias")
        drive.steer(speed, turn)
        drive.nap(float(args.duration))
        drive.stop()
        drive.nap(float(cfg["motion"]["pause_s"]))


@maneuver("slalom", "three alternating arcs — a gentle S-curve weave")
def m_slalom(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    speed = _speed(args)
    rate = clamp(float(args.turn_rate) / 100.0, 0.0, 1.0)
    leg = max(0.6, float(args.duration) / 2.0)
    for index, turn in enumerate((rate, -rate, rate)):
        print(f"  weave {index + 1}/3 ({'left' if turn > 0 else 'right'})")
        drive.steer(speed, turn)
        if not drive.nap(leg):
            break
    drive.stop()


@maneuver("square", "drive a square using timed 90-degree spins")
def m_square(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    speed = _speed(args)
    spin_speed = clamp(float(cfg["geometry"]["turn_speed"]) / 100.0, 0.0, 1.0)
    turn_s = float(cfg["geometry"]["turn_ms_90"]) / 1000.0
    leg = float(args.duration)
    print(f"  four {leg:.1f} s sides with {turn_s:.2f} s spins (turn_ms_90)")
    for side in range(4):
        print(f"  side {side + 1}/4")
        drive.steer(speed, 0.0)
        if not drive.nap(leg):
            break
        drive.stop()
        if not drive.nap(0.4):
            break
        drive.steer(0.0, spin_speed)
        if not drive.nap(turn_s):
            break
        drive.stop()
        if not drive.nap(0.4):
            break
    drive.stop()


@maneuver("figure8", "one circle each way, crossing in the middle")
def m_figure8(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    speed = _speed(args)
    rate = clamp(float(args.turn_rate) / 100.0, 0.0, 1.0)
    lap = max(1.5, float(args.duration))
    for label, turn in (("clockwise loop", -rate), ("counter-clockwise loop", rate)):
        print(f"  {label} for {lap:.1f} s")
        drive.steer(speed, turn)
        if not drive.nap(lap):
            break
        drive.stop("coast")
        if not drive.nap(float(cfg["motion"]["pause_s"])):
            break
    drive.stop()


@maneuver("ramp", "slow 0->max->0 on both sides, no motion commands in between")
def m_ramp(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    span = max(1.0, float(args.duration)) / 2.0
    print(f"  ramping up over {span:.1f} s, down over {span:.1f} s")
    print("  (the control loop does the ramping; this just sets the target)")
    drive.set(1.0, 1.0)
    if not drive.nap(span):
        return
    drive.set(-1.0, -1.0)
    if not drive.nap(span):
        return
    drive.stop()


@maneuver("brake_test", "shows the L298N coast vs brake difference from the same speed")
def m_brake_test(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    speed = _speed(args)
    leg = max(0.8, float(args.duration) / 2.0)
    for label, mode, explain in (
        ("COAST", "coast", "outputs float — the car rolls on"),
        ("BRAKE", "brake", "outputs shorted — the car stops hard"),
    ):
        print(f"\n  run up to {args.speed:.0f}% for {leg:.1f} s, then {label} ({explain})")
        drive.idle_mode = "coast"
        drive.steer(speed, 0.0)
        if not drive.nap(leg):
            return
        # The electrical stop is immediate; whether the car keeps rolling is the point.
        drive.park_now(mode)
        print(f"  {label} applied: {drive.status()}")
        if not drive.nap(1.2):
            return


@maneuver("sequence", "run chained steps back to back (--sequence / --sequence-file)")
def m_sequence(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    steps: List[Dict[str, Any]] = list(getattr(args, "steps", []))
    if not steps:
        raise MotorError('no steps: use --sequence "forward 5 60, left 3 50"')
    repeat = int(getattr(args, "repeat", 1) or 0)
    per_cycle = sum(step["seconds"] for step in steps)
    started = time.monotonic()
    cycle = 0
    finished = True

    while True:
        cycle += 1
        if repeat and cycle > repeat:
            break
        if repeat != 1:
            label = f"cycle {cycle}/{repeat}" if repeat else f"cycle {cycle} (--repeat 0)"
            print(f"\n  --- {label} ---")
        for index, step in enumerate(steps, start=1):
            if drive.aborted or drive.expired():
                print(f"\n  stopped before step {index}/{len(steps)} of cycle {cycle}")
                finished = False
                break
            print(f"  [{index}/{len(steps)}] {describe_step(step)}")
            if step["action"] in ("brake", "coast"):
                # An electrical hold, not a motion command: no ramping involved.
                drive.park_now(step["action"])
                completed = drive.nap(step["seconds"])
            else:
                linear, turn = step_targets(step)
                drive.steer(linear, turn)
                completed = drive.nap(step["seconds"])
            if not completed:
                print(f"\n  stopped during step {index}/{len(steps)} of cycle {cycle}")
                finished = False
                break
        if not finished:
            break

    elapsed = time.monotonic() - started
    if repeat:
        print(f"\n  sequence ran {elapsed:.1f} s of {per_cycle * repeat:.1f} s planned "
              f"({len(steps)} steps x {repeat})")
    else:
        print(f"\n  sequence ran {elapsed:.1f} s over {cycle} cycles "
              f"({len(steps)} steps each)")
    drive.stop()


@maneuver("dance", "the full demo: pulse, forward, spin, arc, slalom, figure-8, ramp, brakes")
def m_dance(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    for name in ("pulse", "forward", "spin", "arc", "slalom", "figure8", "ramp", "brake_test"):
        if drive.aborted or drive.expired():
            break
        _sep(f"{name} — {MANEUVERS[name][1]}")
        MANEUVERS[name][0](drive, cfg, args)
    drive.stop()


# --------------------------------------------------------------------------------------
# Teleop
# --------------------------------------------------------------------------------------

TELEOP_HELP = """
  w / s    forward / reverse
  a / d    spin left / spin right
  q / e    veer left / veer right (arc while moving)
  space    stop, holding the current idle mode
  b / c    stop with BRAKE / stop with COAST
  1 .. 9   set speed to 10 .. 90 %
  + / -    speed up / down by 10 %
  h        this help
  x        quit
""".rstrip()


def run_teleop(drive: Drive, cfg: Dict[str, Any], args: argparse.Namespace) -> int:
    if not sys.stdin.isatty():
        print("teleop needs an interactive terminal (stdin is not a tty).", file=sys.stderr)
        return 1
    try:
        import termios
        import tty
    except ImportError:  # pragma: no cover
        print("teleop needs a POSIX terminal (termios).", file=sys.stderr)
        return 1

    speed = clamp(float(args.speed) / 100.0, 0.1, 1.0)
    action = "stop"
    print(TELEOP_HELP)
    print(f"  speed = {speed * 100:.0f}%   (press x to quit)")
    print(f"  idle mode = {drive.idle_mode}")

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    quit_requested = False
    try:
        tty.setcbreak(fd)
        while not quit_requested and not drive.aborted:
            if drive.expired():
                print("\n  runtime limit reached.")
                break
            ready, _, _ = select.select([sys.stdin], [], [], 0.05)
            if not ready:
                continue
            for ch in sys.stdin.read(1):
                if ch in ("x", "X", "\x03", "\x04"):
                    quit_requested = True
                elif ch == "w":
                    action = "forward"
                elif ch == "s":
                    action = "reverse"
                elif ch == "a":
                    action = "spin_left"
                elif ch == "d":
                    action = "spin_right"
                elif ch == "q":
                    action = "veer_left"
                elif ch == "e":
                    action = "veer_right"
                elif ch == " ":
                    action = "stop"
                elif ch == "b":
                    drive.idle_mode = "brake"
                    action = "stop"
                elif ch == "c":
                    drive.idle_mode = "coast"
                    action = "stop"
                elif ch in "+=":
                    speed = clamp(speed + 0.1, 0.1, 1.0)
                elif ch in "-_":
                    speed = clamp(speed - 0.1, 0.1, 1.0)
                elif ch in "123456789":
                    speed = int(ch) / 10.0
                elif ch == "h":
                    print(TELEOP_HELP)

            if action == "forward":
                drive.steer(speed, 0.0)
            elif action == "reverse":
                drive.steer(-speed, 0.0)
            elif action == "spin_left":
                drive.steer(0.0, speed)
            elif action == "spin_right":
                drive.steer(0.0, -speed)
            elif action == "veer_left":
                drive.steer(speed, speed * 0.5)
            elif action == "veer_right":
                drive.steer(speed, -speed * 0.5)
            else:
                drive.stop(wait=False)

            print(
                f"\r  {action:<11} speed {speed * 100:3.0f}%   {drive.status()}   ",
                end="",
                flush=True,
            )
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        print()
    drive.stop()
    return 0


# --------------------------------------------------------------------------------------
# Configuration handling
# --------------------------------------------------------------------------------------

#: Sequence step token -> canonical action. The short aliases are for typing quickly.
STEP_ACTIONS: Dict[str, str] = {
    "forward": "forward", "f": "forward", "fwd": "forward",
    "reverse": "reverse", "rev": "reverse", "back": "reverse", "b": "reverse",
    "left": "left", "l": "left",
    "right": "right", "r": "right",
    "veerleft": "veerleft", "arcleft": "veerleft",
    "veerright": "veerright", "arcright": "veerright",
    "backleft": "backleft", "backright": "backright",
    "stop": "stop", "wait": "stop", "s": "stop",
    "brake": "brake",
    "coast": "coast",
}

#: One-line description per canonical action, used in the plan and in step progress.
STEP_HELP: Dict[str, str] = {
    "forward": "straight forward",
    "reverse": "straight back",
    "left": "spin in place, left (CCW)",
    "right": "spin in place, right (CW)",
    "veerleft": "arc forward and left",
    "veerright": "arc forward and right",
    "backleft": "arc backward and left",
    "backright": "arc backward and right",
    "stop": "hold still (coasts)",
    "brake": "hold with the bridge shorted (braked)",
    "coast": "hold with the outputs floating",
}

#: Actions that accept a turn-bias value in addition to speed.
STEP_USES_TURN = ("veerleft", "veerright", "backleft", "backright")

#: Named values a step may use instead of positionals.
STEP_NAMED_KEYS = ("seconds", "time", "s", "speed", "turn")

#: Refuse to expand a sequence beyond this many steps (a runaway repeat would eat RAM).
MAX_SEQUENCE_STEPS = 20000


def _expand_repeats(text: str, where: str) -> str:
    """
    Rewrite `repeat <n> { <steps> }` groups into the flat step text they stand for.

    Expanding textually (rather than into step objects) means every existing step error
    still quotes the exact step it came from, and nesting works for free.
    """

    def walk(start: int, depth: int) -> Tuple[str, int]:
        buffer = ""
        index = start
        while index < len(text):
            char = text[index]
            if char == "#":
                while index < len(text) and text[index] != "\n":
                    index += 1
                continue
            if char == "{":
                match = re.search(r"repeat\s+([0-9][0-9_]*)\s*$", buffer, re.IGNORECASE)
                if not match:
                    raise MotorError(
                        f"{where}: '{{' must be preceded by 'repeat <count>', e.g. "
                        "repeat 5 { forward 1, stop 1 }"
                    )
                count = int(match.group(1).replace("_", ""))
                if count < 1:
                    raise MotorError(
                        f"{where}: repeat count must be at least 1 "
                        "(use --repeat 0 to loop the whole sequence instead)"
                    )
                buffer = buffer[: match.start()]
                body, index = walk(index + 1, depth + 1)
                buffer += ", ".join([body.strip()] * count)
                continue
            if char == "}":
                if depth == 0:
                    raise MotorError(f"{where}: unmatched '}}' in the sequence")
                return buffer, index + 1
            buffer += char
            index += 1
        if depth > 0:
            raise MotorError(f"{where}: a repeat group is missing its closing '}}'")
        return buffer, index

    expanded, _ = walk(0, 0)
    return expanded


def _step_number(token: str, what: str, step_label: str) -> float:
    try:
        return float(token.strip().rstrip("%"))
    except ValueError:
        raise MotorError(
            f"sequence step '{step_label}': {what} must be a number, got {token!r}"
        ) from None


def parse_sequence(text: str, cfg: Dict[str, Any], where: str = "sequence") -> List[Dict[str, Any]]:
    """
    Parse a step list into dicts.

        "forward 5 60, left 3 50, veerright 4 60 30, brake 2"
        "repeat 20 { forward 0.5, stop 0.5 }"

    Each step is <action> <seconds> [speed%] [turn%]; values may also be named
    (`seconds=5 speed=60`). Separators are commas or semicolons, `#` starts a comment,
    omitted speed/turn fall back to the config's motion.speed / motion.turn_rate, and
    `repeat <n> { ... }` expands a group n times.
    """
    text = _expand_repeats(text, where)
    default_speed = float(cfg["motion"]["speed"])
    default_turn = float(cfg["motion"]["turn_rate"])
    steps: List[Dict[str, Any]] = []

    for raw in re.split(r"[,;\n]", text):
        chunk = raw.split("#", 1)[0].strip()
        if not chunk:
            continue
        tokens = chunk.split()
        token_action = tokens[0].lower()
        if token_action == "repeat":
            raise MotorError(
                f"sequence step '{chunk}': 'repeat' must be followed by '{{ ... }}', "
                "e.g. repeat 5 { forward 1, stop 1 }"
            )
        if token_action not in STEP_ACTIONS:
            raise MotorError(
                f"unknown sequence action '{tokens[0]}' in step '{chunk}'.\n"
                "  valid actions: " + ", ".join(sorted(set(STEP_ACTIONS.values())))
            )
        action = STEP_ACTIONS[token_action]

        positionals: List[str] = []
        named: Dict[str, str] = {}
        for token in tokens[1:]:
            if "=" in token:
                key, _, value = token.partition("=")
                named[key.strip().lower()] = value.strip()
            else:
                positionals.append(token)
        unknown = [key for key in named if key not in STEP_NAMED_KEYS]
        if unknown:
            raise MotorError(
                f"sequence step '{chunk}': unknown option(s) {unknown}; "
                f"expected one of {list(STEP_NAMED_KEYS)}"
            )

        time_key = next((key for key in ("seconds", "time", "s") if key in named), None)
        if positionals:
            seconds = _step_number(positionals[0], "seconds", chunk)
        elif time_key is not None:
            seconds = _step_number(named[time_key], "seconds", chunk)
        else:
            raise MotorError(
                f"sequence step '{chunk}': a duration in seconds is required, "
                f"e.g. '{token_action} 3 50'"
            )

        if len(positionals) > 1:
            speed = _step_number(positionals[1], "speed", chunk)
        elif "speed" in named:
            speed = _step_number(named["speed"], "speed", chunk)
        else:
            speed = default_speed

        if action in STEP_USES_TURN:
            if len(positionals) > 2:
                turn = _step_number(positionals[2], "turn", chunk)
            elif "turn" in named:
                turn = _step_number(named["turn"], "turn", chunk)
            else:
                turn = default_turn
        else:
            turn = default_turn

        if not 0.0 < seconds <= 600.0:
            raise MotorError(f"sequence step '{chunk}': seconds must be in (0, 600]")
        if not 0.0 <= speed <= 100.0:
            raise MotorError(f"sequence step '{chunk}': speed must be 0-100")
        if not 0.0 <= turn <= 100.0:
            raise MotorError(f"sequence step '{chunk}': turn must be 0-100")

        steps.append(
            {"action": action, "seconds": seconds, "speed": speed, "turn": turn,
             "source": chunk}
        )

    if len(steps) > MAX_SEQUENCE_STEPS:
        raise MotorError(
            f"{where}: expands to {len(steps)} steps (limit {MAX_SEQUENCE_STEPS}); "
            "reduce the repeat count or use --repeat to loop instead"
        )
    return steps


def parse_sequence_file(path: str, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Load steps from JSON: either a bare list or {"steps": [...]} (a top-level "repeat" is
    honoured). Each element is a DSL string, an object {"action": ..., "seconds": ...}, or
    a group {"repeat": n, "steps": [...]}.

    Objects are re-serialised into the DSL and parsed by the same code, so every form gets
    identical validation.
    """
    where = f"sequence file {path}"
    try:
        with open(path, "r") as handle:
            loaded = json.load(handle)
    except FileNotFoundError as exc:
        raise MotorError(f"sequence file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise MotorError(f"sequence file is not valid JSON ({path}): {exc}") from exc

    if isinstance(loaded, dict):
        top_repeat = loaded.get("repeat", 1)
        loaded = loaded.get("steps", [])
        if top_repeat != 1:
            loaded = [{"repeat": top_repeat, "steps": loaded}]
    if not isinstance(loaded, list):
        raise MotorError(f'sequence file must be a list or {{"steps": [...]}}: {path}')

    def from_list(items: Any, what: str) -> List[Dict[str, Any]]:
        steps: List[Dict[str, Any]] = []
        if not isinstance(items, list):
            raise MotorError(f"{what}: expected a list of steps")
        for index, item in enumerate(items, start=1):
            if isinstance(item, str):
                steps.extend(parse_sequence(item, cfg, what))
                continue
            if isinstance(item, dict) and "repeat" in item:
                count = item["repeat"]
                if not isinstance(count, int) or count < 1:
                    raise MotorError(f"{what} item {index}: 'repeat' must be an integer >= 1")
                body = from_list(item.get("steps", []), what)
                for _ in range(count):
                    steps.extend(dict(step) for step in body)
                continue
            if isinstance(item, dict) and "action" in item:
                parts = [str(item["action"])]
                if "seconds" in item:
                    parts.append(str(item["seconds"]))
                if "speed" in item:
                    parts.append(f"speed={item['speed']}")
                if "turn" in item:
                    parts.append(f"turn={item['turn']}")
                steps.extend(parse_sequence(" ".join(parts), cfg, what))
                continue
            raise MotorError(
                f"{what} item {index} must be a string, an object with 'action', "
                'or {"repeat": n, "steps": [...]}'
            )
        return steps

    return from_list(loaded, where)


def step_targets(step: Dict[str, Any]) -> Tuple[float, float]:
    """A step -> (linear, turn) for Drive.steer()."""
    speed = step["speed"] / 100.0
    bias = step["turn"] / 100.0
    return {
        "forward": (speed, 0.0),
        "reverse": (-speed, 0.0),
        "left": (0.0, speed),
        "right": (0.0, -speed),
        "veerleft": (speed, bias),
        "veerright": (speed, -bias),
        "backleft": (-speed, bias),
        "backright": (-speed, -bias),
    }.get(step["action"], (0.0, 0.0))


def describe_step(step: Dict[str, Any]) -> str:
    action = step["action"]
    text = f"{action:<10} {step['seconds']:>6.1f} s"
    if action in ("stop", "brake", "coast"):
        return f"{text}   {STEP_HELP[action]}"
    text += f"  at {step['speed']:>3.0f}%"
    if action in STEP_USES_TURN:
        text += f", turn {step['turn']:>3.0f}%"
    return f"{text}   {STEP_HELP[action]}"


def print_sequence_plan(steps: List[Dict[str, Any]], repeat: int = 1) -> None:
    per_cycle = sum(step["seconds"] for step in steps)
    if repeat == 0:
        print(f"\n  sequence: {len(steps)} steps, looping until stopped "
              f"({per_cycle:.1f} s per cycle)")
    elif repeat > 1:
        print(f"\n  sequence: {len(steps)} steps x {repeat} cycles, "
              f"{per_cycle * repeat:.1f} s of motion")
    else:
        print(f"\n  sequence: {len(steps)} steps, {per_cycle:.1f} s of motion")
    for index, step in enumerate(steps, start=1):
        print(f"    {index:>2}. {describe_step(step)}")
    if repeat == 0:
        print("    ... then back to step 1 until Ctrl+C")


def resolve_config(args: argparse.Namespace) -> Tuple[Dict[str, Any], List[str]]:
    """Build the effective config from defaults + file + CLI flags, and validate it."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy

    if args.config:
        try:
            with open(args.config, "r") as handle:
                loaded = json.load(handle)
        except FileNotFoundError as exc:
            raise MotorError(f"config file not found: {args.config}") from exc
        except json.JSONDecodeError as exc:
            raise MotorError(f"config file is not valid JSON ({args.config}): {exc}") from exc
        if not isinstance(loaded, dict):
            raise MotorError(f"config file must contain a JSON object: {args.config}")
        cfg = deep_merge(cfg, loaded)

    # --- CLI overrides (only when the user actually supplied the flag) --------------
    if args.chip is not None:
        cfg["chip"] = args.chip
    if args.left_pins:
        cfg["pins"]["left"].update(zip(("en", "in1", "in2"), args.left_pins))
    if args.right_pins:
        cfg["pins"]["right"].update(zip(("en", "in3", "in4"), args.right_pins))
    if args.invert_left:
        cfg["pins"]["left"]["invert"] = not cfg["pins"]["left"]["invert"]
    if args.invert_right:
        cfg["pins"]["right"]["invert"] = not cfg["pins"]["right"]["invert"]
    if args.trim_left is not None:
        cfg["trim"]["left"] = args.trim_left
    if args.trim_right is not None:
        cfg["trim"]["right"] = args.trim_right
    for flag, path in (
        (args.max_duty, ("limits", "max_duty")),
        (args.min_duty, ("limits", "min_duty")),
        (args.deadband, ("limits", "deadband")),
        (args.accel, ("limits", "accel")),
        (args.decel, ("limits", "decel")),
        (args.rate, ("control", "rate_hz")),
        (args.freq, ("control", "pwm_freq")),
        (args.max_runtime, ("safety", "max_runtime_s")),
        (args.turn_ms, ("geometry", "turn_ms_90")),
        (args.turn_speed, ("geometry", "turn_speed")),
        (args.log, ("logging", "csv")),
    ):
        if flag is not None:
            section, key = path
            cfg[section][key] = flag
    if args.idle_mode:
        cfg["control"]["idle_mode"] = args.idle_mode

    # Motion knobs can come from either the config file or the CLI; mirror the winner back
    # onto `args` so every maneuver reads from exactly one source of truth.
    for flag, key in (
        (args.speed, "speed"),
        (args.duration, "duration_s"),
        (args.turn_rate, "turn_rate"),
        (args.pulse_ms, "pulse_ms"),
    ):
        if flag is not None:
            cfg["motion"][key] = flag
    if float(cfg["motion"]["duration_s"]) <= 0:
        raise MotorError("motion.duration_s must be > 0")
    if float(cfg["motion"]["pulse_ms"]) < 50:
        raise MotorError("motion.pulse_ms must be at least 50 ms")
    args.speed = float(cfg["motion"]["speed"])
    args.duration = float(cfg["motion"]["duration_s"])
    args.turn_rate = float(cfg["motion"]["turn_rate"])
    args.pulse_ms = float(cfg["motion"]["pulse_ms"])
    if args.repeat is not None:
        cfg["motion"]["repeat"] = args.repeat
    args.repeat = int(cfg["motion"]["repeat"])
    if args.repeat < 0:
        raise MotorError("motion.repeat must be >= 0 (0 loops until stopped)")

    # A step list from --sequence / --sequence-file selects the `sequence` maneuver.
    args.steps = []
    if args.sequence:
        args.steps = parse_sequence(args.sequence, cfg)
        if not args.steps:
            raise MotorError('--sequence was given but contained no steps')
    if args.sequence_file:
        args.steps.extend(parse_sequence_file(args.sequence_file, cfg))
    if args.steps:
        args.maneuver = "sequence"

    warnings = validate_config(cfg, allow_reserved=args.allow_reserved)
    return cfg, warnings


def validate_config(cfg: Dict[str, Any], allow_reserved: bool) -> List[str]:
    warnings: List[str] = []
    pins = cfg["pins"]

    all_pins: List[int] = []
    for side in ("left", "right"):
        for key, value in pins[side].items():
            if key == "invert":
                continue
            try:
                pin = int(value)
            except (TypeError, ValueError) as exc:
                raise MotorError(f"pins.{side}.{key} must be an integer, got {value!r}") from exc
            if not 0 <= pin <= MAX_HEADER_GPIO:
                raise MotorError(
                    f"pins.{side}.{key} = GPIO{pin} is not on the 40-way header "
                    f"(header GPIOs are 0-{MAX_HEADER_GPIO})"
                )
            if pin in FORBIDDEN_PINS:
                message = (
                    f"GPIO{pin} ({phys(pin)}) is reserved: {FORBIDDEN_PINS[pin]}"
                )
                if not allow_reserved:
                    raise MotorError(
                        message
                        + "\n  Refusing to use it. Pick another pin, or pass --allow-reserved "
                        "if you truly know what you are doing."
                    )
                warnings.append(f"FORCED reserved pin — {message}")
            elif pin in DISCOURAGED_PINS:
                warnings.append(f"GPIO{pin} ({phys(pin)}) is normally {DISCOURAGED_PINS[pin]}")
            pins[side][key] = pin
            all_pins.append(pin)

    duplicates = {pin for pin in all_pins if all_pins.count(pin) > 1}
    if duplicates:
        raise MotorError(f"pin(s) used more than once: {sorted(duplicates)}")

    limits = cfg["limits"]
    if not 0.0 <= float(limits["min_duty"]) <= float(limits["max_duty"]) <= 100.0:
        raise MotorError("limits must satisfy 0 <= min_duty <= max_duty <= 100")
    if not 0.0 <= float(limits["deadband"]) < 1.0:
        raise MotorError("limits.deadband must be in [0, 1)")
    if float(limits["accel"]) <= 0 or float(limits["decel"]) <= 0:
        raise MotorError("limits.accel and limits.decel must be > 0")
    if not 1.0 <= float(cfg["control"]["rate_hz"]) <= 500.0:
        raise MotorError("control.rate_hz must be between 1 and 500")
    if not 0.1 <= float(cfg["control"]["pwm_freq"]) <= 10000.0:
        raise MotorError("control.pwm_freq must be between 0.1 and 10000 Hz (lgpio limit)")
    if cfg["control"]["idle_mode"] not in ("coast", "brake"):
        raise MotorError("control.idle_mode must be 'coast' or 'brake'")
    for side in ("left", "right"):
        if not 0.0 < float(cfg["trim"][side]) <= 1.5:
            raise MotorError(f"trim.{side} must be in (0, 1.5]")

    deduped: List[str] = []
    for warning in warnings:
        if warning not in deduped:
            deduped.append(warning)
    return deduped


def pin_roles(cfg: Dict[str, Any]) -> Dict[int, str]:
    pins = cfg["pins"]
    return {
        pins["left"]["en"]: "L.en",
        pins["left"]["in1"]: "L.in1",
        pins["left"]["in2"]: "L.in2",
        pins["right"]["en"]: "R.en",
        pins["right"]["in3"]: "R.in3",
        pins["right"]["in4"]: "R.in4",
    }


def preflight_pins(cfg: Dict[str, Any]) -> List[str]:
    """Ask gpioinfo whether anything already owns our pins. Best effort, never fatal."""
    roles = pin_roles(cfg)
    owners = gpioinfo_map()
    conflicts: List[str] = []
    for pin, role in sorted(roles.items()):
        entry = owners.get(pin)
        if entry and entry[1]:
            conflicts.append(f"  GPIO{pin} ({role}, {phys(pin)}) is owned by '{entry[1]}'")
    return conflicts


# --------------------------------------------------------------------------------------
# Presentation
# --------------------------------------------------------------------------------------


def print_wiring(cfg: Dict[str, Any]) -> None:
    pins = cfg["pins"]
    print(
        """
L298N  <->  Raspberry Pi 4  (BCM numbering, header physical pin in brackets)
---------------------------------------------------------------------------
  LEFT  side   OUT1/OUT2   (two motors wired in parallel)
      ENA   <-  GPIO%-2d %-9s
      IN1   <-  GPIO%-2d %-9s
      IN2   <-  GPIO%-2d %-9s
  RIGHT side   OUT3/OUT4   (two motors wired in parallel)
      IN3   <-  GPIO%-2d %-9s
      IN4   <-  GPIO%-2d %-9s
      ENB   <-  GPIO%-2d %-9s
  GND       <->  any Pi GND  (pin 6, 9, 14, 20, 25, 30, 34 or 39)  ** MANDATORY **

Power
  +12V/VS   <- separate battery pack (2S Li-ion 7.4 V or 6xAA 9 V). The L298N drops
                ~1.8-2 V, so 7.4 V in is about 5.5 V at the motors. That is expected.
  5V jumper : leave fitted when VS >= 7 V (the onboard regulator makes the logic 5 V).
              Never link the L298N +5V pin to the Pi 5V pin at the same time.
  Motors    : NEVER from the Pi's 5V pin.
  Ground    : Pi GND and L298N GND MUST be common, or PWM has no reference.

Before you power up
  * Remove the ENA and ENB jumpers on the L298N, otherwise the enable pins are tied
    high and this script's speed control does nothing (motors will be full speed or off).
  * Fit the L298N heatsink; two motors in parallel can pull ~2 A per channel.
  * Put the car on blocks for the first run.
"""
        % (
            pins["left"]["en"], f"({phys(pins['left']['en'])})",
            pins["left"]["in1"], f"({phys(pins['left']['in1'])})",
            pins["left"]["in2"], f"({phys(pins['left']['in2'])})",
            pins["right"]["in3"], f"({phys(pins['right']['in3'])})",
            pins["right"]["in4"], f"({phys(pins['right']['in4'])})",
            pins["right"]["en"], f"({phys(pins['right']['en'])})",
        )
    )
    tuning = cfg["limits"]
    print(
        "Current limits: max_duty=%.0f%%  min_duty=%.0f%%  deadband=%.2f  "
        "accel=%.0f%%/s  decel=%.0f%%/s  pwm=%.0fHz  idle=%s\n"
        % (
            tuning["max_duty"], tuning["min_duty"], tuning["deadband"],
            tuning["accel"], tuning["decel"], cfg["control"]["pwm_freq"],
            cfg["control"]["idle_mode"],
        )
    )


def print_reserved() -> None:
    print("\nHeader pins this script refuses to drive:\n")
    for pin, reason in sorted(FORBIDDEN_PINS.items()):
        print(f"  GPIO{pin:<3} {phys(pin):<15} {reason}")
    print("\nHeader pins it warns about (usable, but normally something else's):\n")
    for pin, reason in sorted(DISCOURAGED_PINS.items()):
        print(f"  GPIO{pin:<3} {phys(pin):<15} {reason}")
    print(
        """
Two GPIO chips exist on this Pi 4:

  gpiochip0  pinctrl-bcm2711       58 lines   <- the 40-pin header (what this script uses)
  gpiochip1  raspberrypi-exp-gpio   8 lines   <- firmware expander, NOT the header

Do not confuse them. gpioinfo lists "CAM_GPIO" (camera rail) and "SD_PWR_ON" (microSD
power) as lines 5 and 6 of the EXPANDER - not as header pins 5 and 6. The header's own
GPIO5/GPIO6 are ordinary free pins; the expander's are load-bearing. This script picks the
SoC chip by device-tree label and refuses to run against the expander.

Also note: GPIO14/15 look free to every runtime check, yet the serial console (mini-UART
ttyS0, per console=serial0,115200) uses them via a firmware-set pin mux. Policy, not a
probe, is what keeps you off them.
"""
    )


def list_chips() -> int:
    try:
        import lgpio  # type: ignore
    except ImportError:
        print("lgpio is not available; cannot enumerate GPIO chips.", file=sys.stderr)
        return 2
    print("\nGPIO chips on this machine:\n")
    for number in range(0, 8):
        try:
            handle = lgpio.gpiochip_open(number)
        except Exception:
            continue
        info = chip_info(lgpio, handle)
        label = str(info.get("label") or "?")
        is_soc = any(want in label for want in LgpioBackend.LABELS)
        note = "  <- the 40-pin header; this script uses this one" if is_soc else \
               "  <- not the header; ignored"
        print(f"  gpiochip{number}: {label:<24} {info.get('lines')} lines{note}")
        lgpio.gpiochip_close(handle)
    print()
    return 0


def print_config_summary(cfg: Dict[str, Any], backend_name: str) -> None:
    pins = cfg["pins"]
    print(f"  backend      : {backend_name}")
    print(
        "  pins         : "
        f"L en={pins['left']['en']} in={pins['left']['in1']}/{pins['left']['in2']}"
        f"{' (inverted)' if pins['left']['invert'] else ''}   "
        f"R en={pins['right']['en']} in={pins['right']['in3']}/{pins['right']['in4']}"
        f"{' (inverted)' if pins['right']['invert'] else ''}"
    )
    print(
        f"  trim         : left={cfg['trim']['left']:.2f} right={cfg['trim']['right']:.2f}"
        f"   idle={cfg['control']['idle_mode']}   rate={cfg['control']['rate_hz']:.0f} Hz"
    )


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="test_motors.py",
        description="L298N 4-wheel motor test rig (Raspberry Pi 4, BCM2711).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  test_motors.py --wiring\n"
            "  test_motors.py -m forward --dry-run --duration 2\n"
            "  test_motors.py -m wiring --pulse-ms 600\n"
            "  test_motors.py -m dance --max-duty 70 --log motor_log.csv\n"
            "  test_motors.py --teleop --speed 45\n"
            '  test_motors.py --sequence "forward 5 60, left 3 50, veerright 4 60 30"\n'
            '  test_motors.py --sequence "repeat 20 { forward 0.5 60, stop 0.5 }"\n'
            '  test_motors.py --sequence "forward 1, stop 1" --repeat 0\n'
            "  test_motors.py --write-config src/motor_config.json\n"
        ),
    )
    parser.add_argument("-m", "--maneuver", default="dance", help="maneuver to run (see --list)")
    parser.add_argument("--list", action="store_true", help="list maneuvers and exit")
    parser.add_argument("--wiring", action="store_true", help="print the wiring checklist and exit")
    parser.add_argument("--list-reserved", action="store_true", help="print the pin-safety table")
    parser.add_argument("--list-chips", action="store_true", help="enumerate GPIO chips and exit")
    parser.add_argument("--teleop", action="store_true", help="interactive keyboard driving")
    parser.add_argument(
        "--sequence", metavar="STEPS",
        help='chain steps, e.g. "forward 5 60, left 3 50, brake 2"',
    )
    parser.add_argument(
        "--sequence-file", metavar="FILE.json",
        help="JSON list of steps to chain (strings or {'action':...,'seconds':...})",
    )
    parser.add_argument(
        "--repeat", type=int, metavar="N",
        help="run the sequence N times; 0 repeats until stopped (Ctrl+C or --max-runtime)",
    )
    parser.add_argument("--dry-run", action="store_true", help="no hardware; print pin activity")
    parser.add_argument("--yes", action="store_true", help="skip the start countdown")
    parser.add_argument("--quiet", action="store_true", help="less chatter")

    group = parser.add_argument_group("configuration")
    group.add_argument("--config", metavar="FILE", help="JSON config to merge over the defaults")
    group.add_argument("--write-config", metavar="FILE", help="write the effective config and exit")
    group.add_argument("--print-config", action="store_true", help="print effective config and exit")
    group.add_argument("--chip", type=int, help="gpiochip number (default: auto-detect)")
    group.add_argument(
        "--left-pins", type=lambda s: [int(x) for x in s.split(",")], metavar="EN,IN1,IN2",
        help="override the left side pins",
    )
    group.add_argument(
        "--right-pins", type=lambda s: [int(x) for x in s.split(",")], metavar="EN,IN3,IN4",
        help="override the right side pins",
    )
    group.add_argument("--invert-left", action="store_true", help="flip the left side's direction")
    group.add_argument("--invert-right", action="store_true", help="flip the right side's direction")
    group.add_argument("--trim-left", type=float, help="left side gain (0-1.5)")
    group.add_argument("--trim-right", type=float, help="right side gain (0-1.5)")
    group.add_argument("--allow-reserved", action="store_true", help="permit reserved pins anyway")

    group = parser.add_argument_group("tuning")
    group.add_argument("--max-duty", type=float, help="duty ceiling in %% (default 90)")
    group.add_argument("--min-duty", type=float, help="deadband floor in %% (default 22)")
    group.add_argument("--deadband", type=float, help="commanded deadband, 0-1 (default 0.12)")
    group.add_argument("--accel", type=float, help="duty %%/s while accelerating")
    group.add_argument("--decel", type=float, help="duty %%/s while decelerating")
    group.add_argument("--rate", type=float, help="control loop rate in Hz (default 50)")
    group.add_argument("--freq", type=float, help="PWM frequency in Hz (default 1000)")
    group.add_argument("--idle-mode", choices=("coast", "brake"), help="what 'stopped' means")
    group.add_argument("--turn-ms", type=float, help="measured ms for a 90 degree spin")
    group.add_argument("--turn-speed", type=float, help="duty %% for that spin")

    group = parser.add_argument_group("motion")
    group.add_argument("--speed", type=float, help="speed in %% for straight/arc moves (default 60)")
    group.add_argument("--duration", type=float, help="hold time in seconds for straight/arc moves")
    group.add_argument("--turn-rate", type=float, help="turn bias in %% for arcs (default 35)")
    group.add_argument("--pulse-ms", type=float, help="pulse length for --maneuver pulse/wiring")
    group.add_argument("--max-runtime", type=float, help="hard stop after N seconds (0 = off)")
    group.add_argument("--log", metavar="FILE.csv", help="write control-loop telemetry")

    parser.add_argument("--version", action="version", version=f"test_motors.py {__version__}")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Informational modes that need no config resolution beyond the defaults.
    if args.list:
        print("\nManeuvers:\n")
        for name, (_, description) in MANEUVERS.items():
            print(f"  {name:<12} {description}")
        print("\n  Run one with:  -m <name>      Everything:  -m dance")
        print('  Chain several: --sequence "forward 5 60, left 3 50, brake 2"\n')
        return 0

    try:
        cfg, warnings = resolve_config(args)
    except MotorError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    if args.list_reserved:
        print_reserved()
        return 0

    if args.list_chips:
        return list_chips()

    if args.write_config:
        with open(args.write_config, "w") as handle:
            json.dump(cfg, handle, indent=2)
            handle.write("\n")
        print(f"wrote {args.write_config}")
        return 0

    if args.print_config:
        print(json.dumps(cfg, indent=2))
        return 0

    if args.wiring:
        print_wiring(cfg)
        return 0

    # A `sequence` run with no steps is a usage mistake, not a hardware problem, so catch
    # it before any GPIO is touched.
    if args.maneuver == "sequence" and not args.steps:
        print(
            "'sequence' needs steps:\n"
            '  --sequence "forward 5 60, left 3 50, brake 2"\n'
            "  --sequence-file steps.json",
            file=sys.stderr,
        )
        return 1

    # --- banner --------------------------------------------------------------------
    print("=" * 68)
    print(f" L298N 4-wheel motor test — test_motors.py {__version__}")
    print(f" board: {board_model()}")
    print("=" * 68)

    # --- backend --------------------------------------------------------------------
    backend: Optional[Backend] = None
    hardware = not args.dry_run
    if hardware:
        try:
            backend = LgpioBackend(cfg["chip"])
        except MotorError as exc:
            print(f"\nhardware backend unavailable:\n  {exc}", file=sys.stderr)
            if args.chip is not None:
                # An explicit --chip that does not work is a mistake, not something to
                # silently paper over with a dry run.
                return 2
            print("\nFalling back to --dry-run so you can still exercise the logic.")
            hardware = False
        except Exception as exc:  # lgpio raises its own error type on a bad chip
            print(f"\ncould not open GPIO chip: {exc}", file=sys.stderr)
            print("  Hint: on a Pi 4 the number is usually 0; run --list-chips.\n")
            if args.chip is not None:
                return 2
            print("Falling back to --dry-run.")
            hardware = False

    if not hardware:
        backend = DryRunBackend(pin_roles(cfg))
        print("\n*** DRY RUN — no GPIO will be driven. ***")

    assert backend is not None
    print_config_summary(cfg, backend.name)

    # --- preflight ------------------------------------------------------------------
    if not args.quiet:
        conflicts = preflight_pins(cfg)
        if conflicts:
            print("\nWARNING: pins already owned by something else:")
            for line in conflicts:
                print(line)
            if hardware and not args.allow_reserved:
                print("\nRefusing to claim them. Free the pins, or pick others.\n")
                backend.close()
                return 2
    if not args.quiet:
        for warning in warnings:
            print(f"  note: {warning}")

    if args.maneuver not in MANEUVERS:
        print(f"\nunknown maneuver '{args.maneuver}'. Try --list.", file=sys.stderr)
        backend.close()
        return 1

    # --- move! ----------------------------------------------------------------------
    try:
        drive = Drive(cfg, backend, verbose=not args.quiet)
    except MotorError as exc:
        print(f"\ncould not claim the pins: {exc}", file=sys.stderr)
        print("  Check the pin map (--wiring) and that nothing else owns those lines.",
              file=sys.stderr)
        backend.close()
        return 2

    def _on_terminate(*_: Any) -> None:
        drive.abort()

    # SIGHUP matters here: this is driven over SSH, and if the session drops the car
    # should stop deliberately rather than just having its process killed.
    handled = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        handled.append(signal.SIGHUP)
    for sig in handled:
        try:
            signal.signal(sig, _on_terminate)
        except (ValueError, OSError):  # pragma: no cover - not the main thread
            pass

    # Teleop has its own safety — nothing moves until a key is pressed — so no countdown.
    if args.steps and not args.quiet:
        print_sequence_plan(args.steps, args.repeat)

    if not args.yes and not args.dry_run and not args.teleop and args.maneuver != "stop":
        print("\n  Motors will move. Ctrl+C to abort.")
        for remaining in (3, 2, 1):
            if drive.aborted:
                break
            print(f"  starting in {remaining}...", flush=True)
            time.sleep(1)

    interrupted = False
    exit_code = 0
    try:
        drive.start()
        if args.teleop:
            exit_code = run_teleop(drive, cfg, args)
        else:
            description = MANEUVERS[args.maneuver][1]
            _sep(f"{args.maneuver} — {description}")
            t0 = time.monotonic()
            MANEUVERS[args.maneuver][0](drive, cfg, args)
            if drive.expired():
                print("\n  runtime limit reached — stopping early.")
            print(f"\n  finished in {time.monotonic() - t0:.1f} s")
    except KeyboardInterrupt:
        interrupted = True
        print("\n  interrupted.")
    except MotorError as exc:
        print(f"\nhardware error: {exc}", file=sys.stderr)
        exit_code = 2
    finally:
        drive.stop(wait=False)
        drive.close()
        print("  outputs parked, GPIO released.")

    if interrupted or drive.aborted:
        return 130
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
