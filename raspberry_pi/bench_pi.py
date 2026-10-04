"""bench_pi.py - on-device speed benchmark of every NCNN model folder in the current directory.
Run on the Pi inside ~/maize_weed:  python bench_pi.py   -> prints results and saves pi_benchmark.csv"""
import glob, json, time, csv, subprocess, numpy as np
from ultralytics import YOLO
img = (np.random.rand(480, 640, 3) * 255).astype('uint8')
rows = []
for d in sorted(glob.glob('maize_weed_*ncnn_*/')):
    cfg = json.load(open(d + 'robot_config.json'))
    m = YOLO(d + 'maize_weed_ncnn_model', task='detect')
    for _ in range(5): m.predict(img, imgsz=cfg['imgsz'], verbose=False)
    t = []
    for _ in range(30):
        s = time.perf_counter(); m.predict(img, imgsz=cfg['imgsz'], verbose=False)
        t.append((time.perf_counter() - s) * 1000)
    temp = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True, text=True).stdout.strip()
    thr = subprocess.run(['vcgencmd', 'get_throttled'], capture_output=True, text=True).stdout.strip()
    med = float(np.median(t))
    r = dict(model=cfg.get('model', 'yolo26n' if 'yolo26n' in d else 'yolo11n').replace('.pt', ''), imgsz=cfg['imgsz'],
             median_ms=round(med, 1), fps=round(1000 / med, 1), temp=temp, throttled=thr)
    print(r, flush=True); rows.append(r)
    time.sleep(20)   # cool down between models
with open('pi_benchmark.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
print('saved pi_benchmark.csv')
