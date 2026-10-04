# Raspberry Pi 4 - robot software

Runs the YOLO26n NCNN model on the Pi Camera, protects maize, lights the "laser" LEDs at confirmed
weeds and (optionally) drives the robot along a predefined route, stopping for each weed.

## Hardware (GPIO = BCM numbers)
| Part | Connection |
|---|---|
| Camera | OV5647 Pi Camera on the CAMERA port (if not detected: `camera_auto_detect=0` + `dtoverlay=ov5647` in `/boot/firmware/config.txt`) |
| Motors (L298N, 4 motors, left pair / right pair) | left ENA 12, IN1 17, IN2 27 · right ENB 13, IN3 22, IN4 23 · common GND |
| Laser stand-in LEDs | both on GPIO24 (pin 18), each with its own 330 Ω resistor to GND |
| Cooling | heatsink + fan strongly recommended (the Pi throttles above 80 °C during long runs) |

## Setup (once)
```bash
mkdir -p ~/maize_weed && cd ~/maize_weed          # copy this folder's files here
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # optional, saves ~3 GB
pip install -r requirements-pi.txt
```
Copy the exported model folder `maize_weed_yolo26n_ncnn_416/` (from the training notebook) into `~/maize_weed/`.

## Run
```bash
cd ~/maize_weed && source venv/bin/activate
python weed_robot.py                          # detection + LEDs only (robot does not move)
python weed_robot.py --drive --motors-dry-run # full program, wheels do not move (safe test)
python weed_robot.py --drive                  # full robot: drive route, stop for weeds, LEDs on 1 s, continue
```
Live view in a browser on the same network: `http://<PI_IP>:8000`. Stop with **Ctrl+C**.
Every firing is logged in `logs/actions_<date>.csv`.

Behaviour per weed: robot stops -> weed must be seen in 5 frames (~0.7 s) -> LEDs on 1 s -> continue.
Weeds touching a maize safety zone are never targeted.

Useful options: `--persist 3`, `--led-time 2`, `--confirm-wait 1.0`, `--maize-conf 0.25 --weed-conf 0.35`,
`--roi l,t,r,b` (fire zone), `--record 5` (save photos for retraining), `--route "forward 5 35, right 1 45"`,
`--motors mine` (backup `motors.py`), `--ruler`.

## Motor tests (wheels off the ground)
```bash
python robot_drive.py --dry-run       # nothing moves, prints pin activity
python robot_drive.py                 # drive the ROUTE once
python robot_drive.py --pause-test    # drive, pause 2 s, resume
```
The route is the `ROUTE` line at the top of `robot_drive.py` (slow: 35 % drive, 45 % turn).
`src/test_motors.py` + `src/motor_config.json` are the hardware team's motor driver (unchanged);
note `safety.max_runtime_s` (240 s) caps one run.

## Other tools
- `bench_pi.py` - speed benchmark of every model folder in the current directory -> `pi_benchmark.csv`
- `live_view.py` - camera + detections in the browser, nothing else
- `find_zone.py` - finds where the LEDs/laser shine in the camera picture and prints `--roi` values
