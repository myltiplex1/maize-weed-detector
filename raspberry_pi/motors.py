#!/usr/bin/env python3
"""
motors.py - drive the robot's 4 wheel motors (L298N-style driver) from the Raspberry Pi,
and follow a predefined route. Test it on its own, or let weed_robot.py --drive use it.

Wiring (from the team):
  LEFT  motors (both together):  ENA = GPIO12, IN1 = GPIO17, IN2 = GPIO27
  RIGHT motors (both together):  ENB = GPIO13, IN3 = GPIO22, IN4 = GPIO23
  Pi GND connected to the driver's GND; motors powered from their own battery.
  (Indicator LEDs are on GPIO24 - no clash.)

Tests (inside ~/maize_weed with the venv active). LIFT THE WHEELS OFF THE GROUND for the first tests!
  python motors.py --side-test       # left side only, then right side only (checks wiring + direction)
  python motors.py --test            # forward, backward, left, right - 1.5 s each
  python motors.py --drive           # drive by keyboard: w/s/a/d, space = stop, +/- speed, q = quit
  python motors.py --route           # run the ROUTE below once
  python motors.py --test --speed 0.3
Ctrl+C always stops the motors.
"""
import argparse, sys, threading, time

# ---------------------------------------------------------------- settings to edit
PINS = {
    'left':  {'forward': 17, 'backward': 27, 'enable': 12},   # IN1, IN2, ENA
    'right': {'forward': 22, 'backward': 23, 'enable': 13},   # IN3, IN4, ENB
}
SPEED = 0.35        # 0.0-1.0 of full power. Slow for weeding. If the wheels only hum and don't turn, raise it a little.
TURN_SPEED = 0.40   # turning on the spot needs a bit more power than driving straight
TRIM = {'left': 1.00, 'right': 1.00}   # if the robot drifts to one side going "straight", lower the FASTER side, e.g. 0.92
INVERT = {'left': False, 'right': False}  # set True if that side spins backwards when told to go forward
RAMP_TIME = 0.4     # seconds to speed up / slow down smoothly (no jerky starts)

# Predefined route: (movement, seconds). Movements: forward, backward, left, right, stop
ROUTE = [
    ('forward', 5.0),
    ('right',   1.2),   # adjust on the real robot until it turns about 90 degrees
    ('forward', 2.0),
    ('right',   1.2),
    ('forward', 5.0),
    ('stop',    0.0),
]


# ---------------------------------------------------------------- motor control
class Motors:
    """Left and right motor pairs with smooth speed changes. Without GPIO (laptop) it only prints."""
    def __init__(self, pins=PINS, speed=SPEED, turn_speed=TURN_SPEED):
        self.speed, self.turn_speed = speed, turn_speed
        self.cur = [0.0, 0.0]                      # current left/right value (-1..1)
        self.lock = threading.Lock()
        self.left = self.right = None
        try:
            from gpiozero import Motor
            self.left, self.right = Motor(**pins['left']), Motor(**pins['right'])
        except Exception as e:
            print(f'(motors not available: {e}) - simulation mode, printing only', flush=True)

    def _apply(self, l, r):
        self.cur = [l, r]
        if self.left is None or self.left.closed: return
        for mot, v, side in ((self.left, l, 'left'), (self.right, r, 'right')):
            v = max(-1.0, min(1.0, v * TRIM[side])) * (-1 if INVERT[side] else 1)
            if v > 0: mot.forward(v)
            elif v < 0: mot.backward(-v)
            else: mot.stop()

    def set(self, l, r, ramp=RAMP_TIME):
        """Go smoothly from the current speeds to (l, r). Values -1..1 (negative = backwards)."""
        with self.lock:
            l0, r0 = self.cur
            steps = max(1, int(ramp / 0.05)) if ramp > 0 else 1
            for i in range(1, steps + 1):
                f = i / steps
                self._apply(l0 + (l - l0) * f, r0 + (r - r0) * f)
                if steps > 1: time.sleep(ramp / steps)

    def move(self, action, speed=None):
        s = speed if speed is not None else (self.turn_speed if action in ('left', 'right') else self.speed)
        target = {'forward': (s, s), 'backward': (-s, -s), 'left': (-s, s), 'right': (s, -s)}.get(action, (0.0, 0.0))
        if self.left is None: print(f'[motors] {action} {s:.2f}', flush=True)
        self.set(*target)

    def stop(self, smooth=True):
        if self.left is None and self.cur != [0.0, 0.0]: print('[motors] stop', flush=True)
        self.set(0.0, 0.0, RAMP_TIME / 2 if smooth else 0)

    def close(self):
        self.stop(smooth=False)
        for mot in (self.left, self.right):
            if mot is not None and not mot.closed: mot.close()


