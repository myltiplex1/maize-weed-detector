#!/usr/bin/env python3
"""
find_zone.py - find where the LEDs (laser stand-in) point in the camera picture, automatically.

How it works: takes photos with the LEDs OFF and ON, compares them, and finds the spot that
got brighter. That spot is the fire zone. It prints the --roi numbers to use with weed_robot.py
and saves find_zone.jpg so you can check it.

Use it with the robot built (camera + LEDs in their final positions), robot standing on the ground,
in shade or indoors (bright sunlight can hide the LED light).

  python find_zone.py
  python find_zone.py --led-pins 24 --margin 0.05
"""
import argparse, time
import cv2
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument('--led-pins', default='24')
ap.add_argument('--size', default='640x480')
ap.add_argument('--margin', type=float, default=0.05, help='extra space added around the lit spot (fraction of the picture)')
a = ap.parse_args()
W, H = [int(v) for v in a.size.split('x')]


def find_spot(off, on, margin):
    """Return (roi fractions, bbox px, diff image, strength) of the area that got brighter."""
    d = cv2.subtract(cv2.cvtColor(on, cv2.COLOR_BGR2GRAY), cv2.cvtColor(off, cv2.COLOR_BGR2GRAY))
    d = cv2.GaussianBlur(d, (9, 9), 0)
    strength = int(d.max())
    noise = float(np.percentile(d, 99))                # brightness change of ordinary camera noise
    if strength < max(15, 2.5 * noise + 5):            # the LED spot must stand out clearly from the noise
        return None, None, d, strength
    _, m = cv2.threshold(d, max(12, strength * 0.5), 255, cv2.THRESH_BINARY)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None, None, d, strength
    pts = np.vstack(cnts)                         # both LED spots together
    x, y, w, h = cv2.boundingRect(pts)
    hh, ww = d.shape
    roi = [max(0, x / ww - margin), max(0, y / hh - margin), min(1, (x + w) / ww + margin), min(1, (y + h) / hh + margin)]
    return [round(v, 2) for v in roi], (x, y, w, h), d, strength


if __name__ == '__main__':
    from gpiozero import LEDBoard
    from picamera2 import Picamera2
    leds = LEDBoard(*[int(v) for v in a.led_pins.split(',')])
    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(main={'size': (W, H), 'format': 'RGB888'}))
    cam.start(); time.sleep(2)
    md = cam.capture_metadata()                    # freeze exposure/colour so only the LEDs change
    cam.set_controls({'AeEnable': False, 'AwbEnable': False,
                      'ExposureTime': md['ExposureTime'], 'AnalogueGain': md['AnalogueGain'],
                      'ColourGains': md.get('ColourGains', (1.5, 1.5))})
    time.sleep(1)

    def grab(n=5):
        return np.mean([cam.capture_array().astype(np.float32) for _ in range(n)], axis=0).astype(np.uint8)

    leds.off(); time.sleep(0.5); off = grab()
    leds.on();  time.sleep(0.5); on = grab()
    leds.off(); cam.stop(); leds.close()

    roi, box, diff, strength = find_spot(off, on, a.margin)
    vis = on.copy()
    if roi is None:
        print(f'Could not see the LED light (brightness change only {strength}).')
        print('Try in shade/indoors, check the LEDs light up, or use the manual bottle-cap method.')
    else:
        x, y, w, h = box
        r = [int(roi[0] * W), int(roi[1] * H), int(roi[2] * W), int(roi[3] * H)]
        cv2.rectangle(vis, (r[0], r[1]), (r[2], r[3]), (255, 255, 255), 2)
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 200, 255), 1)
        print(f'LED spot found (brightness change {strength}).')
        print(f'Fire zone: --roi {roi[0]},{roi[1]},{roi[2]},{roi[3]}')
        print(f'Run:  python weed_robot.py --drive --roi {roi[0]},{roi[1]},{roi[2]},{roi[3]}')
    cv2.imwrite('find_zone.jpg', np.hstack([vis, cv2.cvtColor(np.clip(diff.astype(np.int32) * 4, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)]))
    print('Saved find_zone.jpg (left: photo with zone, right: what got brighter)')
