#!/usr/bin/env python3
"""
weed_robot.py - maize/weed robot controller for Raspberry Pi 4 (YOLO NCNN model)

Pipeline per frame:
  camera / video / photo folder -> YOLO (NCNN) -> per-class thresholds
  -> size + working-area filters -> maize protection zones (maize always wins)
  -> weed tracking (must be seen in N frames in a row) -> FIRE command (laser target)

For now FIRE lights the indicator LEDs together (default: both LEDs on GPIO24) and prints/logs the weed position
and its grid cell. Replace Actuator.fire() when the laser mechanism is ready.

Examples (run inside ~/maize_weed with the venv active):
  python weed_robot.py                                  # live camera, browser view on :8000
  python weed_robot.py --source test_photos/            # folder of photos (no camera needed)
  python weed_robot.py --source farm.mp4 --no-view      # video file
  python weed_robot.py --roi 0.1,0.3,0.9,1.0            # only act in this part of the frame
  python weed_robot.py --maize-conf 0.25 --weed-conf 0.35   # try other thresholds (config file unchanged)
  python weed_robot.py --persist 5 --merge-overlap 0.4  # weed must be seen 5 frames; merge overlapping boxes more
  python weed_robot.py --drive                          # also drive the route (teammate's motor code)
  python weed_robot.py --drive --motors-dry-run         # same, but the wheels don't move (desk test)
  python weed_robot.py --record 5                       # also save a raw frame every 5 s (training data)
Stop with Ctrl+C.
"""
import argparse, csv, glob, json, os, subprocess, threading, time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
from ultralytics import YOLO

# ----------------------------------------------------------------- settings
p = argparse.ArgumentParser(description='Maize/weed robot controller')
p.add_argument('--model-dir', default='maize_weed_yolo26n_ncnn_416', help='folder with maize_weed_ncnn_model/ + robot_config.json')
p.add_argument('--source', default='cam', help="'cam' (Pi camera), a video file, or a folder of photos")
p.add_argument('--maize-conf', type=float, help='override maize threshold from robot_config.json')
p.add_argument('--weed-conf', type=float, help='override weed threshold from robot_config.json')
p.add_argument('--roi', default='0,0,1,1', help='working area x1,y1,x2,y2 as fractions of the frame (0-1)')
p.add_argument('--protect-margin', type=float, default=0.15, help='enlarge each maize box by this fraction on every side')
p.add_argument('--min-area', type=float, default=0.0005, help='ignore boxes smaller than this fraction of the frame')
p.add_argument('--max-area', type=float, default=0.5, help='ignore boxes larger than this fraction of the frame')
p.add_argument('--persist', type=int, default=5, help='frames in a row a weed must be seen before uprooting')
p.add_argument('--merge-overlap', type=float, default=0.5, help='merge same-class boxes whose overlap (IoU, or share of the smaller box inside the bigger) is above this')
p.add_argument('--match-dist', type=float, default=0.08, help='max centre movement between frames (fraction of frame width) to count as the same weed')
p.add_argument('--size', default='640x480', help='camera capture size')
p.add_argument('--no-view', action='store_true', help='disable the browser live view')
p.add_argument('--port', type=int, default=8000)
p.add_argument('--record', type=float, default=0, help='save a raw frame every N seconds to ./recordings (0 = off)')
p.add_argument('--grid', default='1x1', help='split the working area into ROWSxCOLS cells for the target mechanism')
p.add_argument('--led-pins', default='24', help='GPIO (BCM) numbers of the indicator LEDs, comma-separated; they all light together. "none" = no LEDs')
p.add_argument('--led-time', type=float, default=1.0, help='seconds the LED stays on per weed')
p.add_argument('--drive', action='store_true', help="also drive the route with the motors; the robot stands still while a weed is confirmed and fired at")
p.add_argument('--motors', choices=['teammate', 'mine'], default='teammate', help="teammate = src/test_motors.py via robot_drive.py (default); mine = backup motors.py")
p.add_argument('--route', help="route for --drive in the teammate's step language, e.g. \"forward 5 35, right 1 45, forward 5 35\" (default: ROUTE in robot_drive.py)")
p.add_argument('--motors-dry-run', action='store_true', help='with --drive: do not move the motors, only print what they would do')
p.add_argument('--confirm-wait', type=float, default=1.5, help='with --drive: max seconds to stand still waiting for a weed in the zone to be confirmed')
p.add_argument('--ruler', action='store_true', help='show a 0-1 ruler on the live view edges (for reading --roi numbers by hand)')
p.add_argument('--loop', action='store_true', help='repeat a photo folder / video forever (for demos)')
args = p.parse_args()

