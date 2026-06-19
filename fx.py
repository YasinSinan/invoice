"""
Doviz kuru cevirme - frankfurter.app uzerinden (ucretsiz, API key gerektirmez,
Avrupa Merkez Bankasi referans kurlarina dayanir).

Her tutar, kendi islem tarihindeki gunluk kur ile USD'ye cevrilir.
Aym (kur, tarih) ciftleri icin tekrar API cagrisi yapilmaz (cache).
"""

import requests

TARGET_CURRENCY = "USD"
_rate_cache = {}


def get_rate(from_currency, date_str):
    """from_currency -> USD kurunu dondurur. date_str format: YYYY-MM-DD veya 'latest'.
    API'den alinamazsa None doner; cagiran taraf bunu ele almalidir.
    """
    if from_currency == TARGET_CURRENCY:
        return 1.0

    key = (from_currency, date_str)
    if key in _rate_cache:
        return _rate_cache[key]

    rate = _fetch_rate(from_currency, date_str)
    if rate is None and date_str != "latest":
        rate = _fetch_rate(from_currency, "latest")

    _rate_cache[key] = rate
    return rate


def _fetch_rate(from_currency, date_str):
    try:
        url = f"https://api.frankfurter.app/{date_str}"
        resp = requests.get(url, params={"from": from_currency, "to": TARGET_CURRENCY}, timeout=10)
        resp.raise_for_status()
        return resp.json()["rates"][TARGET_CURRENCY]
    except Exception:
        return None


def clear_cache():
    _rate_cache.clear()
