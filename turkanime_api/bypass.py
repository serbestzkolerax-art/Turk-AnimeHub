"""
turkanime.tv (ve türevi kaynaklar) için HTTP oturum yönetimi ve
embed linklerinin şifresini çözme yardımcıları.
"""
import logging
from base64 import b64decode
from hashlib import md5

from Crypto.Cipher import AES
from curl_cffi import requests as cffi_requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# GÜNCELLENDİ: .tv uzantısı genelde banlandığı için aktif olan .co kullanılıyor
BASE_URL = "https://www.turkanime.co"
ECCHICIX_BASE_URL = "https://ecchicix.com"
ANIMECIX_BASE_URL = "https://animecix.tv"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

_sessions = {}
session = None

# ----------------------------------------------------------------------
# NEW: Shared global session – reuses TCP connections across all providers
# ----------------------------------------------------------------------
SHARED_SESSION = cffi_requests.Session(impersonate="chrome", timeout=5)
SHARED_SESSION.headers.update(DEFAULT_HEADERS)

def get_shared_session():
    return SHARED_SESSION
# ----------------------------------------------------------------------

def get_session(domain=None):
    global session
    key = domain or BASE_URL
    if key not in _sessions:
        _sessions[key] = cffi_requests.Session(impersonate="chrome", verify=False)
    if key == BASE_URL:
        session = _sessions[key]
    return _sessions[key]

def fetch(path=None, headers=None, data=None, domain=None):
    if path is None:
        return ""

    base = domain or BASE_URL
    url = path if path.startswith("http") else base.rstrip("/") + "/" + path.lstrip("/")

    req_headers = dict(DEFAULT_HEADERS)
    if headers:
        req_headers.update(headers)

    sess = get_session(domain)
    try:
        if data is not None:
            resp = sess.post(url, data=data, headers=req_headers, timeout=5)
        else:
            resp = sess.get(url, headers=req_headers, timeout=5)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logging.error(f"fetch başarısız ({url}): {e}")
        return ""

CIPHER_PASSPHRASE = "CHANGE_ME"

def _evp_bytes_to_key(password: bytes, salt: bytes, key_len=32, iv_len=16):
    derived = b""
    block = b""
    while len(derived) < key_len + iv_len:
        block = md5(block + password + salt).digest()
        derived += block
    return derived[:key_len], derived[key_len:key_len + iv_len]

def _cryptojs_decrypt(b64_ciphertext: str, passphrase: str) -> str:
    raw = b64decode(b64_ciphertext)
    if raw[:8] != b"Salted__":
        raise ValueError("Beklenmeyen şifreleme formatı (Salted__ önegi yok).")
    salt = raw[8:16]
    ciphertext = raw[16:]
    key, iv = _evp_bytes_to_key(passphrase.encode("utf-8"), salt)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = cipher.decrypt(ciphertext)
    pad_len = padded[-1]
    return padded[:-pad_len].decode("utf-8")

def get_real_url(cipher):
    return _cryptojs_decrypt(cipher, CIPHER_PASSPHRASE)

def unmask_real_url(url, video=None):
    sess = get_session()
    try:
        resp = sess.get(url, headers=DEFAULT_HEADERS, allow_redirects=True, timeout=5)
        return resp.url
    except Exception as e:
        logging.error(f"unmask_real_url başarısız ({url}): {e}")
        return url

def get_m3u8_stream(url):
    sess = get_session()
    try:
        resp = sess.get(url, headers=DEFAULT_HEADERS, allow_redirects=True, timeout=5)
        return resp.url
    except Exception as e:
        logging.error(f"get_m3u8_stream başarısız ({url}): {e}")
        return url

get_session()