cfg = json.load(open(os.path.join(args.model_dir, 'robot_config.json')))
PHOTOS = os.path.isdir(args.source)
if PHOTOS: args.persist = 1   # photos are unrelated to each other -> judge each photo on its own
THR = {'maize': args.maize_conf if args.maize_conf is not None else cfg['maize_conf'],
       'weed': args.weed_conf if args.weed_conf is not None else cfg['weed_conf']}
IMGSZ = cfg['imgsz']
ROI = [float(v) for v in args.roi.split(',')]
W, H = [int(v) for v in args.size.lower().split('x')]
COL = {'maize': (83, 200, 0), 'weed': (214, 64, 255), 'pending': (0, 200, 255), 'zone': (83, 200, 0), 'roi': (255, 255, 255)}  # BGR
os.makedirs('logs', exist_ok=True)
STAMP = datetime.now().strftime('%Y%m%d_%H%M%S')


# ----------------------------------------------------------------- actuator (PLACEHOLDER)
class Actuator:
    """Target output. For now: an LED on a GPIO pin lights up for each confirmed weed (stand-in for the laser).
    x, y = weed centre as fractions of the WORKING AREA (0,0 top-left of ROI, 1,1 bottom-right).
    cell = (row, col) of that point in a --grid of the working area, numbered from 0 at top-left.
    Later: send the cell (or x, y) to the laser mechanism, e.g. over USB to an Arduino:
        import serial; self.ser = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
        self.ser.write(f'FIRE {row} {col}\n'.encode())"""
    def __init__(self, led_pins, on_time):
        self.count, self.on_time, self.led = 0, on_time, None
        pins = [] if led_pins.lower() == 'none' else [int(v) for v in led_pins.split(',') if v.strip()]
        if pins:
            try:
                from gpiozero import LEDBoard
                self.led = LEDBoard(*pins)          # all LEDs switch together
                print(f'LED indicators on GPIO {", ".join(map(str, pins))}', flush=True)
            except Exception as e:
                print(f'(LEDs on GPIO {pins} not available: {e}) - printing only', flush=True)

    def fire(self, x, y, cell, conf, track_id):
        self.count += 1
        where = f' -> cell row {cell[0]}, col {cell[1]}' if cell is not None else ''
        print(f'>>> FIRE #{self.count}: weed {track_id} at x={x:.2f}, y={y:.2f}{where} (conf {conf:.2f})', flush=True)
        if self.led:   # non-blocking: LED turns itself off after on_time seconds
            self.led.blink(on_time=self.on_time, off_time=0, n=1, background=True)

    def close(self):
        if self.led: self.led.off(); self.led.close()


# ----------------------------------------------------------------- frame sources
def frames():
    if args.source == 'cam':
        from picamera2 import Picamera2
        cam = Picamera2()
        cam.configure(cam.create_preview_configuration(main={'size': (W, H), 'format': 'RGB888'}))  # RGB888 = BGR array
        cam.start(); time.sleep(2)
        try:
            while True:
                yield cam.capture_array(), 'cam'
        finally:
            cam.stop()
    elif os.path.isdir(args.source):
        files = sorted(f for ext in ('jpg', 'jpeg', 'png', 'JPG', 'JPEG', 'PNG') for f in glob.glob(os.path.join(args.source, f'*.{ext}')))
        if not files: raise SystemExit(f'No photos found in {args.source}')
        while True:
            for f in files:
                img = cv2.imread(f)
                if img is not None:
                    yield img, os.path.basename(f)
                    if not args.no_view: time.sleep(0.5)   # slow down so you can watch
            if not args.loop: break
    else:
        cap = cv2.VideoCapture(args.source)
        if not cap.isOpened(): raise SystemExit(f'Cannot open {args.source}')
        while True:
            ok, img = cap.read()
            if not ok:
                if args.loop: cap.set(cv2.CAP_PROP_POS_FRAMES, 0); continue
                break
            yield img, args.source


