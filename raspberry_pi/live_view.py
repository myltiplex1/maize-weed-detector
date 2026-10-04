import json, time, threading, cv2
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from picamera2 import Picamera2
from ultralytics import YOLO
d = 'maize_weed_yolo26n_ncnn_416'
cfg = json.load(open(f'{d}/robot_config.json'))
thr = {'maize': cfg['maize_conf'], 'weed': cfg['weed_conf']}
COL = {'maize': (83, 200, 0), 'weed': (214, 64, 255)}   # BGR: maize green, weed magenta
m = YOLO(f'{d}/maize_weed_ncnn_model', task='detect')
cam = Picamera2()
cam.configure(cam.create_preview_configuration(main={'size': (1296, 972), 'format': 'RGB888'}))
cam.start(); time.sleep(2)
latest, lock = None, threading.Lock()
def text(img, s, xy, scale, col):
    cv2.putText(img, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 5)
    cv2.putText(img, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, col, 2)
def loop():
    global latest
    while True:
        f = cam.capture_array()
        t = time.perf_counter()
        r = m.predict(f, imgsz=cfg['imgsz'], conf=min(thr.values()), verbose=False)[0]
        ms = (time.perf_counter() - t) * 1000
        n = {'maize': 0, 'weed': 0}
        for b, c, p in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
            name = r.names[int(c)]
            if p < thr[name]: continue
            n[name] += 1
            x1, y1, x2, y2 = map(int, b)
            cv2.rectangle(f, (x1, y1), (x2, y2), COL[name], 3)
            text(f, f'{name} {p:.2f}', (x1, max(y1 - 8, 25)), 0.8, COL[name])
        text(f, f'{ms:.0f} ms | maize {n["maize"]} | weed {n["weed"]}', (15, 45), 1.1, (255, 255, 255))
        ok, jpg = cv2.imencode('.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, 70])
        with lock: latest = jpg.tobytes()
threading.Thread(target=loop, daemon=True).start()
class H(BaseHTTPRequestHandler):
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
print('Live view running: open http://<PI_IP>:8000 in your laptop browser (e.g. http://10.67.116.127:8000). Ctrl+C to stop.', flush=True)
try:
    ThreadingHTTPServer(('0.0.0.0', 8000), H).serve_forever()
except KeyboardInterrupt:
    cam.stop()
