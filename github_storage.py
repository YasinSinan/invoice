"""
Gecmis analizleri GitHub reposundaki bir klasore (reports/) JSON olarak
kaydetmek ve geri okumak icin yardimci fonksiyonlar.

GitHub REST API kullanir, bir Personal Access Token gerektirir. Bu token
Streamlit Cloud'da "Secrets" bolumune GITHUB_TOKEN olarak eklenmelidir.
Yerel calistirmada ise .streamlit/secrets.toml dosyasina eklenir (bu dosya
.gitignore'da oldugu icin GitHub'a yuklenmez).
"""

import base64
import json

import numpy as np
import requests
import streamlit as st

GITHUB_OWNER = "YasinSinan"
GITHUB_REPO = "invoice"
GITHUB_BRANCH = "main"
REPORTS_DIR = "reports"
API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"


class GithubStorageError(Exception):
    pass


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
        resp.raise_for_status()
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
    resp.raise_for_status()
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
        existing.raise_for_status()

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
    resp.raise_for_status()
    return resp.json()


def delete_report(period):
    """Belirli bir donemin kayitli raporunu siler."""
    url = f"{API_BASE}/contents/{REPORTS_DIR}/{period}.json"
    existing = requests.get(url, headers=_headers(), timeout=15)
    existing.raise_for_status()
    sha = existing.json()["sha"]

    body = {
        "message": f"Rapor silindi: {period}",
        "sha": sha,
        "branch": GITHUB_BRANCH,
    }
    resp = requests.delete(url, headers=_headers(), json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()