# ----------------------------------------------------------------- helpers
def inside(cx, cy, box):
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]

def expand(b, m, w, h):
    bw, bh = b[2] - b[0], b[3] - b[1]
    return [max(0, b[0] - m * bw), max(0, b[1] - m * bh), min(w, b[2] + m * bw), min(h, b[3] + m * bh)]

def overlaps(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])

def merge_boxes(dets, thr):
    """Keep the most confident box; drop same-class boxes that overlap it too much
    (IoU > thr, or more than thr of the smaller box lies inside the other - e.g. small boxes inside a weed patch)."""
    keep = []
    for b, c in sorted(dets, key=lambda d: -d[1]):
        ok = True
        for k, _ in keep:
            iw = max(0, min(b[2], k[2]) - max(b[0], k[0])); ih = max(0, min(b[3], k[3]) - max(b[1], k[1]))
            inter = iw * ih
            if inter == 0: continue
            a1 = (b[2] - b[0]) * (b[3] - b[1]); a2 = (k[2] - k[0]) * (k[3] - k[1])
            if inter / (a1 + a2 - inter) > thr or inter / min(a1, a2) > max(thr, 0.7):
                ok = False; break
        if ok: keep.append((b, c))
    return keep

def text(img, s, xy, scale, col):
    th = 1 if scale < 0.7 else 2
    cv2.putText(img, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), th + 2, cv2.LINE_AA)   # dark outline
    cv2.putText(img, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)

def pi_status():
    try:
        t = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True, text=True).stdout.strip().split('=')[1]
        th = subprocess.run(['vcgencmd', 'get_throttled'], capture_output=True, text=True).stdout.strip().split('=')[1]
        return t, th
    except Exception:
        return '?', '?'


# ----------------------------------------------------------------- weed tracker
class Tracker:
    """A weed must be matched in `persist` consecutive frames before it is acted on.
    Flickering false detections never reach that count."""
    def __init__(self, persist, match_px):
        self.persist, self.match_px, self.tracks, self.next_id = persist, match_px, [], 1

    def update(self, dets):   # dets: list of (cx, cy, conf, box)
        for t in self.tracks: t['seen'] = False
        for cx, cy, conf, box in sorted(dets, key=lambda d: -d[2]):
            best, bd = None, self.match_px
            for t in self.tracks:
                if t['seen']: continue
                d = np.hypot(cx - t['cx'], cy - t['cy'])
                if d < bd: best, bd = t, d
            if best is None:
                best = {'id': self.next_id, 'hits': 0, 'done': False}; self.next_id += 1; self.tracks.append(best)
            best.update(cx=cx, cy=cy, conf=conf, box=box, seen=True); best['hits'] += 1
        # a weed not seen this frame loses its streak (must be seen N frames IN A ROW)
        self.tracks = [t for t in self.tracks if t['seen']]
        return self.tracks


# ----------------------------------------------------------------- live view server
latest, lock = None, threading.Lock()
class View(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/': self.send_error(404); return
        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame'); self.end_headers()
        try:
            while True:
                with lock: jpg = latest
                if jpg:
                    self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' + str(len(jpg)).encode() + b'\r\n\r\n' + jpg + b'\r\n')
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError):
            pass
    def log_message(self, *a): pass


