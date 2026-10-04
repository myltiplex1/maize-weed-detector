#!/usr/bin/env python3
"""
robot_drive.py - connects the teammate's motor code (src/test_motors.py + src/motor_config.json)
to the weed detector. It follows a predefined route and can PAUSE (stand still) while the
LEDs fire at a weed, then RESUME exactly where it left off.

Nothing in the teammate's files is changed: this file only imports his Drive class, his config
and his route language ("forward 5 35, right 1 45, ...").

Route language (from test_motors.py):  <action> <seconds> [speed%]
   forward / reverse / left / right (spin in place) / stop / brake / coast
   veerleft / veerright <seconds> <speed%> <turn%>   (curve while moving)

Standalone tests (inside ~/maize_weed with the venv active; wheels OFF the ground first):
  python robot_drive.py --dry-run            # no motors move: prints what the pins would do
  python robot_drive.py                      # drive the ROUTE below once
  python robot_drive.py --pause-test         # drive, pause 2 s in the middle, resume (what weed_robot does)
  python robot_drive.py --route "forward 3 30, left 1.2 45, forward 3 30"
Ctrl+C stops the motors.
"""
import argparse, json, os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'src'))
import test_motors as tm   # the teammate's script (its own main() does not run on import)

CONFIG_FILE = os.path.join(HERE, 'src', 'motor_config.json')

# ---------------------------------------------------------------- the route (edit this)
# Slow on purpose: 35 % for driving, 45 % for turning on the spot.
# A 90-degree turn takes about 1.0 s at 45 % (from the config: 700 ms at 65 %) - adjust on the real robot.
ROUTE = "forward 5 35, right 1.0 45, forward 2 35, right 1.0 45, forward 5 35, stop 0.5"


def load_config(path=CONFIG_FILE, max_runtime=None):
    """Teammate's defaults + his motor_config.json, validated by his own checks."""
    cfg = json.loads(json.dumps(tm.DEFAULT_CONFIG))
    if os.path.exists(path):
        with open(path) as f:
            cfg = tm.deep_merge(cfg, json.load(f))
    if max_runtime is not None:
        cfg['safety']['max_runtime_s'] = float(max_runtime)
    for w in tm.validate_config(cfg, allow_reserved=False):
        print(f'[drive] warning: {w}', flush=True)
    return cfg


def make_drive(cfg, dry_run=False):
    if dry_run:
        backend = tm.DryRunBackend(tm.pin_roles(cfg), min_interval=0.5)
    else:
        try:
            backend = tm.LgpioBackend(cfg.get('chip'))
        except tm.MotorError as e:
            print(f'[drive] motors not available ({e}) - using dry-run (no movement)', flush=True)
            backend = tm.DryRunBackend(tm.pin_roles(cfg), min_interval=0.5)
    drive = tm.Drive(cfg, backend, verbose=False)
    drive.start()
    return drive


class _Closer:
    """weed_robot.py calls runner.m.close() at the end."""
    def __init__(self, drive): self.drive = drive
    def close(self):
        try: self.drive.close()
        except Exception: pass


class RouteRunner:
    """Follows the route in a background thread using the teammate's Drive.
    pause() stops the wheels, resume() continues the same step; paused time doesn't count."""
    def __init__(self, route=ROUTE, cfg=None, dry_run=False, loop=False):
        self.cfg = cfg or load_config()
        self.steps = tm.parse_sequence(route, self.cfg)
        self.drive = make_drive(self.cfg, dry_run)
        self.m = _Closer(self.drive)
        self.loop = loop
        self._go = threading.Event(); self._go.set()
        self._quit = threading.Event()
        self.step, self.finished, self.paused = None, False, False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        tm.print_sequence_plan(self.steps, 0 if self.loop else 1)
        self.thread.start()
        return self

    def _apply(self, step):
        if step['action'] in ('brake', 'coast'):
            self.drive.park_now(step['action'])
        elif step['action'] == 'stop':
            self.drive.stop(wait=False)
        else:
            self.drive.steer(*tm.step_targets(step))

    def pause(self):
        if self._go.is_set():
            self._go.clear(); self.paused = True
            self.drive.stop(wait=False)          # ramps down quickly (decel from the config)

    def resume(self):
        if not self._go.is_set():
            self._go.set(); self.paused = False
            if self.step and not self.finished: self._apply(self.step)

    def stop(self):
        self._quit.set(); self._go.set()
        if self.thread.is_alive(): self.thread.join(timeout=2)
        self.drive.stop(wait=False)

    def _run(self):
        try:
            while not self._quit.is_set():
                for i, step in enumerate(self.steps, 1):
                    if self._quit.is_set() or self.drive.expired(): break
                    self.step = step
                    print(f'[route] {i}/{len(self.steps)} {tm.describe_step(step)}', flush=True)
                    self._go.wait()
                    self._apply(step)
                    left = step['seconds']
                    while left > 0 and not self._quit.is_set():
                        if self.drive.expired():
                            print('[route] max_runtime reached (safety.max_runtime_s in motor_config.json)', flush=True); break
                        if not self._go.is_set():           # paused: wheels already stopping
                            self._go.wait()
                            if self._quit.is_set(): break
                            self._apply(step)
                        t = time.monotonic(); time.sleep(min(0.05, left)); left -= time.monotonic() - t
                if not self.loop or self.drive.expired(): break
        finally:
            self.drive.stop(wait=False); self.finished = True
            print('[route] finished', flush=True)


# ---------------------------------------------------------------- standalone use
if __name__ == '__main__':
    ap = argparse.ArgumentParser(description="Drive the route with the teammate's motor code")
    ap.add_argument('--route', default=ROUTE, help='route in the teammate\'s step language')
    ap.add_argument('--dry-run', action='store_true', help='no motors: print pin activity only')
    ap.add_argument('--pause-test', action='store_true', help='pause for 2 s after 2 s, then resume')
    ap.add_argument('--loop', action='store_true', help='repeat the route until Ctrl+C')
    ap.add_argument('--max-runtime', type=float, help='safety stop in seconds (default from motor_config.json)')
    a = ap.parse_args()
    r = RouteRunner(a.route, load_config(max_runtime=a.max_runtime), dry_run=a.dry_run, loop=a.loop).start()
    try:
        if a.pause_test:
            time.sleep(2); print('>>> PAUSE (as if a weed was found)', flush=True); r.pause()
            time.sleep(2); print('>>> RESUME', flush=True); r.resume()
        while not r.finished: time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        r.stop(); r.m.close(); print('motors stopped', flush=True)
