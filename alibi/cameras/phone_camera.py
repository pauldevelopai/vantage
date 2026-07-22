"""
Your phone as a camera, in about thirty seconds.

An old handset on a windowsill is a real camera. The bridge protocol the
desktop recorder speaks is plain HTTP — pair, register, post JPEGs — so a web
page can speak it too, with no app to install and nothing to open on the
router.

It posts to the SAME /cameras/bridge/frame endpoint the recorder uses, which
means a phone is not a side feature: its frames go through detection, plates,
faces, vehicle ReID, scene-change suppression and the retention policy exactly
like any other camera, and show up on Overview, People and Vehicles beside
them.

Two things it does locally, on the phone, before spending anything:
  * only sends when the picture actually CHANGES, so a still room costs
    nothing; and
  * downscales to 1280px, which is what the face and plate passes want (the
    old 640 recorder frames are why plates were unreadable).

Credentials live in localStorage on the handset. Losing the phone means
revoking that bridge from the Cameras page, not rotating anything shared.
"""

PHONE_CAMERA_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>Vantage — phone camera</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body { margin:0; background:#0b1020; color:#e8ecf8;
         font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom); }
  .wrap { max-width:520px; margin:0 auto; padding:20px 16px 40px; }
  h1 { font-size:20px; margin:0 0 4px; }
  .sub { color:#94a3b8; font-size:13px; margin:0 0 20px; }
  .card { background:#131a30; border:1px solid #24304f; border-radius:14px;
          padding:16px; margin-bottom:14px; }
  label { display:block; font-size:13px; color:#94a3b8; margin-bottom:6px; }
  input { width:100%; padding:13px; font-size:17px; border-radius:10px;
          border:1px solid #2c3a5e; background:#0c1223; color:#e8ecf8;
          text-align:center; letter-spacing:.18em; text-transform:uppercase; }
  button { width:100%; padding:15px; font-size:16px; font-weight:600;
           border:0; border-radius:10px; background:#4f46e5; color:#fff; margin-top:12px; }
  button:disabled { opacity:.5; }
  button.ghost { background:#1e293b; color:#cbd5e1; }
  video { width:100%; border-radius:12px; background:#000; display:block; }
  .row { display:flex; gap:10px; align-items:center; justify-content:space-between; }
  .stat { font-variant-numeric:tabular-nums; font-weight:600; }
  .muted { color:#94a3b8; font-size:12px; }
  .ok { color:#4ade80; } .warn { color:#fbbf24; } .err { color:#f87171; }
  .dot { width:9px;height:9px;border-radius:50%;background:#475569;display:inline-block;margin-right:7px; }
  .dot.live { background:#4ade80; box-shadow:0 0 9px #4ade80; }
  .hide { display:none; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Use this phone as a camera</h1>
  <p class="sub">It feeds the same system as your other cameras — people, vehicles and plates all land in the usual places.</p>

  <!-- Step 1: pair -->
  <div class="card" id="pairCard">
    <label for="code">Pairing code from the Cameras page</label>
    <input id="code" autocomplete="one-time-code" autocapitalize="characters"
           inputmode="latin" placeholder="ABC123">
    <label style="margin-top:14px">What to call this camera</label>
    <input id="name" style="letter-spacing:normal;text-transform:none;text-align:left"
           placeholder="Kitchen window" value="Phone camera">
    <button id="pairBtn">Pair this phone</button>
    <p class="muted" id="pairMsg" style="margin-bottom:0"></p>
  </div>

  <!-- Step 2: watch -->
  <div class="card hide" id="camCard">
    <div class="row" style="margin-bottom:12px">
      <div><span class="dot" id="dot"></span><span id="state">Ready</span></div>
      <button class="ghost" id="flip" style="width:auto;padding:8px 14px;margin:0">Flip</button>
    </div>
    <video id="v" playsinline muted autoplay></video>
    <button id="startBtn" style="margin-top:14px">Start watching</button>
    <button class="ghost hide" id="stopBtn">Stop</button>
    <div class="row" style="margin-top:14px">
      <span class="muted">Frames sent</span><span class="stat" id="sent">0</span>
    </div>
    <div class="row" style="margin-top:6px">
      <span class="muted">Last</span><span class="stat muted" id="last">—</span>
    </div>
    <p class="muted" style="margin-top:14px;margin-bottom:0">
      It keeps watching while nothing moves — a still room is fine, it just
      stays quiet and checks in every minute. Only frames where something
      changes are sent.<br><br>
      Leave this page in front with the screen on. Phones suspend background
      tabs, so switching apps or locking the screen will pause it — it says so
      above if that happens, and picks up again when you come back.
    </p>
    <button class="ghost" id="forget" style="margin-top:14px">Unpair this phone</button>
  </div>
</div>

<script>
(function () {
  var API = location.origin + '/api';
  var LS = 'vantage.phone.creds';
  var creds = null;
  try { creds = JSON.parse(localStorage.getItem(LS) || 'null'); } catch (e) {}

  var $ = function (id) { return document.getElementById(id); };
  var stream = null, timer = null, facing = 'environment';
  var prev = null, sent = 0;

  // Only spend on frames where something actually changed. A coarse greyscale
  // difference is enough to tell "someone walked in" from "the room is still",
  // and it costs nothing to compute on the handset.
  var GRID = 16, CHANGE = 0.045, INTERVAL_MS = 4000, MAX_W = 1280;

  function show(step) {
    $('pairCard').classList.toggle('hide', step !== 'pair');
    $('camCard').classList.toggle('hide', step !== 'cam');
  }

  function setState(text, cls) {
    $('state').textContent = text;
    $('state').className = cls || '';
  }

  // ---- pairing -----------------------------------------------------------
  $('pairBtn').onclick = async function () {
    var code = $('code').value.trim().toUpperCase();
    if (!code) { $('pairMsg').textContent = 'Enter the code first.'; return; }
    $('pairBtn').disabled = true;
    $('pairMsg').className = 'muted';
    $('pairMsg').textContent = 'Pairing…';
    try {
      var r = await fetch(API + '/cameras/bridge/register', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: code, kind: 'phone',
                               name: $('name').value.trim() || 'Phone camera' })
      });
      if (!r.ok) throw new Error((await r.json().catch(function(){return{};})).detail || 'Pairing failed');
      var c = await r.json();
      creds = {
        bridge_id: c.bridge_id, token: c.token,
        // The server names the camera so both ends agree; fall back only if
        // talking to an older build.
        camera_id: c.camera_id || ('phone-' + c.bridge_id.slice(-6)),
        name: $('name').value.trim() || 'Phone camera'
      };
      localStorage.setItem(LS, JSON.stringify(creds));
      show('cam');
      startCamera();
    } catch (e) {
      $('pairMsg').className = 'err';
      $('pairMsg').textContent = e.message + ' — codes expire, so ask for a fresh one.';
    } finally { $('pairBtn').disabled = false; }
  };

  $('forget').onclick = function () {
    if (!confirm('Unpair this phone? It will stop sending frames.')) return;
    stopWatching();
    localStorage.removeItem(LS);
    creds = null;
    show('pair');
  };

  // ---- camera ------------------------------------------------------------
  async function startCamera() {
    try {
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: facing, width: { ideal: 1920 } }, audio: false
      });
      $('v').srcObject = stream;
      setState('Camera ready');
    } catch (e) {
      setState('No camera access — allow it in your browser settings', 'err');
    }
  }

  $('flip').onclick = function () {
    facing = (facing === 'environment') ? 'user' : 'environment';
    startCamera();
  };

  function grab(maxW) {
    var v = $('v');
    if (!v.videoWidth) return null;
    var scale = Math.min(1, maxW / v.videoWidth);
    var c = document.createElement('canvas');
    c.width = Math.round(v.videoWidth * scale);
    c.height = Math.round(v.videoHeight * scale);
    c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
    return c;
  }

  function signature() {
    var c = grab(GRID * 4);
    if (!c) return null;
    var d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    var out = [];
    for (var i = 0; i < d.length; i += 4) out.push((d[i] + d[i+1] + d[i+2]) / 3);
    return out;
  }

  function changed(a, b) {
    if (!a || !b || a.length !== b.length) return true;
    var diff = 0;
    for (var i = 0; i < a.length; i++) diff += Math.abs(a[i] - b[i]);
    return (diff / a.length / 255) > CHANGE;
  }

  // Say we're alive even when nothing moves. Without this, a phone watching a
  // still room looks identical to a phone that has been switched off.
  var lastBeat = 0;
  async function heartbeat() {
    if (!creds || Date.now() - lastBeat < 60000) return;
    lastBeat = Date.now();
    try {
      await fetch(API + '/cameras/bridge/heartbeat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Bridge-Id': creds.bridge_id,
          'X-Bridge-Token': creds.token
        },
        body: '{}'
      });
    } catch (e) { /* the next tick tries again */ }
  }

  var lastTick = 0;

  async function tick() {
    lastTick = Date.now();
    heartbeat();
    // A still scene is not a reason to stop. We keep looking and keep saying
    // we're here; the system counts that as recording, just quiet.
    var sig = signature();
    if (!changed(prev, sig)) { setState('Watching — nothing moving', 'muted'); return; }
    prev = sig;
    var c = grab(MAX_W);
    if (!c) return;
    setState('Sending…', 'warn');
    c.toBlob(async function (blob) {
      if (!blob) return;
      try {
        var r = await fetch(API + '/cameras/bridge/frame?camera_id=' +
                            encodeURIComponent(creds.camera_id), {
          method: 'POST',
          headers: {
            'Content-Type': 'image/jpeg',
            'X-Bridge-Id': creds.bridge_id,
            'X-Bridge-Token': creds.token
          },
          body: blob
        });
        if (r.status === 401) {
          setState('This phone is no longer paired', 'err');
          stopWatching();
          return;
        }
        var j = await r.json().catch(function () { return {}; });
        sent++;
        $('sent').textContent = sent;
        $('last').textContent = j.reason === 'throttled' ? 'throttled'
                              : (j.unchanged ? 'no change' : (j.incident ? 'incident raised' : 'analysed'));
        setState('Watching', 'ok');
      } catch (e) {
        setState('Send failed — will retry', 'warn');
      }
    }, 'image/jpeg', 0.85);
  }

  // The wake lock is RELEASED by the browser every time the page is hidden, so
  // asking once means losing it the first time the screen goes off. Re-acquire
  // whenever we're visible and watching.
  var wake = null;
  async function holdScreen() {
    if (!navigator.wakeLock || !timer || document.visibilityState !== 'visible') return;
    try { wake = await navigator.wakeLock.request('screen'); } catch (e) { wake = null; }
  }

  function startWatching() {
    if (!creds) return;
    prev = null;
    lastBeat = 0;
    lastTick = Date.now();
    heartbeat();
    timer = setInterval(tick, INTERVAL_MS);
    $('dot').classList.add('live');
    $('startBtn').classList.add('hide');
    $('stopBtn').classList.remove('hide');
    setState('Watching', 'ok');
    holdScreen();
  }

  function stopWatching() {
    if (timer) clearInterval(timer);
    timer = null;
    $('dot').classList.remove('live');
    $('startBtn').classList.remove('hide');
    $('stopBtn').classList.add('hide');
    setState('Stopped');
  }

  $('startBtn').onclick = startWatching;
  $('stopBtn').onclick = stopWatching;

  // Coming back from a locked screen or another app: the browser may have
  // suspended our timer and stopped the camera track. Pick both up rather than
  // sitting there looking connected while sending nothing.
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState !== 'visible' || !timer) return;
    holdScreen();
    var track = stream && stream.getVideoTracks()[0];
    if (!track || track.readyState === 'ended') startCamera();
    lastTick = Date.now();
    heartbeat();
    setState('Watching', 'ok');
  });

  // If the browser has been throttling us, say so instead of showing a
  // reassuring green dot while nothing is being sent.
  setInterval(function () {
    if (!timer) return;
    var idle = Date.now() - lastTick;
    if (idle > 90000) {
      setState('Paused by the phone — tap the screen', 'warn');
      $('dot').classList.remove('live');
    } else {
      $('dot').classList.add('live');
    }
  }, 15000);

  // The QR carries the code: /phone?code=ABC123. Say so, so the form doesn't
  // look like it still wants something typed.
  var qs = new URLSearchParams(location.search);
  if (qs.get('code')) {
    $('code').value = qs.get('code').toUpperCase();
    $('pairMsg').className = 'muted';
    $('pairMsg').textContent = 'Code filled in from the QR — name this camera and tap Pair.';
    setTimeout(function () { $('name').focus(); }, 200);
  }

  if (creds) { show('cam'); startCamera(); } else { show('pair'); }
})();
</script>
</body>
</html>
"""
