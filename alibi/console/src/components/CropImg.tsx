import { useLayoutEffect, useRef, useState } from 'react';
import { useAuthObjectUrl } from './AuthImg';

/**
 * A crop of an authenticated evidence frame, rendered client-side.
 *
 * The frame is already stored and served whole (`/api/cameras/frames/{id}.jpg`);
 * a face shot or car shot is just that frame scaled/translated so the bbox fills
 * the container — no second image pipeline, no extra storage.
 *
 * VERIFIED 2026-07-17 against real frames from both live cameras: bboxes
 * (FaceSighting.bbox, intel.detections[].bbox) are in the STORED frame's pixel
 * space (the motion job scales uploads to min(iw,640), and detection runs on the
 * decoded stored JPEG). The frame's real dimensions are still read from the
 * loaded image — never assumed from the camera.
 *
 * bbox is [x, y, w, h]; `pad` widens it (a face crop needs headroom to read as
 * a face). Without a bbox it falls back to a plain contained image.
 */
export function CropImg({ src, alt, bbox, pad = 0.35, className }: {
  src: string;
  alt: string;
  bbox?: [number, number, number, number] | number[] | null;
  pad?: number;
  className?: string;
}) {
  const { url, failed } = useAuthObjectUrl(src);
  const boxRef = useRef<HTMLDivElement>(null);
  const [imgStyle, setImgStyle] = useState<React.CSSProperties | null>(null);

  const hasBox = !!bbox && bbox.length === 4 && bbox[2] > 0 && bbox[3] > 0;

  const place = (img: HTMLImageElement) => {
    const el = boxRef.current;
    if (!el || !hasBox) return;
    const [x, y, w, h] = bbox as number[];
    const W = img.naturalWidth, H = img.naturalHeight;
    if (!W || !H) return;
    // Pad the bbox, clamped to the frame.
    const px = w * pad, py = h * pad;
    const bx = Math.max(0, x - px);
    const by = Math.max(0, y - py);
    const bw = Math.min(W, x + w + px) - bx;
    const bh = Math.min(H, y + h + py) - by;
    const cw = el.clientWidth, ch = el.clientHeight;
    if (!cw || !ch || bw <= 0 || bh <= 0) return;
    // Cover: scale so the padded bbox fills the container, centred on it.
    const scale = Math.max(cw / bw, ch / bh);
    setImgStyle({
      position: 'absolute',
      width: W * scale,
      height: H * scale,
      maxWidth: 'none',
      left: cw / 2 - (bx + bw / 2) * scale,
      top: ch / 2 - (by + bh / 2) * scale,
    });
  };

  const imgRef = useRef<HTMLImageElement>(null);
  useLayoutEffect(() => {
    const img = imgRef.current;
    if (img && img.complete && img.naturalWidth) place(img);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  if (failed) {
    return (
      <div className={`flex items-center justify-center bg-slate-800 text-slate-600 text-[10px] ${className || ''}`}>
        frame unavailable
      </div>
    );
  }
  if (!url) {
    return <div className={`animate-pulse bg-slate-800 ${className || ''}`} />;
  }
  if (!hasBox) {
    return <img src={url} alt={alt} className={`object-cover ${className || ''}`} loading="lazy" />;
  }
  return (
    <div ref={boxRef} className={`relative overflow-hidden ${className || ''}`}>
      <img
        ref={imgRef}
        src={url}
        alt={alt}
        style={imgStyle ?? { opacity: 0 }}
        onLoad={e => place(e.currentTarget)}
      />
    </div>
  );
}
