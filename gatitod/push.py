#!/usr/bin/python3
"""Notifications to the phone (and the PC) with Web Push, the browsers' standard system.

Each browser that enables notifications gives us a subscription (an endpoint of its
push service and two keys). To notify:
  - we sign with our VAPID keys (ES256) so the service knows it is us, and
  - we encrypt the message for that browser (RFC 8291, aes128gcm): the push
    service carries it but cannot read it.
The web UI's service worker (static/sw.js) receives it and shows the notification.

Notification kinds (each device chooses which ones it wants):
  waiting  - an agent is waiting for you     done   - an agent finished
  failed   - a task could not be launched    launched - a scheduled task started
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import core
import hostinfo
import store

DIR = core.STATE / 'push'
VAPID = DIR / 'vapid.pem'
SUBS = DIR / 'subs.json'
KINDS = {'waiting': True, 'done': True, 'failed': True, 'launched': False}
# push services ask for a contact; it is not used. Apple's (Safari, iPhone) may
# reject a fake one: config.json -> push_sub ("mailto:you@example.com" or an https URL)
SUBJECT = 'mailto:gatito@localhost'


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def _key():
    DIR.mkdir(parents=True, exist_ok=True)
    if not VAPID.exists():
        k = ec.generate_private_key(ec.SECP256R1())
        VAPID.write_bytes(k.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
        VAPID.chmod(0o600)
    return serialization.load_pem_private_key(VAPID.read_bytes(), None)


def _raw_pub(k) -> bytes:
    return k.public_key().public_bytes(serialization.Encoding.X962,
                                       serialization.PublicFormat.UncompressedPoint)


def public_key() -> str:
    """VAPID public key (base64url), the one pushManager.subscribe() asks for."""
    return _b64(_raw_pub(_key()))


# ---------------------------------------------------------- subscriptions

def subscribe(sub: dict, prefs: dict | None = None, label: str = '') -> dict:
    if not sub.get('endpoint', '').startswith('https://') or not (sub.get('keys') or {}).get('p256dh'):
        return {'ok': False, 'err': 'invalid subscription'}
    with store.edit(SUBS, []) as subs:
        old = next((s for s in subs if s['endpoint'] == sub['endpoint']), None)
        subs[:] = [s for s in subs if s['endpoint'] != sub['endpoint']]
        subs.append({'endpoint': sub['endpoint'], 'keys': sub['keys'], 'label': label[:80],
                     'prefs': {**KINDS, **((old or {}).get('prefs') or {}), **(prefs or {})},
                     'created': (old or {}).get('created') or int(time.time() * 1000)})
    return {'ok': True}


def unsubscribe(endpoint: str) -> dict:
    with store.edit(SUBS, []) as subs:
        subs[:] = [s for s in subs if s['endpoint'] != endpoint]
    return {'ok': True}


def get_sub(endpoint: str) -> dict | None:
    return next((s for s in store.read(SUBS, []) or [] if s['endpoint'] == endpoint), None)


# ------------------------------------------------------------------ sending

def _vapid_header(endpoint: str) -> str:
    u = urllib.parse.urlparse(endpoint)
    k = _key()
    head = _b64(json.dumps({'typ': 'JWT', 'alg': 'ES256'}).encode())
    body = _b64(json.dumps({'aud': f'{u.scheme}://{u.netloc}', 'exp': int(time.time()) + 12 * 3600,
                            'sub': core.config().get('push_sub') or SUBJECT}).encode())
    r, s = decode_dss_signature(k.sign(f'{head}.{body}'.encode(), ec.ECDSA(hashes.SHA256())))
    sig = _b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))
    return f'vapid t={head}.{body}.{sig}, k={_b64(_raw_pub(k))}'


def _hkdf(salt: bytes, ikm: bytes, info: bytes, n: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=n, salt=salt, info=info).derive(ikm)


def _encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    """RFC 8291 + RFC 8188 (aes128gcm), a single record."""
    ua_pub = _unb64(p256dh)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub)
    eph = ec.generate_private_key(ec.SECP256R1())
    as_pub = _raw_pub(eph)
    secret = eph.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(_unb64(auth), secret, b'WebPush: info\x00' + ua_pub + as_pub, 32)
    salt = os.urandom(16)
    cek = _hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = _hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
    body = AESGCM(cek).encrypt(nonce, payload + b'\x02', None)
    return salt + (4096).to_bytes(4, 'big') + bytes([len(as_pub)]) + as_pub + body


def _send(sub: dict, msg: dict) -> int:
    data = _encrypt(json.dumps(msg, ensure_ascii=False).encode(), sub['keys']['p256dh'], sub['keys']['auth'])
    req = urllib.request.Request(sub['endpoint'], data=data, method='POST', headers={
        'Authorization': _vapid_header(sub['endpoint']), 'Content-Encoding': 'aes128gcm',
        'Content-Type': 'application/octet-stream', 'TTL': '86400', 'Urgency': 'high'})
    try:
        ctx = hostinfo.ssl_ctx(core.config().get('ca_extra'))
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return 0


def notify(kind: str, title: str, body: str = '', url: str = '/', tag: str | None = None,
           only: str | None = None, perm: str | None = None) -> dict:
    """Notify the devices that want this kind of notification (or only `only`).

    `perm`: id of a permission request; the notification carries a "Deny" button.
    """
    subs = [s for s in store.read(SUBS, []) or []
            if (only and s['endpoint'] == only) or (not only and s['prefs'].get(kind, KINDS.get(kind)))]
    msg = {'title': title, 'body': body[:240], 'url': url, 'tag': tag or kind, 'kind': kind}
    if perm:
        msg['perm'] = perm
    gone, sent = [], 0
    for s in subs:
        code = _send(s, msg)
        if code in (404, 410):  # the browser no longer wants it
            gone.append(s['endpoint'])
        elif 200 <= code < 300:
            sent += 1
        else:
            print(f'push: {code} at {urllib.parse.urlparse(s["endpoint"]).netloc}', flush=True)
    for e in gone:
        unsubscribe(e)
    return {'ok': True, 'sent': sent, 'total': len(subs)}


def notify_bg(*a, **k):
    """Same as notify, without waiting for the network."""
    try:   # the notification reaches your own devices: with the real values, not the placeholders
        import mask
        a = tuple(mask.unmask(x) if i in (1, 2) else x for i, x in enumerate(a))
    except Exception:
        pass
    threading.Thread(target=notify, args=a, kwargs=k, daemon=True).start()


# ------------------------------------------------------- watching agents

_prev: dict[str, tuple] | None = None
TERMINAL_PERM_S = 60   # a terminal session asking for permission notifies if you have gone a minute without answering


def _watched(a: dict, now: float) -> bool:
    if a.get('kind') == 'background':
        return True
    p = a.get('perm')
    return bool(p) and now - p['created'] > TERMINAL_PERM_S


def watch(agents: list[dict]):
    """Called on every turn of the status loop: notifies about changes."""
    global _prev
    t = time.time()
    now = {a['key']: (a['group'], (a.get('perm') or {}).get('id')) for a in agents if _watched(a, t)}
    asks = {a['key'] for a in agents if (a.get('perm') or {}).get('kind') == 'ask'}
    if _prev is not None:
        for a in agents:
            k = a['key']
            if k not in now or now[k] == _prev.get(k):
                continue
            (g, perm), before = now[k], (_prev.get(k) or (None, None))[0]
            name = a.get('name') or k
            if perm and k in asks:
                notify_bg('waiting', f'Asks you: {name}', a.get('needs') or '', f'/#{k}', tag=k)
            elif perm:
                # same tag as "Waiting for you": if that notification arrived earlier, this one replaces it
                notify_bg('waiting', f'Asks permission: {name}', a.get('needs') or '', f'/#{k}',
                          tag=k, perm=perm)
            elif g == 'waiting' and before != 'waiting':
                notify_bg('waiting', f'Waiting for you: {name}', a.get('needs') or 'Needs your reply.',
                          f'/#{k}', tag=k)
            elif g == 'recent' and before == 'working':
                notify_bg('done', f'Finished: {name}', a.get('result') or a.get('detail') or '',
                          f'/#{k}', tag=k)
    _prev = now
