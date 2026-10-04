"""
Maize & Weed Detector - Streamlit web app for the ML part of the weeding robot.

Upload a photo, take one with your camera, or upload a video: the YOLO model (NCNN export)
finds maize and weeds, draws the boxes, and shows what the robot would do
(protect maize, target weeds that are not next to maize).

Run locally:   streamlit run app.py
"""
import glob, io, os, tempfile, time

import cv2
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image, ImageOps

from detector import Detector

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(APP_DIR, 'models')
SAMPLES_DIR = os.path.join(APP_DIR, 'samples')

# Colours: boxes (BGR for OpenCV) and UI (hex)
BOX = {'maize': (83, 200, 0), 'weed': (214, 64, 255)}
UI = {'maize': '#00a854', 'weed': '#d63aff', 'ink': '#18261c', 'muted': '#5d6b61'}

st.set_page_config(page_title='Maize & Weed Detector', page_icon='🌽', layout='wide', initial_sidebar_state='auto')

# ------------------------------------------------------------------ styling
st.markdown(f"""
<style>
  .block-container {{ padding-top: 3.2rem; padding-bottom: 2rem; max-width: 1280px; }}
  .hero {{ background: linear-gradient(120deg, #0f3d22 0%, #1d6b3a 55%, #3f8f3a 100%);
          border-radius: 18px; padding: 22px 28px; color: #fff; margin-bottom: 18px;
          box-shadow: 0 6px 24px rgba(15,61,34,.18); }}
  .hero h1 {{ font-size: 1.9rem; margin: 0 0 4px 0; color: #fff; letter-spacing: -.3px; }}
  .hero p {{ margin: 0; opacity: .88; font-size: 1.0rem; }}
  .chip {{ display: inline-flex; align-items: center; gap: 6px; background: rgba(255,255,255,.14);
          border: 1px solid rgba(255,255,255,.25); border-radius: 999px; padding: 3px 11px;
          font-size: .82rem; margin: 10px 6px 0 0; color: #fff; }}
  .dot {{ width: 10px; height: 10px; border-radius: 3px; display: inline-block; }}
  .card {{ background: #fff; border: 1px solid #e3e8e1; border-radius: 14px; padding: 14px 16px;
          box-shadow: 0 1px 3px rgba(0,0,0,.04); min-height: 104px; margin-bottom: 10px; }}
  .card .lbl {{ font-size: .78rem; text-transform: uppercase; letter-spacing: .6px; color: {UI['muted']}; }}
  .card .val {{ font-size: 1.9rem; font-weight: 700; color: {UI['ink']}; line-height: 1.15; }}
  .card .sub {{ font-size: .8rem; color: {UI['muted']}; }}
  .decision {{ border-radius: 12px; padding: 12px 16px; margin: 12px 0 6px 0; font-weight: 600; }}
  .decision.go {{ background: #fbeaff; border: 1px solid #efc2fb; color: #6d1688; }}
  .decision.ok {{ background: #e7f6ec; border: 1px solid #bfe5cb; color: #135c2d; }}
  .decision.none {{ background: #f2f4f1; border: 1px solid #e0e5de; color: #46524a; }}
  .section-title {{ font-weight: 700; font-size: 1.05rem; color: {UI['ink']}; margin: 4px 0 8px 0; }}
  div[data-testid="stTabs"] button p {{ font-size: 1.0rem; font-weight: 600; }}
  .foot {{ color: {UI['muted']}; font-size: .8rem; margin-top: 26px; text-align: center; }}
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------ model
def find_models():
    found = []
    for cfg in sorted(glob.glob(os.path.join(MODELS_DIR, '*', 'robot_config.json'))):
        found.append(os.path.dirname(cfg))
    for p in sorted(glob.glob(os.path.join(MODELS_DIR, '*', '**', '*.param'), recursive=True)):
        top = os.path.join(MODELS_DIR, os.path.relpath(p, MODELS_DIR).split(os.sep)[0])
        if top not in found: found.append(top)
    return found


@st.cache_resource(show_spinner='Loading model...')
def load_detector(path):
    return Detector(path)


def label_for(path):
    import re
    name = os.path.basename(path).lower()
    size = (re.findall(r'(\d{3})', name) or [''])[-1]
    model = 'YOLO26n' if 'yolo26' in name else ('YOLO11n' if 'ncnn' in name else name)
    return f'{model} · {size} px' if size else model


models = find_models()
if not models:
    st.markdown('<div class="hero"><h1>🌽 Maize & Weed Detector</h1><p>No model found yet.</p></div>', unsafe_allow_html=True)
    st.error('Put your exported model folder (e.g. `maize_weed_yolo26n_ncnn_416`) inside the `models/` folder, then reload. See README.md.')
    st.stop()

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown('### ⚙️ Settings')
    default = next((i for i, m in enumerate(models) if 'yolo26n' in m and '416' in m), 0)
    model_path = st.selectbox('Model', models, index=default, format_func=label_for)
    det = load_detector(model_path)
    st.caption(f'Input size **{det.imgsz} px** · classes: {", ".join(det.names.values())}')

    st.markdown('**Confidence thresholds**')
    maize_thr = st.slider('Maize', 0.05, 0.95, float(round(det.thresholds['maize'], 2)), 0.01,
                          help='Lower = protect more maize (more boxes). Default chosen on the Nigerian validation set.')
    weed_thr = st.slider('Weed', 0.05, 0.95, float(round(det.thresholds['weed'], 2)), 0.01,
                         help='Lower = find more weeds, but more false alarms.')
    st.markdown('**Robot logic**')
    protect = st.slider('Maize safety margin', 0.0, 0.5, 0.15, 0.05,
                        help='Each maize box is enlarged by this fraction; weeds touching it are never targeted.')
    show_conf = st.toggle('Show confidence on boxes', True)
    show_zones = st.toggle('Show maize safety zones', True)
    st.divider()
    st.caption(f'Defaults from the model: maize {det.thresholds["maize"]:.3f} · weed {det.thresholds["weed"]:.3f}')

THR = {'maize': maize_thr, 'weed': weed_thr}


# ------------------------------------------------------------------ core
def analyse(dets, w, h, protect):
    maize = [d for d in dets if d['name'] == 'maize']
    weeds = [d for d in dets if d['name'] == 'weed']
    zones = []
    for d in maize:
        x1, y1, x2, y2 = d['box']; bw, bh = x2 - x1, y2 - y1
        zones.append([max(0, x1 - protect * bw), max(0, y1 - protect * bh), min(w, x2 + protect * bw), min(h, y2 + protect * bh)])
    for d in weeds:
        b = d['box']
        d['protected'] = any(not (b[2] < z[0] or z[2] < b[0] or b[3] < z[1] or z[3] < b[1]) for z in zones)
    return maize, weeds, zones


def draw(bgr, maize, weeds, zones, show_conf=True, show_zones=True):
    img = bgr.copy()
    h, w = img.shape[:2]
    t = max(2, int(round(min(h, w) / 280)))
    fs = max(0.45, min(h, w) / 900)
    def label(text, x, y, col):
        (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, max(1, t - 1))
        y0 = max(int(y), th + base + 4)
        cv2.rectangle(img, (int(x), y0 - th - base - 4), (int(x) + tw + 8, y0), col, -1)
        cv2.putText(img, text, (int(x) + 4, y0 - base - 2), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), max(1, t - 1), cv2.LINE_AA)
    if show_zones:
        overlay = img.copy()
        for z in zones:
            cv2.rectangle(overlay, (int(z[0]), int(z[1])), (int(z[2]), int(z[3])), BOX['maize'], -1)
        img = cv2.addWeighted(overlay, 0.12, img, 0.88, 0)
    for d in maize:
        x1, y1, x2, y2 = map(int, d['box'])
        cv2.rectangle(img, (x1, y1), (x2, y2), BOX['maize'], t)
        label(f"maize {d['conf']:.2f}" if show_conf else 'maize', x1, y1, BOX['maize'])
    for d in weeds:
        x1, y1, x2, y2 = map(int, d['box'])
        if d['protected']:
            cv2.rectangle(img, (x1, y1), (x2, y2), (160, 160, 160), max(1, t - 1))
            label('weed (near maize)', x1, y1, (120, 120, 120))
        else:
            cv2.rectangle(img, (x1, y1), (x2, y2), BOX['weed'], t)
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            r = max(6, min(x2 - x1, y2 - y1) // 5)
            cv2.circle(img, (cx, cy), r, (255, 255, 255), max(1, t - 1), cv2.LINE_AA)
            cv2.line(img, (cx - r - 4, cy), (cx + r + 4, cy), (255, 255, 255), 1, cv2.LINE_AA)
            cv2.line(img, (cx, cy - r - 4), (cx, cy + r + 4), (255, 255, 255), 1, cv2.LINE_AA)
            label(f"weed {d['conf']:.2f}" if show_conf else 'weed', x1, y1, BOX['weed'])
    return img


def run(bgr):
    t0 = time.perf_counter()
    dets = det.predict(bgr, conf=THR)
    ms = (time.perf_counter() - t0) * 1000
    h, w = bgr.shape[:2]
    maize, weeds, zones = analyse(dets, w, h, protect)
    return draw(bgr, maize, weeds, zones, show_conf, show_zones), maize, weeds, ms


def card(col, label, value, sub=''):
    col.markdown(f'<div class="card"><div class="lbl">{label}</div><div class="val">{value}</div><div class="sub">{sub}</div></div>', unsafe_allow_html=True)


def to_bgr(file_or_bytes):
    img = Image.open(file_or_bytes)
    img = ImageOps.exif_transpose(img).convert('RGB')      # phone photos: respect rotation
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def show_image_result(bgr, name='image'):
    annotated, maize, weeds, ms = run(bgr)
    targets = [d for d in weeds if not d['protected']]
    left, right = st.columns([1.65, 1], gap='large')
    with left:
        view = st.radio('View', ['Detections', 'Original', 'Side by side'], horizontal=True, label_visibility='collapsed', key=f'view_{name}')
        if view == 'Detections':
            st.image(cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB), width='stretch')
        elif view == 'Original':
            st.image(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), width='stretch')
        else:
            a, b = st.columns(2)
            a.image(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), caption='Original', width='stretch')
            b.image(cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB), caption='Detections', width='stretch')
    with right:
        st.markdown('<div class="section-title">Prediction</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        card(c1, '🌽 Maize', len(maize), 'protected')
        card(c2, '🌿 Weeds', len(weeds), f'{len(targets)} to remove')
        c3, c4 = st.columns(2)
        avg = np.mean([d['conf'] for d in maize + weeds]) if maize or weeds else 0
        card(c3, 'Avg confidence', f'{avg:.2f}' if maize or weeds else '–')
        card(c4, 'Inference', f'{ms:.0f} ms', f'{det.imgsz}px NCNN')
        if targets:
            st.markdown(f'<div class="decision go">🎯 Robot action: remove {len(targets)} weed{"s" if len(targets) != 1 else ""}'
                        f'{f" · {len(weeds) - len(targets)} skipped (next to maize)" if len(weeds) > len(targets) else ""}</div>', unsafe_allow_html=True)
        elif maize:
            st.markdown('<div class="decision ok">✅ Only maize here - nothing to remove</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="decision none">No maize or weeds detected at these thresholds</div>', unsafe_allow_html=True)
        rows = [{'Class': d['name'], 'Confidence': round(d['conf'], 3),
                 'Action': 'protect' if d['name'] == 'maize' else ('skip (near maize)' if d['protected'] else 'remove'),
                 'Box (x1, y1, x2, y2)': ', '.join(f'{v:.0f}' for v in d['box'])} for d in maize + weeds]
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch', height=min(38 * (len(rows) + 1) + 3, 320))
        ok, png = cv2.imencode('.png', annotated)
        st.download_button('⬇️ Download annotated image', png.tobytes(), file_name=f'{os.path.splitext(name)[0]}_detections.png', mime='image/png', width='stretch')


# ------------------------------------------------------------------ page
st.markdown(f"""
<div class="hero">
  <h1>🌽 Maize & Weed Detector</h1>
  <p>Upload a photo, take a picture, go live with your camera or upload a video - the model finds maize and weeds and shows what the weeding robot would do.</p>
  <span class="chip"><span class="dot" style="background:{UI['maize']}"></span>maize - protected</span>
  <span class="chip"><span class="dot" style="background:{UI['weed']}"></span>weed - target ⊕</span>
  <span class="chip"><span class="dot" style="background:#9aa29c"></span>weed next to maize - skipped</span>
  <span class="chip">🧠 {det.model_name} · {det.imgsz}px</span>
</div>
""", unsafe_allow_html=True)

tab_img, tab_cam, tab_live, tab_vid, tab_robot, tab_about = st.tabs(['🖼️ Upload image', '📸 Take a picture', '🔴 Live camera', '🎞️ Video', '🤖 Robot camera', 'ℹ️ About'])

with tab_img:
    samples = sorted(f for f in glob.glob(os.path.join(SAMPLES_DIR, '*')) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp')))
    cu, cs = st.columns([2, 1]) if samples else (st.container(), None)
    up = cu.file_uploader('Upload a field photo', type=['jpg', 'jpeg', 'png', 'webp', 'bmp'], label_visibility='collapsed')
    pick = None
    if samples:
        pick = cs.selectbox('…or try a sample', ['—'] + [os.path.basename(s) for s in samples])
    if up is not None:
        show_image_result(to_bgr(up), up.name)
    elif pick and pick != '—':
        show_image_result(to_bgr(os.path.join(SAMPLES_DIR, pick)), pick)
    else:
        st.info('Upload a photo of maize / weeds (taken from above works best) to see the detections.')

with tab_cam:
    shot = st.camera_input('Point the camera at the plants and take a picture', label_visibility='visible')
    if shot is not None:
        show_image_result(to_bgr(shot), 'camera.jpg')

with tab_live:
    st.markdown('<div class="section-title">Live detection from your camera</div>', unsafe_allow_html=True)
    st.caption('Click **START** and allow camera access. Every frame is analysed in real time on the server; the boxes appear on the video. '
               'On a phone, use the camera selector to switch to the back camera.')
    try:
        from streamlit_webrtc import webrtc_streamer, WebRtcMode
        import av, threading

        class LiveProcessor:
            def __init__(self):
                self.lock = threading.Lock()
                self.settings = dict(thr=THR, protect=protect, show_conf=show_conf, show_zones=show_zones)
                self.stats = {'maize': 0, 'weeds': 0, 'targets': 0, 'ms': 0.0}

            def recv(self, frame):
                img = frame.to_ndarray(format='bgr24')
                h, w = img.shape[:2]
                if w > 640:
                    img = cv2.resize(img, (640, int(h * 640 / w))); h, w = img.shape[:2]
                with self.lock: cfg = dict(self.settings)
                t0 = time.perf_counter()
                dets = det.predict(img, conf=cfg['thr'])
                ms = (time.perf_counter() - t0) * 1000
                maize, weeds, zones = analyse(dets, w, h, cfg['protect'])
                out = draw(img, maize, weeds, zones, cfg['show_conf'], cfg['show_zones'])
                n_t = sum(not d['protected'] for d in weeds)
                bar = f'maize {len(maize)} | weeds {len(weeds)} | to remove {n_t} | {ms:.0f} ms'
                cv2.rectangle(out, (0, 0), (w, 30), (24, 38, 28), -1)
                cv2.putText(out, bar, (10, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
                with self.lock: self.stats = {'maize': len(maize), 'weeds': len(weeds), 'targets': n_t, 'ms': ms}
                return av.VideoFrame.from_ndarray(out, format='bgr24')

        ctx = webrtc_streamer(
            key='live', mode=WebRtcMode.SENDRECV, video_processor_factory=LiveProcessor, async_processing=True,
            media_stream_constraints={'video': {'width': {'ideal': 640}, 'height': {'ideal': 480}}, 'audio': False},
            rtc_configuration={'iceServers': [{'urls': ['stun:stun.l.google.com:19302', 'stun:stun1.l.google.com:19302']}]},
            video_html_attrs={'style': {'width': '100%', 'maxWidth': '760px', 'borderRadius': '12px'}, 'autoPlay': True, 'controls': False, 'muted': True},
        )
        if ctx.video_processor:                       # push the current sidebar settings to the live stream
            with ctx.video_processor.lock:
                ctx.video_processor.settings = dict(thr=THR, protect=protect, show_conf=show_conf, show_zones=show_zones)
        st.caption('If the video never starts, your network may block live video (WebRTC) - try another network or use "Take a picture".')
    except ImportError:
        st.warning('Live camera needs the `streamlit-webrtc` package - add it to requirements.txt and reinstall.')

with tab_vid:
    vid = st.file_uploader('Upload a video', type=['mp4', 'mov', 'avi', 'mkv', 'm4v'], key='vid')
    o1, o2, o3 = st.columns(3)
    step = o1.select_slider('Analyse every', options=[1, 2, 3, 5, 10], value=2, format_func=lambda v: f'{v} frame' + ('s' if v > 1 else ''))
    max_s = o2.slider('Max length (s)', 5, 120, 30, 5)
    width = o3.select_slider('Output width', options=[480, 640, 960], value=640)
    if vid is not None and st.button('▶️ Analyse video', type='primary'):
        tmp_in = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(vid.name)[1]); tmp_in.write(vid.read()); tmp_in.close()
        cap = cv2.VideoCapture(tmp_in.name)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        total = int(min(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1e9, fps * max_s))
        out_path = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4').name
        import imageio.v2 as imageio
        writer = imageio.get_writer(out_path, fps=max(1.0, fps / step), codec='libx264', quality=7, macro_block_size=16, ffmpeg_log_level='error')
        prog = st.progress(0.0, text='Analysing…')
        live = st.empty()
        stats, i, times = [], 0, []
        while i < total:
            ok, frame = cap.read()
            if not ok: break
            if i % step == 0:
                h, w = frame.shape[:2]
                nw = min(width, w) // 16 * 16; nh = max(16, int(round(h * nw / w / 16)) * 16)   # H.264-friendly size
                frame = cv2.resize(frame, (nw, nh))
                annotated, maize, weeds, ms = run(frame)
                times.append(ms)
                stats.append({'time (s)': round(i / fps, 2), 'maize': len(maize), 'weeds': len(weeds), 'to remove': sum(not d['protected'] for d in weeds)})
                rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
                writer.append_data(rgb)
                if len(stats) % 5 == 1: live.image(rgb, caption=f'frame {i}', width='stretch')
                prog.progress(min(1.0, (i + 1) / max(total, 1)), text=f'Analysing… frame {i + 1}/{total}')
            i += 1
        cap.release(); writer.close(); os.unlink(tmp_in.name)
        prog.empty(); live.empty()
        if not stats:
            st.error('Could not read any frames from this video.')
        else:
            df = pd.DataFrame(stats)
            st.session_state['video_result'] = (open(out_path, 'rb').read(), df, float(np.mean(times)), vid.name)
            os.unlink(out_path)
    if 'video_result' in st.session_state:
        data, df, avg_ms, vname = st.session_state['video_result']
        left, right = st.columns([1.65, 1], gap='large')
        with left:
            st.video(data)
        with right:
            st.markdown('<div class="section-title">Video summary</div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            card(c1, 'Frames analysed', len(df))
            card(c2, 'Avg inference', f'{avg_ms:.0f} ms')
            c3, c4 = st.columns(2)
            card(c3, '🌽 Max maize', int(df['maize'].max()), 'in one frame')
            card(c4, '🌿 Max weeds', int(df['weeds'].max()), 'in one frame')
            st.download_button('⬇️ Download annotated video', data, file_name=f'{os.path.splitext(vname)[0]}_detections.mp4', mime='video/mp4', width='stretch')
        st.markdown('<div class="section-title">Plants detected over time</div>', unsafe_allow_html=True)
        st.line_chart(df.set_index('time (s)')[['maize', 'weeds']], color=[UI['maize'], UI['weed']], height=240)

with tab_robot:
    st.markdown('<div class="section-title">Watch the robot\'s own camera</div>', unsafe_allow_html=True)
    st.caption('Shows the live view from the Raspberry Pi while `weed_robot.py` is running on it. '
               'Works when this app runs on a laptop connected to the same Wi-Fi/hotspot as the robot '
               '(the online version cannot reach the robot\'s local address).')
    url = st.text_input('Robot stream address', 'http://10.67.116.127:8000')
    if st.toggle('Show robot camera', False):
        st.markdown(f'<img src="{url}" style="width:100%;max-width:960px;border-radius:12px;border:1px solid #e3e8e1">', unsafe_allow_html=True)

with tab_about:
    st.markdown(f"""
#### How it works
1. The picture is resized to **{det.imgsz} × {det.imgsz} px** and passed to the **{det.model_name}** detector (NCNN format - the same file that runs on the robot's Raspberry Pi).
2. Each box gets a class (**maize** or **weed**) and a confidence. Boxes below the thresholds in the sidebar are dropped.
3. **Robot logic:** every maize box gets a safety zone; weeds touching a zone are **skipped**, all other weeds are **targets** (⊕ marks the aiming point).

#### The model
- Trained on 7,308 field images (Nigeria, CornWeed, CropAndWeed, ACRE, Roboflow) - 35k maize and 304k weed boxes.
- Test set: maize mAP@0.5 ≈ 0.94, weed ≈ 0.70 (all images); Nigerian images: maize ≈ 0.90, weed ≈ 0.47.
- On the Raspberry Pi 4: ~145 ms per frame (~7 FPS) at {det.imgsz} px.

#### Tips
- Photos taken **from above**, 40-60 cm over the plants, in daylight work best - like the robot's camera.
- The model only knows field scenes: indoor or non-plant photos can give random boxes.
""")

st.markdown('<div class="foot">Maize & weed detection for an autonomous weeding robot · YOLO + NCNN · Streamlit</div>', unsafe_allow_html=True)