# ----------------------------------------------------------------- main loop
def main():
    global latest
    model = YOLO(os.path.join(args.model_dir, 'maize_weed_ncnn_model'), task='detect')
    act = Actuator(args.led_pins, args.led_time)
    runner = None
    if args.drive:
        if args.motors == 'teammate':
            import robot_drive
            runner = robot_drive.RouteRunner(args.route or robot_drive.ROUTE, dry_run=args.motors_dry_run).start()
            print("Driving the route with the teammate's motor code. Ctrl+C stops everything.", flush=True)
        else:
            from motors import Motors, RouteRunner
            runner = RouteRunner(Motors()).start()
            print('Driving the route with the backup motors.py. Ctrl+C stops everything.', flush=True)
    hold_until, pend_since = 0.0, None
    GR, GC = [int(v) for v in args.grid.lower().split('x')]
    tracker = None
    log = open(f'logs/actions_{STAMP}.csv', 'w', newline=''); lw = csv.writer(log)
    lw.writerow(['time', 'frame', 'source', 'track_id', 'x_roi', 'y_roi', 'cell_row', 'cell_col', 'conf', 'maize_in_view', 'weeds_in_view'])
    if not args.no_view:
        threading.Thread(target=ThreadingHTTPServer(('0.0.0.0', args.port), View).serve_forever, daemon=True).start()
        print(f'Live view: open http://<PI_IP>:{args.port} in your laptop browser', flush=True)
    if args.record: os.makedirs('recordings', exist_ok=True)
    print(f'Model {args.model_dir} | imgsz {IMGSZ} | maize_conf {THR["maize"]:.3f} | weed_conf {THR["weed"]:.3f} | '
          f'persist {args.persist} | ROI {ROI} | source {args.source}', flush=True)
    recent = []   # (cx, cy, time) of recent uproots: don't fire twice at the same weed
    n, last_rec, last_stat, temp, thr_flag, fps_t, fps = 0, 0, 0, '?', '?', time.time(), 0.0
    try:
        for frame, name in frames():
            n += 1
            h, w = frame.shape[:2]
            if tracker is None or PHOTOS: tracker = Tracker(args.persist, args.match_dist * w)
            now = time.time()
            if args.record and now - last_rec >= args.record:
                cv2.imwrite(f'recordings/{STAMP}_{n:06d}.jpg', frame); last_rec = now
            roi = [ROI[0] * w, ROI[1] * h, ROI[2] * w, ROI[3] * h]

            t0 = time.perf_counter()
            r = model.predict(frame, imgsz=IMGSZ, conf=min(THR.values()), verbose=False)[0]
            ms = (time.perf_counter() - t0) * 1000

            maize, weeds = [], []
            for b, c, conf in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
                cls = r.names[int(c)]
                if conf < THR[cls]: continue
                area = (b[2] - b[0]) * (b[3] - b[1]) / (w * h)
                if not (args.min_area <= area <= args.max_area): continue
                (maize if cls == 'maize' else weeds).append((b, conf))
            maize, weeds = merge_boxes(maize, args.merge_overlap), merge_boxes(weeds, args.merge_overlap)   # one box per plant
            zones = [expand(b, args.protect_margin, w, h) for b, _ in maize]
            cand = []
            for b, conf in weeds:
                cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                if not inside(cx, cy, roi): continue                       # outside working area
                if any(overlaps(b, z) for z in zones): continue            # maize wins: never act near maize
                cand.append((cx, cy, conf, b))
            ded = []   # merge duplicate boxes on the same weed (keep the most confident)
            for c in sorted(cand, key=lambda d: -d[2]):
                if all(np.hypot(c[0] - k[0], c[1] - k[1]) >= tracker.match_px / 2 for k in ded): ded.append(c)
            tracks = tracker.update(ded)
            recent = [q for q in recent if now - q[2] < 5]
            for t in tracks:
                if not t['done'] and any(np.hypot(t['cx'] - rx, t['cy'] - ry) < tracker.match_px and now - rt < 5 for rx, ry, rt in recent):
                    t['done'] = True   # same spot was targeted < 5 s ago
                if t['hits'] >= args.persist and not t['done']:
                    x = (t['cx'] - roi[0]) / max(roi[2] - roi[0], 1); y = (t['cy'] - roi[1]) / max(roi[3] - roi[1], 1)
                    cell = (min(int(y * GR), GR - 1), min(int(x * GC), GC - 1))
                    if runner: runner.pause()             # stand still while firing
                    act.fire(x, y, cell if GR * GC > 1 else None, t['conf'], t['id']); t['done'] = True; recent.append((t['cx'], t['cy'], now))
                    hold_until = now + args.led_time + 0.3
                    lw.writerow([datetime.now().isoformat(timespec='seconds'), n, name, t['id'], f'{x:.3f}', f'{y:.3f}', cell[0], cell[1], f'{t["conf"]:.3f}', len(maize), len(weeds)]); log.flush()

            if runner:
                # stop while a weed in the fire zone is still being confirmed (max confirm-wait s), and while firing
                pending = any(not t['done'] and t['hits'] < args.persist for t in tracks)
                pend_since = (pend_since or now) if pending else None
                if now < hold_until or (pending and now - pend_since < args.confirm_wait): runner.pause()
                else: runner.resume()
                if runner.finished:
                    print('Route finished.', flush=True); break

            if now - last_stat > 10:
                temp, thr_flag = pi_status(); last_stat = now
                try: now_bits = int(thr_flag, 16) & 0xF          # bits 0-3 = happening NOW (16-19 = happened since boot)
                except ValueError: now_bits = 0
                if now_bits & 0x1: print(f'WARNING: under-voltage NOW ({thr_flag}) - use the official 5V 3A power supply', flush=True)
                if now_bits & 0xE: print(f'WARNING: Pi is slowing itself down NOW ({thr_flag}, {temp}) - add cooling', flush=True)
            fps = 0.8 * fps + 0.2 * (1 / max(now - fps_t, 1e-6)) if n > 1 else 0; fps_t = now

            if not args.no_view:
                v = frame.copy()
                for f in ((0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9) if args.ruler else ()):   # optional ruler for reading --roi numbers
                    cv2.line(v, (int(f * w), h - 12), (int(f * w), h), (255, 255, 255), 1); text(v, f'{f:.1f}', (int(f * w) - 12, h - 16), 0.4, (255, 255, 255))
                    cv2.line(v, (w - 12, int(f * h)), (w, int(f * h)), (255, 255, 255), 1); text(v, f'{f:.1f}', (w - 42, int(f * h) + 5), 0.4, (255, 255, 255))
                if ROI != [0.0, 0.0, 1.0, 1.0]:   # only draw the fire zone when one is set
                    cv2.rectangle(v, (int(roi[0]), int(roi[1])), (int(roi[2]), int(roi[3])), COL['roi'], 1)
                for i in range(1, GC): xg = int(roi[0] + i * (roi[2] - roi[0]) / GC); cv2.line(v, (xg, int(roi[1])), (xg, int(roi[3])), (150, 150, 150), 1)
                for i in range(1, GR): yg = int(roi[1] + i * (roi[3] - roi[1]) / GR); cv2.line(v, (int(roi[0]), yg), (int(roi[2]), yg), (150, 150, 150), 1)
                for z in zones: cv2.rectangle(v, (int(z[0]), int(z[1])), (int(z[2]), int(z[3])), COL['zone'], 1)
                for b, conf in maize:
                    cv2.rectangle(v, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), COL['maize'], 3)
                    text(v, f'maize {conf:.2f}', (int(b[0]), max(int(b[1]) - 6, 20)), 0.6, COL['maize'])
                for b, conf in weeds:   # all weeds above threshold (thin = ignored: protected / outside area)
                    cv2.rectangle(v, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), COL['weed'], 1)
                for t in tracks:
                    b = t['box']; col = COL['weed'] if t['hits'] >= args.persist else COL['pending']
                    cv2.rectangle(v, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), col, 3)
                    label = f'weed {t["conf"]:.2f} ' + ('FIRE' if t['done'] else f'{t["hits"]}/{args.persist}')
                    text(v, label, (int(b[0]), max(int(b[1]) - 6, 20)), 0.6, col)
                text(v, f'{ms:.0f} ms  {fps:.1f} fps | maize {len(maize)} | weed {len(weeds)} | fired {act.count} | {temp}', (10, 28), 0.7, (255, 255, 255))
                ok, jpg = cv2.imencode('.jpg', v, [cv2.IMWRITE_JPEG_QUALITY, 70])
                with lock: latest = jpg.tobytes()
            elif n % 20 == 0:
                print(f'frame {n}: {ms:.0f} ms | maize {len(maize)} | weed {len(weeds)} | fired {act.count} | {temp}', flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        if runner: runner.stop(); runner.m.close()
        act.close(); log.close()
        print(f'Stopped after {n} frames, {act.count} fire commands. Log: logs/actions_{STAMP}.csv', flush=True)


if __name__ == '__main__':
    main()
