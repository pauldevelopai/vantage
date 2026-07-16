import { useEffect, useRef, useState } from 'react';
import Hls from 'hls.js';
import { api } from '../lib/api';
import { getToken } from '../lib/auth';

/**
 * On-demand live player for one camera. Heartbeats /watch while mounted so the
 * recorder streams it, and tears down on unmount. Tuned to BUFFER rather than
 * chase the live edge — low-latency mode starves the buffer over a cloud relay
 * and causes the stutter; here we keep a few seconds buffered for smoothness.
 */
export function LivePlayer({ cameraId, name }: { cameraId: string; name: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState<'connecting' | 'live' | 'error'>('connecting');
  const [message, setMessage] = useState('Connecting…');

  useEffect(() => {
    let hls: Hls | null = null;
    let cancelled = false;
    const token = getToken();
    const src = `/api/cameras/${cameraId}/hls/index.m3u8`;

    api.watchCamera(cameraId).catch(() => {});
    const beat = setInterval(() => api.watchCamera(cameraId).catch(() => {}), 5000);
    const giveUp = setTimeout(() => {
      if (!cancelled && status !== 'live') { setStatus('error'); setMessage('No video — is the recorder running?'); }
    }, 30000);

    if (!Hls.isSupported()) {
      setStatus('error'); setMessage('This browser can’t play the stream.');
    } else {
      hls = new Hls({
        xhrSetup: (xhr: XMLHttpRequest) => { if (token) xhr.setRequestHeader('Authorization', 'Bearer ' + token); },
        lowLatencyMode: false,          // buffer instead of chasing the edge -> smooth
        liveSyncDurationCount: 4,       // sit ~4 segments behind live
        maxBufferLength: 12,            // keep up to 12s buffered
        maxMaxBufferLength: 30,
        fragLoadingMaxRetry: 8,
      });
      hls.loadSource(src);
      hls.attachMedia(videoRef.current!);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        if (cancelled) return;
        clearTimeout(giveUp);
        setStatus('live');
        videoRef.current?.play().catch(() => {});
      });
      hls.on(Hls.Events.ERROR, (_e, data) => {
        if (!data.fatal || cancelled) return;
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          setTimeout(() => { if (!cancelled && hls) hls.loadSource(src); }, 1500);
        } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
          hls?.recoverMediaError();
        } else {
          setStatus('error'); setMessage('Stream error.');
        }
      });
    }

    return () => { cancelled = true; clearInterval(beat); clearTimeout(giveUp); if (hls) hls.destroy(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId]);

  return (
    <div className="bg-gray-900 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-800">
        <span className="text-white text-sm font-medium truncate">{name}</span>
        {status === 'live' && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-600 text-white flex-none">● LIVE</span>}
      </div>
      <div className="relative bg-black aspect-video flex items-center justify-center">
        <video ref={videoRef} className="w-full h-full" muted playsInline controls />
        {status !== 'live' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-4 bg-black/60">
            {status === 'connecting' && (
              <svg className="animate-spin h-5 w-5 text-white mb-2" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
            )}
            <p className="text-xs text-gray-200">{message}</p>
          </div>
        )}
      </div>
    </div>
  );
}