# ---------------------------------------------------------------- route follower
class RouteRunner:
    """Runs ROUTE in a background thread. pause()/resume() stop and restart the wheels;
    paused time does not count, so every step still gets its full duration."""
    def __init__(self, motors, route=ROUTE, loop=False):
        self.m, self.route, self.loop = motors, route, loop
        self._go = threading.Event(); self._go.set()
        self._quit = threading.Event()
        self.step, self.finished = None, False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start(); return self

    def pause(self):
        if self._go.is_set():
            self._go.clear(); self.m.stop()

    def resume(self):
        if not self._go.is_set():
            self._go.set()
            if self.step and not self.finished: self.m.move(self.step)

    def stop(self):
        self._quit.set(); self._go.set()
        if self.thread.is_alive(): self.thread.join(timeout=2)
        self.m.stop(smooth=False)

    def _run(self):
        while not self._quit.is_set():
            for action, secs in self.route:
                if self._quit.is_set(): break
                self.step = action
                print(f'[route] {action} for {secs:.1f} s', flush=True)
                self._go.wait()
                self.m.move(action)
                left = secs
                while left > 0 and not self._quit.is_set():
                    if not self._go.is_set():          # paused: wheels already stopped
                        self._go.wait()
                        if self._quit.is_set(): break
                        self.m.move(action)
                    t = time.monotonic(); time.sleep(min(0.05, left)); left -= time.monotonic() - t
            if not self.loop: break
        self.m.stop(); self.finished = True
        print('[route] finished', flush=True)


# ---------------------------------------------------------------- keyboard driving (works in PuTTY)
def keyboard_drive(m):
    import termios, tty
    print('w = forward, s = backward, a = left, d = right, space = stop, + / - = speed, q = quit', flush=True)
    fd = sys.stdin.fileno(); old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            k = sys.stdin.read(1).lower()
            if k == 'q': break
            elif k in '+=': m.speed = min(1.0, m.speed + 0.05); m.turn_speed = min(1.0, m.turn_speed + 0.05)
            elif k in '-_': m.speed = max(0.1, m.speed - 0.05); m.turn_speed = max(0.1, m.turn_speed - 0.05)
            elif k in 'wsad': m.move({'w': 'forward', 's': 'backward', 'a': 'left', 'd': 'right'}[k])
            elif k == ' ': m.stop()
            print(f'\rspeed {m.speed:.2f} (turn {m.turn_speed:.2f})   ', end='', flush=True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old); print()


# ---------------------------------------------------------------- standalone use
if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Test the wheel motors / drive / run the route')
    ap.add_argument('--side-test', action='store_true', help='left side alone, then right side alone')
    ap.add_argument('--test', action='store_true', help='forward, backward, left, right (1.5 s each)')
    ap.add_argument('--drive', action='store_true', help='drive with the keyboard')
    ap.add_argument('--route', action='store_true', help='run the predefined ROUTE once')
    ap.add_argument('--speed', type=float, default=SPEED)
    a = ap.parse_args()
    m = Motors(speed=a.speed, turn_speed=min(1.0, a.speed + (TURN_SPEED - SPEED)))
    try:
        if a.side_test:
            for name, l, r in (('LEFT side forward', 1, 0), ('LEFT side backward', -1, 0),
                               ('RIGHT side forward', 0, 1), ('RIGHT side backward', 0, -1)):
                print(name, flush=True); m.set(l * m.speed, r * m.speed); time.sleep(1.5); m.stop(); time.sleep(0.7)
            print('If a side turned the wrong way, set INVERT for it to True. If a side did not move, check its wires.')
        elif a.test:
            for act in ('forward', 'backward', 'left', 'right'):
                print(f'{act} 1.5 s', flush=True); m.move(act); time.sleep(1.5); m.stop(); time.sleep(0.7)
        elif a.drive:
            keyboard_drive(m)
        elif a.route:
            r = RouteRunner(m).start()
            while not r.finished: time.sleep(0.2)
        else:
            ap.print_help()
    except KeyboardInterrupt:
        pass
    finally:
        m.close(); print('motors stopped', flush=True)
