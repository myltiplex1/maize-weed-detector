"""
detector.py - lightweight YOLO (NCNN) maize/weed detector for the web app.

Runs the exported NCNN model directly with the `ncnn` package + NumPy + OpenCV, so the app
does NOT need PyTorch/Ultralytics (which would be far too big for Streamlit Cloud).
Pre/post-processing reproduces Ultralytics' predict(): letterbox to the model size (grey 114
padding), RGB, 0-1 scaling, then per-class NMS (IoU 0.7). Works for YOLO26n and YOLO11n exports.
"""
import glob, json, os
import cv2
import numpy as np
import ncnn
import yaml


class Detector:
    def __init__(self, model_dir, threads=4):
        self.dir = model_dir
        param = (glob.glob(os.path.join(model_dir, '**', '*.param'), recursive=True) or [None])[0]
        if param is None:
            raise FileNotFoundError(f'No NCNN model (*.param) found in {model_dir}')
        self.param, self.bin = param, param[:-6] + '.bin'
        meta_path = os.path.join(os.path.dirname(param), 'metadata.yaml')
        meta = yaml.safe_load(open(meta_path)) if os.path.exists(meta_path) else {}
        self.names = {int(k): v for k, v in (meta.get('names') or {0: 'maize', 1: 'weed'}).items()}
        imgsz = meta.get('imgsz', 416)
        self.imgsz = int(imgsz[0] if isinstance(imgsz, (list, tuple)) else imgsz)
        cfg_path = os.path.join(model_dir, 'robot_config.json')
        self.cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
        self.thresholds = {'maize': float(self.cfg.get('maize_conf', 0.25)), 'weed': float(self.cfg.get('weed_conf', 0.25))}
        self.model_name = str(self.cfg.get('model', meta.get('description', 'YOLO'))).replace('.pt', '').upper()
        self.net = ncnn.Net()
        self.net.opt.num_threads = threads
        self.net.opt.use_vulkan_compute = False
        self.net.load_param(self.param)
        self.net.load_model(self.bin)

    # ------------------------------------------------------------------ helpers
    def _letterbox(self, img):
        h, w = img.shape[:2]
        s = self.imgsz
        r = min(s / h, s / w)
        nw, nh = int(round(w * r)), int(round(h * r))
        dw, dh = (s - nw) / 2, (s - nh) / 2
        if (w, h) != (nw, nh):
            img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
        return img, r, (left, top)

    def predict(self, bgr, conf=None, iou=0.7, max_det=300):
        """bgr: HxWx3 uint8 (OpenCV order). Returns list of dicts: cls, name, conf, box=[x1,y1,x2,y2] (pixels)."""
        thr = conf if conf is not None else self.thresholds
        min_thr = min(thr.values())
        lb, r, (px, py) = self._letterbox(bgr)
        x = np.ascontiguousarray(lb[:, :, ::-1].transpose(2, 0, 1), dtype=np.float32) / 255.0
        x = np.ascontiguousarray(x)
        mat = ncnn.Mat(x).clone()
        ex = self.net.create_extractor()
        ex.input('in0', mat)
        _, out = ex.extract('out0')
        out = np.array(out)
        del ex
        nc = len(self.names)
        if out.ndim == 2 and out.shape[0] == 4 + nc:            # (4+nc, N): cx,cy,w,h + class scores -> NMS needed
            p = out.T
            scores = p[:, 4:4 + nc]
            cls = scores.argmax(1); cf = scores[np.arange(len(p)), cls]
            keep = cf >= min_thr
            p, cls, cf = p[keep], cls[keep], cf[keep]
            xyxy = np.stack([p[:, 0] - p[:, 2] / 2, p[:, 1] - p[:, 3] / 2, p[:, 0] + p[:, 2] / 2, p[:, 1] + p[:, 3] / 2], 1)
            dets = []
            for c in np.unique(cls):
                m = cls == c
                b, s = xyxy[m], cf[m]
                idx = cv2.dnn.NMSBoxes(np.column_stack([b[:, :2], b[:, 2:] - b[:, :2]]).tolist(), s.tolist(), 0.0, iou)
                for i in np.array(idx).reshape(-1):
                    dets.append((b[i], float(s[i]), int(c)))
        else:                                                   # end-to-end export: (N, 6) x1,y1,x2,y2,conf,cls
            p = out.reshape(-1, 6)
            dets = [(row[:4], float(row[4]), int(row[5])) for row in p if row[4] >= min_thr]
        res = []
        h, w = bgr.shape[:2]
        for b, s, c in sorted(dets, key=lambda d: -d[1])[:max_det]:
            name = self.names.get(c, str(c))
            if s < thr.get(name, min_thr):
                continue
            x1 = float(np.clip((b[0] - px) / r, 0, w)); y1 = float(np.clip((b[1] - py) / r, 0, h))
            x2 = float(np.clip((b[2] - px) / r, 0, w)); y2 = float(np.clip((b[3] - py) / r, 0, h))
            res.append({'cls': c, 'name': name, 'conf': s, 'box': [x1, y1, x2, y2]})
        return res
