"""
Gecmis analizleri GitHub reposundaki bir klasore (reports/) JSON olarak
kaydetmek ve geri okumak icin yardimci fonksiyonlar.

GitHub REST API kullanir, bir Personal Access Token gerektirir. Bu token
Streamlit Cloud'da "Secrets" bolumune GITHUB_TOKEN olarak eklenmelidir.
Yerel calistirmada ise .streamlit/secrets.toml dosyasina eklenir (bu dosya
.gitignore'da oldugu icin GitHub'a yuklenmez).
"""

import base64
import io
import json

import numpy as np
import pandas as pd
import requests
import streamlit as st

GITHUB_OWNER = "YasinSinan"
GITHUB_REPO = "invoice"
GITHUB_BRANCH = "main"
REPORTS_DIR = "reports"
RAW_DATA_DIR = "data"
API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"


class GithubStorageError(Exception):
    pass


def _kontrol_et(resp, baglam=""):
    """resp.raise_for_status() yerine kullanilir - GitHub API hatasini
    (401/403/422/500 vb.) genel bir 'requests.HTTPError' yerine, GitHub'in
    kendi hata mesajini da iceren okunakli bir GithubStorageError'a cevirir.
    Boylece hata app.py'deki 'except GithubStorageError' bloklariyla
    yakalanip kullaniciya duzgun gosterilir - uygulama tamamen cokmez."""
    if resp.ok:
        return resp
    try:
        detay = resp.json().get("message", resp.text[:200])
    except Exception:
        detay = resp.text[:200] if resp.text else "(bos yanit)"

    if resp.status_code == 401:
        aciklama = "GITHUB_TOKEN gecersiz veya suresi dolmus. Streamlit Cloud Secrets'taki token'i kontrol et/yenile."
    elif resp.status_code == 403:
        aciklama = "Yetki reddedildi (rate limit asilmis olabilir ya da token'in bu depoya yazma/okuma izni yok)."
    elif resp.status_code == 404:
        aciklama = "Kaynak bulunamadi (dosya/donem GitHub'da yok)."
    elif resp.status_code == 409:
        aciklama = "Cakisma olustu (dosya baska bir islemde ayni anda degisti). Tekrar dene."
    elif resp.status_code == 422:
        aciklama = "Istek GitHub tarafindan reddedildi (gecersiz veri)."
    else:
        aciklama = "GitHub API hatasi."

    onek = f"{baglam}: " if baglam else ""
    raise GithubStorageError(f"{onek}{aciklama} (HTTP {resp.status_code}) - {detay}")


def _get_token():
    try:
        token = st.secrets.get("GITHUB_TOKEN")
    except Exception:
        token = None
    if not token:
        raise GithubStorageError(
            "GITHUB_TOKEN bulunamadi. Streamlit Cloud'da uygulama ayarlarindan "
            "Secrets bolumune GITHUB_TOKEN = \"...\" seklinde eklemeniz gerekiyor."
        )
    return token


def _headers():
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Accept": "application/vnd.github+json",
    }


def _raw_headers():
    """GitHub, Contents API'de 1MB'dan buyuk dosyalarda base64 icerigi
    dondurmuyor. Bu header ile dosya icerigi dogrudan ham (raw) bytes
    olarak alinir, boyut sinirlamasi olmaz."""
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Accept": "application/vnd.github.raw",
    }


def list_saved_reports():
    """reports/ klasorundeki kayitli donemleri (dosya adi - .json haric) listeler.
    En yeni donem en basta olacak sekilde sirali dondurur. Klasor yoksa veya
    bos ise bos liste doner.
    """
    url = f"{API_BASE}/contents/{REPORTS_DIR}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code == 404:
            return []
        _kontrol_et(resp, "Gecmis raporlar listelenirken")
        files = resp.json()
        names = sorted(
            (f["name"][:-5] for f in files if f["name"].endswith(".json")),
            reverse=True,
        )
        return list(names)
    except GithubStorageError:
        raise
    except Exception as e:
        raise GithubStorageError(f"Gecmis raporlar listelenemedi: {e}")


def load_report(period):
    """Belirli bir donemin kayitli raporunu (JSON) okur ve dict olarak dondurur."""
    url = f"{API_BASE}/contents/{REPORTS_DIR}/{period}.json"
    resp = requests.get(url, headers=_headers(), timeout=15)
    _kontrol_et(resp, "Rapor okunurken")
    data = resp.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content)


def _json_default(obj):
    """summary sozlugundeki bazi degerler pandas/numpy islemlerinden geldigi
    icin numpy.int64/float64 olabilir - bunlar standart json.dumps ile
    serilestirilemez, bu fonksiyon onlari native Python tipine cevirir."""
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"{type(obj)} JSON'a cevrilemiyor")


