"""
FastALPR swap — live demo / verification.

Generates a synthetic plate + scene, then runs BOTH pipelines through the
IDENTICAL caller pattern used across the codebase:

    plates = detector.detect(frame, max_plates=3)
    for p in plates:
        text, conf = ocr.read_plate(p.plate_image)

- LEGACY: alibi.plates.plate_detect.PlateDetector  (OpenCV contours)
- NEW:    alibi.plates.fast_alpr_engine.PlateDetector + PlateOCR (trained ONNX)

Run:  python plates_fastalpr_demo.py
"""

import cv2
import numpy as np

PLATE_TEXT = "N12345W"


def make_plate_crop(text: str = PLATE_TEXT, w: int = 440, h: int = 140) -> np.ndarray:
    """Render a clean plate crop (white bg, black chars, plate proportions)."""
    img = np.full((h, w, 3), 245, dtype=np.uint8)
    cv2.rectangle(img, (4, 4), (w - 5, h - 5), (20, 20, 20), 3)
    font = cv2.FONT_HERSHEY_DUPLEX
    scale = 3.0
    thick = 6
    (tw, th), _ = cv2.getTextSize(text, font, scale, thick)
    org = ((w - tw) // 2, (h + th) // 2)
    cv2.putText(img, text, org, font, scale, (15, 15, 15), thick, cv2.LINE_AA)
    return img


def make_scene(plate: np.ndarray, W: int = 960, H: int = 640) -> np.ndarray:
    """Composite the plate onto a textured 'vehicle' scene."""
    rng = np.random.default_rng(7)
    scene = rng.integers(40, 90, size=(H, W, 3), dtype=np.uint8)
    # a darker 'car body' block
    cv2.rectangle(scene, (180, 200, ), (780, 560), (70, 60, 55), -1)
    cv2.rectangle(scene, (300, 300), (660, 420), (90, 80, 75), -1)  # 'bumper'
    # mount the plate
    ph, pw = plate.shape[:2]
    x, y = (W - pw) // 2, 440
    scene[y:y + ph, x:x + pw] = plate
    # a little blur/noise to look less synthetic
    scene = cv2.GaussianBlur(scene, (3, 3), 0)
    return scene, (x, y, pw, ph)


def run_legacy(scene, plate_crop):
    print("\n=== LEGACY pipeline (OpenCV contours + EasyOCR) ===")
    try:
        from alibi.plates.plate_detect import PlateDetector as LegacyDetector
    except Exception as e:
        print(f"  [detector] import failed: {e}")
        return
    det = LegacyDetector()
    regions = det.detect(scene, max_plates=5)
    print(f"  contour detector returned {len(regions)} candidate region(s)")
    for i, r in enumerate(regions):
        print(f"    region {i}: bbox={r.bbox} conf={r.confidence:.2f}")
    # OCR (EasyOCR) is optional/heavy; only run if installed.
    try:
        from alibi.plates.plate_ocr import PlateOCR as LegacyOCR
        ocr = LegacyOCR()
        if ocr.ocr_type == "none":
            print("  [ocr] EasyOCR/Tesseract not installed — skipping legacy OCR")
        else:
            text, conf = ocr.read_plate(plate_crop)
            print(f"  [ocr:{ocr.ocr_type}] on clean crop -> '{text}' (conf {conf:.2f})")
    except Exception as e:
        print(f"  [ocr] skipped: {e}")


def run_new(scene, plate_crop):
    print("\n=== NEW pipeline (FastALPR: trained ONNX detector + OCR) ===")
    from alibi.plates.fast_alpr_engine import PlateDetector, PlateOCR
    det = PlateDetector(conf_thresh=0.25)
    ocr = PlateOCR()

    # Full scene detection (the real-world path)
    plates = det.detect(scene, max_plates=3)
    print(f"  trained detector found {len(plates)} plate(s) in the full scene")
    for i, p in enumerate(plates):
        text, conf = ocr.read_plate(p.plate_image)
        print(f"    plate {i}: bbox={p.bbox} det_conf={p.confidence:.2f} "
              f"-> OCR '{text}' (conf {conf:.2f})")

    # OCR on the clean crop (isolates OCR quality)
    text, conf = ocr.read_plate(plate_crop)
    print(f"  [ocr:{ocr.ocr_type}] on clean crop -> '{text}' (conf {conf:.2f})  "
          f"[ground truth: {PLATE_TEXT}]")


def main():
    plate_crop = make_plate_crop()
    scene, gt_box = make_scene(plate_crop)
    print(f"Ground-truth plate '{PLATE_TEXT}' mounted at bbox={gt_box} in a "
          f"{scene.shape[1]}x{scene.shape[0]} scene")

    run_legacy(scene, plate_crop)
    run_new(scene, plate_crop)


if __name__ == "__main__":
    main()
