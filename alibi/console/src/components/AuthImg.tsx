import { useEffect, useState } from 'react';
import { getToken } from '../lib/auth';

/**
 * Fetch an authenticated image endpoint into an object URL. Evidence frames sit
 * behind auth, and a plain <img src> can't send an Authorization header — so
 * fetch the bytes with the token and render them from an object URL (revoked on
 * unmount). Shared by AuthImg (whole frame) and CropImg (bbox crop).
 */
export function useAuthObjectUrl(src: string): { url: string | null; failed: boolean } {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let revoked = false;
    let objectUrl: string | null = null;
    const token = getToken();
    setUrl(null);
    setFailed(false);
    fetch(src, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then(r => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then(b => {
        if (revoked) return;
        objectUrl = URL.createObjectURL(b);
        setUrl(objectUrl);
      })
      .catch(() => { if (!revoked) setFailed(true); });
    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src]);

  return { url, failed };
}

/** An <img> for an authenticated endpoint. */
export function AuthImg({ src, alt, className }: { src: string; alt: string; className?: string }) {
  const { url, failed } = useAuthObjectUrl(src);

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
  return <img src={url} alt={alt} className={className} loading="lazy" />;
}