def save_report(period, payload):
    """Bir donemin raporunu (dict) JSON olarak reports/{period}.json'a kaydeder.
    Dosya zaten varsa icerigini guncelletir (uzerine yazar).
    """
    url = f"{API_BASE}/contents/{REPORTS_DIR}/{period}.json"

    sha = None
    existing = requests.get(url, headers=_headers(), timeout=15)
    if existing.status_code == 200:
        sha = existing.json()["sha"]
    elif existing.status_code not in (404,):
        _kontrol_et(existing, "Rapor kaydedilirken (mevcut dosya kontrolu)")

    content_str = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
    content_b64 = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")

    body = {
        "message": f"Rapor kaydedildi: {period}",
        "content": content_b64,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        body["sha"] = sha

    resp = requests.put(url, headers=_headers(), json=body, timeout=15)
    _kontrol_et(resp, "Rapor kaydedilirken")
    return resp.json()


def delete_report(period):
    """Belirli bir donemin kayitli raporunu siler."""
    url = f"{API_BASE}/contents/{REPORTS_DIR}/{period}.json"
    existing = requests.get(url, headers=_headers(), timeout=15)
    _kontrol_et(existing, "Rapor silinirken (dosya bulunamadi)")
    sha = existing.json()["sha"]

    body = {
        "message": f"Rapor silindi: {period}",
        "sha": sha,
        "branch": GITHUB_BRANCH,
    }
    resp = requests.delete(url, headers=_headers(), json=body, timeout=15)
    _kontrol_et(resp, "Rapor silinirken")
    return resp.json()


# ----------------------------------------------------------------------
# Ham gelir/gider dosyalarinin arsivlenmesi
#
# Yapisi:  data/{period}/gelir/{dosya_adi}
#          data/{period}/gider/{dosya_adi}
#          data/{period}/gider/_meta.json  -> {"dosya_adi.xlsx": "UniUni", ...}
# Boylece bir donemin (orn. "2026-07") tum fatura dosyalari saklanir ve
# istenen zaman tekrar indirilip analiz calistirilabilir.
# ----------------------------------------------------------------------

def list_periods():
    """data/ altindaki kayitli donemleri (klasor adlarini), en yeni en basta
    olacak sekilde listeler. Hic dosya arsivlenmemisse bos liste doner."""
    url = f"{API_BASE}/contents/{RAW_DATA_DIR}"
    resp = requests.get(url, headers=_headers(), timeout=15)
    if resp.status_code == 404:
        return []
    _kontrol_et(resp, "Donemler listelenirken")
    items = resp.json()
    periods = sorted((it["name"] for it in items if it["type"] == "dir"), reverse=True)
    return periods


def list_raw_files(period, category):
    """Bir donemin gelir/gider klasorundeki dosya adlarini listeler
    (_meta.json haric)."""
    url = f"{API_BASE}/contents/{RAW_DATA_DIR}/{period}/{category}"
    resp = requests.get(url, headers=_headers(), timeout=15)
    if resp.status_code == 404:
        return []
    _kontrol_et(resp, "Dosya listesi alinirken")
    items = resp.json()
    return sorted(it["name"] for it in items if it["type"] == "file" and it["name"] != "_meta.json")


def save_raw_file(period, category, filename, file_bytes):
    """Bir gelir/gider dosyasini data/{period}/{category}/{filename} olarak
    kaydeder. Dosya zaten varsa uzerine yazar."""
    url = f"{API_BASE}/contents/{RAW_DATA_DIR}/{period}/{category}/{filename}"

    sha = None
    existing = requests.get(url, headers=_headers(), timeout=15)
    if existing.status_code == 200:
        sha = existing.json()["sha"]
    elif existing.status_code not in (404,):
        _kontrol_et(existing, "Dosya kaydedilirken (mevcut dosya kontrolu)")

    content_b64 = base64.b64encode(file_bytes).decode("utf-8")
    body = {
        "message": f"Dosya arsivlendi: {period}/{category}/{filename}",
        "content": content_b64,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        body["sha"] = sha

    resp = requests.put(url, headers=_headers(), json=body, timeout=30)
    _kontrol_et(resp, "Dosya kaydedilirken")
    return resp.json()


def load_raw_file(period, category, filename):
    """data/{period}/{category}/{filename} dosyasinin icerigini bytes olarak dondurur.
    Ham (raw) Accept header'i kullanilir - boylece 1MB'dan buyuk dosyalarda da
    (GitHub Contents API'nin base64 icerik sinirlamasina takilmadan) calisir."""
    url = f"{API_BASE}/contents/{RAW_DATA_DIR}/{period}/{category}/{filename}"
    resp = requests.get(url, headers=_raw_headers(), timeout=30)
    _kontrol_et(resp, "Dosya indirilirken")
    return resp.content


def save_gider_meta(period, carrier_for_file):
    """Gider dosyalarinin hangi kargo firmasina ait oldugunu
    data/{period}/gider/_meta.json icine kaydeder. carrier_for_file:
    {"dosya_adi.xlsx": "UniUni", ...}"""
    url = f"{API_BASE}/contents/{RAW_DATA_DIR}/{period}/gider/_meta.json"

    sha = None
    existing = requests.get(url, headers=_headers(), timeout=15)
    if existing.status_code == 200:
        sha = existing.json()["sha"]
    elif existing.status_code not in (404,):
        _kontrol_et(existing, "Gider bilgisi kaydedilirken (mevcut dosya kontrolu)")

    content_str = json.dumps(carrier_for_file, ensure_ascii=False, indent=2)
    content_b64 = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
    body = {
        "message": f"Gider firma bilgisi kaydedildi: {period}",
        "content": content_b64,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        body["sha"] = sha

    resp = requests.put(url, headers=_headers(), json=body, timeout=15)
    _kontrol_et(resp, "Gider bilgisi kaydedilirken")
    return resp.json()


def load_gider_meta(period):
    """data/{period}/gider/_meta.json icerigini dict olarak dondurur.
    Yoksa bos dict doner."""
    url = f"{API_BASE}/contents/{RAW_DATA_DIR}/{period}/gider/_meta.json"
    resp = requests.get(url, headers=_headers(), timeout=15)
    if resp.status_code == 404:
        return {}
    _kontrol_et(resp, "Gider bilgisi okunurken")
    data = resp.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content)


# Bir dosyada bu kolonlardan hangisi varsa, satirlarin "kimligi" (tekillestirme
# anahtari) olarak o kullanilir - ayni kimlige sahip iki satirdan en son
# yuklenen gecerli olur. Kolon isimleri processing.py'deki CARRIER_PROFILES
# ile gelir dosyasi kolonlarindan derlenmistir.
_DEDUP_KEY_CANDIDATES = [
    "Shipment No",
    "Track Number",
    "CustomerTrackingNumberOriginal",
    "Customer Tracking Number Original",
    "Parcel Tracking No.",
    "Tracking Number",
    "Express or Ground Tracking ID",
    "Master Tracking Number",
]


def _guess_dedup_key(df):
    for col in _DEDUP_KEY_CANDIDATES:
        if col in df.columns:
            return col
    return None


def merge_and_save_raw_file(period, category, filename, new_bytes):
    """Ayni isimli dosya data/{period}/{category}/{filename} altinda zaten
    varsa, eskisiyle yeni yuklenen dosyayi birlestirir: ayni takip numarasina
    (veya Shipment No'ya) sahip satirlarda en son yuklenen veri gecerli olur,
    farkli/yeni satirlar ise eklenir - hicbir veri kaybolmaz. Dosya ilk kez
    yukleniyorsa oldugu gibi kaydedilir.

    Returns: dict(durum="yeni"|"birlestirildi", eski_satir, yeni_satir, sonuc_satir, dedup_anahtari)
    """
    url = f"{API_BASE}/contents/{RAW_DATA_DIR}/{period}/{category}/{filename}"
    existing = requests.get(url, headers=_headers(), timeout=15)

    new_df = pd.read_excel(io.BytesIO(new_bytes))

    if existing.status_code == 404:
        save_raw_file(period, category, filename, new_bytes)
        return {
            "durum": "yeni",
            "eski_satir": 0,
            "yeni_satir": len(new_df),
            "sonuc_satir": len(new_df),
            "dedup_anahtari": None,
        }
    _kontrol_et(existing, "Dosya birlestirilirken (mevcut dosya kontrolu)")

    old_content = load_raw_file(period, category, filename)
    old_df = pd.read_excel(io.BytesIO(old_content))

    combined = pd.concat([old_df, new_df], ignore_index=True)
    dedup_key = _guess_dedup_key(combined)
    if dedup_key:
        combined = combined.drop_duplicates(subset=[dedup_key], keep="last")
    else:
        combined = combined.drop_duplicates(keep="last")
    combined = combined.reset_index(drop=True)

    out_buffer = io.BytesIO()
    combined.to_excel(out_buffer, index=False)
    save_raw_file(period, category, filename, out_buffer.getvalue())

    return {
        "durum": "birlestirildi",
        "eski_satir": len(old_df),
        "yeni_satir": len(new_df),
        "sonuc_satir": len(combined),
        "dedup_anahtari": dedup_key,
    }
