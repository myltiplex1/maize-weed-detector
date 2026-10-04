# 🌽 Maize & Weed Detector — Streamlit app

Web dashboard for the ML part of the weeding robot. Upload a photo, take a picture with your
phone/laptop camera, or upload a video — the YOLO model finds **maize** and **weeds**, draws the
boxes and shows what the robot would do (protect maize, target weeds that are not next to maize).

It runs the same **NCNN** model file used on the Raspberry Pi, with a small custom loader
(`detector.py`) — no PyTorch needed, so it installs fast and fits on Streamlit Community Cloud.
The loader reproduces Ultralytics' predictions exactly (checked box-for-box).

## Folder layout
```
maize_weed_app/
├── app.py                 # the dashboard
├── detector.py            # NCNN model loader + pre/post-processing
├── requirements.txt
├── .streamlit/config.toml # colours / theme, upload size
├── models/                # ← put maize_weed_yolo26n_ncnn_416/ here (see models/README.txt)
└── samples/               # optional demo photos
```

## 1. Add the model
Unzip `maize_weed_yolo26n_ncnn_416.zip` into `models/` so you get
`models/maize_weed_yolo26n_ncnn_416/robot_config.json` and `.../maize_weed_ncnn_model/model.ncnn.param`.
(Optional: also unzip the YOLO11n `maize_weed_ncnn_416.zip` to compare models in the sidebar.)

## 2. Run on your laptop (to test)
```bash
cd maize_weed_app
python -m venv .venv
.venv\Scripts\activate          # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
streamlit run app.py
```
Your browser opens at http://localhost:8501.

## 3. Deploy on Streamlit Community Cloud (free)
1. Create a GitHub account (if needed) and a **new repository**, e.g. `maize-weed-detector`.
2. Upload **everything in this folder** to the repository, *including* `models/maize_weed_yolo26n_ncnn_416/`
   and the hidden `.streamlit/` folder (on github.com: "Add file → Upload files", drag the folders in).
3. Go to **https://share.streamlit.io**, sign in with GitHub → **Create app** → *Deploy a public app from GitHub*.
4. Repository: your repo · Branch: `main` · Main file path: `app.py`.
5. *Advanced settings* → Python version **3.12** → Save → **Deploy**.
6. After 2–4 minutes you get a public link like `https://maize-weed-detector.streamlit.app` to share.

Updating: change a file on GitHub and the app redeploys automatically.

## Using the app
- **Upload image** / **Take a picture**: result on the left, prediction panel on the right
  (counts, confidence, robot decision, table of every box, download button).
- **Video**: choose how many frames to analyse; you get an annotated video, a summary and a chart
  of maize/weeds over time. Long videos are cut to the "Max length" setting.
- **Sidebar**: switch model, change the maize/weed thresholds (defaults come from the model's
  `robot_config.json`), maize safety margin, toggle labels/zones.

Note: the camera tab needs HTTPS (works on the deployed site and on localhost).
