"""
Gelir-gider eslestirme mantigi.
Gelir dosyasi formati sabit (WH_CUSTOMER_SHIPMENT_LIST).
Gider dosyalari kargo firmasina gore degisir; her firma icin bir
CARRIER_PROFILES girdisi tanimlanir. Yeni bir kargo firmasi eklemek
icin sadece bu sozluge yeni bir profil eklemek yeterli.
"""

import pandas as pd

from fx import TARGET_CURRENCY, get_rate

NO_TRACKING_VALUES = {"No Tracking Number", "Customer Label", "nan", "", "None"}

# Her kargo firmasi icin: takip numarasi kolonu ve ucret kolonu (veya kolonlari).
# currency_col / date_col verilirse, ucret otomatik olarak USD'ye cevrilir
# (her satir kendi tarihindeki gunluk kur ile).
CARRIER_PROFILES = {
    "Asendia": {
        "tracking_col": "CustomerTrackingNumberOriginal",
        "charge_col": "TOTALCHARGE",
        "currency_col": "CurrencyType",
        "date_col": "JobDate",
        "invoice_col": "Invoice Number",
    },
    "UniUni": {
        "tracking_col": "Parcel Tracking No.",
        "charge_col": "Shipping Fee",
        "currency_col": "Charge Currency",
        "date_col": "Invoice Date",
        "invoice_col": "Invoice Number",
    },
    "UPS": {
        "tracking_col": "Tracking Number",
        "charge_col": "Net Amount Due",
        "date_col": "Invoice Date",
        "invoice_col": "Invoice Number",
        "charge_is_money_text": True,
        "tax_category_col": "Shipping System / Adjustment",
        "tax_category_values": ["US Customs Duties", "Government Charges", "Brokerage Charges"],
    },
}

# ByeLabel dosyasi (shipments-...xlsx) tek tabloda birden fazla firma icerir.
# Carrier & Service kolonundaki degere gore filtrelenip ayri profil olarak eklenir.
# charge_col = kargo bedeli, tax_col = vergi/gumruk (ayri ayri hesaplanir, sonra toplanir).
_BYELABEL_BASE = {
    "tracking_col": "Master Tracking Number",
    "charge_col": "Cost",
    "tax_col": "Tax",
    "date_col": "Create Date",
    "service_filter_col": "Carrier & Service",
}

CARRIER_PROFILES.update(
    {
        "ePost Global": {**_BYELABEL_BASE, "service_filter_contains": "ePost Global"},
        "DHL": {**_BYELABEL_BASE, "service_filter_contains": "DHL"},
        "intelcom": {**_BYELABEL_BASE, "service_filter_contains": "Intelcom"},
        "APC": {**_BYELABEL_BASE, "service_filter_contains": "APC"},
        "USPS": {**_BYELABEL_BASE, "service_filter_contains": "USPS"},
        "Evri": {**_BYELABEL_BASE, "service_filter_contains": "Evri"},
        "Purolator": {**_BYELABEL_BASE, "service_filter_contains": "Purolator"},
        "FedEx (ByeLabel)": {**_BYELABEL_BASE, "service_filter_contains": "FedEx"},
        "UPS (ByeLabel)": {**_BYELABEL_BASE, "service_filter_contains": "UPS"},
    }
)


def _parse_money_text(value):
    """'$74.69', '-$0.67', '($12.34)' gibi metinleri sayiya cevirir."""
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    negative = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.replace("$", "").replace(",", "").replace("(", "").replace(")", "").replace("-", "").strip()
    if not s:
        return None
    num = float(s)
    return -num if negative else num


def load_income_file(file_obj):
    """Gelir dosyasini okur, ihtiyac duyulan kolonlari secer."""
    df = pd.read_excel(file_obj)

    required = ["Shipment No", "Track Number", "Carrier Name", "Invoice Amount", "Status", "Added Date"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Gelir dosyasinda eksik kolon(lar): {', '.join(missing)}")

    out = df[required].copy()
    out["TrackingKey"] = out["Track Number"].astype(str).str.strip()
    out["Takip_Var_Mi"] = ~out["TrackingKey"].isin(NO_TRACKING_VALUES)
    return out


def load_cost_file(file_obj, carrier_name):
    """Bir kargo firmasinin gider dosyasini okur, takip numarasina gore gruplar.

    Kargo bedeli (charge_col) ve vergi/gumruk (tax_col veya tax_category_col
    ile belirlenen) ayri ayri toplanir, sonra "Gider" olarak birlestirilir.

    Takip numarasi OLMAYAN vergi/komisyon satirlari (orn. UPS'te Brokerage
    Charges, Government Charges) belirli bir pakete baglanamaz - bunlar
    "genel gider" olarak ayrica dondurulur, pakete dagitilmaz.

    Ayni takip numarasi birden fazla satirda gecerse (tekrar/surcharge satiri vs.)
    ucretler toplanir - hicbir satir atilmaz.

    Para birimi USD disindaysa, her satir kendi tarihindeki gunluk kur ile
    otomatik olarak USD'ye cevrilir (Frankfurter API).

    Returns: (grouped_df, currency_warning, genel_gider_tutari)
    """
    if carrier_name not in CARRIER_PROFILES:
        raise ValueError(f"Taninmayan kargo firmasi: {carrier_name}")

    empty_cols = ["TrackingKey", "Gider_Kargo", "Gider_Tax", "Gider", "Kargo Firmasi", "Satir Sayisi"]

    profile = CARRIER_PROFILES[carrier_name]
    df = pd.read_excel(file_obj)

    track_col = profile["tracking_col"]
    charge_col = profile["charge_col"]
    tax_col = profile.get("tax_col")
    currency_col = profile.get("currency_col")
    date_col = profile.get("date_col")
    tax_category_col = profile.get("tax_category_col")
    tax_category_values = profile.get("tax_category_values")

    filter_col = profile.get("service_filter_col")
    filter_contains = profile.get("service_filter_contains")
    if filter_col:
        if filter_col not in df.columns:
            raise ValueError(f"{carrier_name} dosyasinda '{filter_col}' kolonu bulunamadi")
        df = df[df[filter_col].astype(str).str.contains(filter_contains, case=False, na=False)].copy()
        if df.empty:
            return pd.DataFrame(columns=empty_cols), None, 0.0

    needed_cols = [track_col, charge_col] + ([tax_col] if tax_col else [])
    for col in needed_cols:
        if col not in df.columns:
            raise ValueError(f"{carrier_name} dosyasinda '{col}' kolonu bulunamadi")

    if profile.get("charge_is_money_text"):
        df[charge_col] = df[charge_col].apply(_parse_money_text)
        if tax_col:
            df[tax_col] = df[tax_col].apply(_parse_money_text)

    if tax_category_col and tax_category_col in df.columns:
        is_tax = df[tax_category_col].isin(tax_category_values)
    else:
        is_tax = pd.Series(False, index=df.index)

    # Vergi kategorisinde olup takip numarasi OLMAYAN satirlar -> genel gider.
    # Belirli bir pakete baglanamadiklari icin eslestirmeye dahil edilmezler.
    no_tracking = df[track_col].isna()
    overhead_mask = is_tax & no_tracking
    genel_gider = float(df.loc[overhead_mask, charge_col].fillna(0).sum())

    df = df[~overhead_mask].copy()
    df = df.dropna(subset=[track_col]).copy()
    df["TrackingKey"] = df[track_col].astype(str).str.strip()

    if profile.get("charge_is_money_text"):
        df = df.dropna(subset=[charge_col])

    if tax_category_col and tax_category_col in df.columns:
        # Ayni tutar kolonu (charge_col), baska bir kolonun degerine gore
        # kargo / vergi olarak ikiye bolunur (orn. UPS'te "Brokerage Charges" gibi
        # satirlar Net Amount Due icinde ama vergi sayilmasi gerekiyor).
        is_tax = df[tax_category_col].isin(tax_category_values)
        df["_kargo_raw"] = df[charge_col].where(~is_tax, 0.0)
        df["_tax_raw"] = df[charge_col].where(is_tax, 0.0)
    elif tax_col:
        df["_kargo_raw"] = df[charge_col]
        df["_tax_raw"] = df[tax_col].fillna(0)
    else:
        df["_kargo_raw"] = df[charge_col]
        df["_tax_raw"] = 0.0

    currency_warning = None
    fx_failed_count = 0

    needs_conversion = (
        currency_col
        and currency_col in df.columns
        and df[currency_col].dropna().ne(TARGET_CURRENCY).any()
    )

    if needs_conversion:
        if date_col and date_col in df.columns:
            df["_date_str"] = pd.to_datetime(df[date_col], errors="coerce", format="mixed").dt.strftime("%Y-%m-%d")
        else:
            df["_date_str"] = None
        df["_date_str"] = df["_date_str"].fillna("latest")

        def convert(row):
            nonlocal fx_failed_count
            cur = row[currency_col]
            if pd.isna(cur) or cur == TARGET_CURRENCY:
                return row["_kargo_raw"], row["_tax_raw"]
            rate = get_rate(cur, row["_date_str"])
            if rate is None:
                fx_failed_count += 1
                return None, None
            return row["_kargo_raw"] * rate, row["_tax_raw"] * rate

        converted = df.apply(convert, axis=1, result_type="expand")
        df["Gider_Kargo"] = converted[0]
        df["Gider_Tax"] = converted[1]

        currencies = [c for c in df[currency_col].dropna().unique() if c != TARGET_CURRENCY]
        currency_warning = f"{carrier_name}: {', '.join(currencies)} -> USD gunluk kur ile cevrildi."
    else:
        df["Gider_Kargo"] = df["_kargo_raw"]
        df["Gider_Tax"] = df["_tax_raw"]

    if fx_failed_count:
        msg = f"UYARI: {carrier_name} icin {fx_failed_count} satirda doviz kuru alinamadi, bu satirlar dislandi."
        currency_warning = f"{currency_warning} {msg}" if currency_warning else msg

    df = df.dropna(subset=["Gider_Kargo"])

    grouped = df.groupby("TrackingKey", as_index=False).agg(
        Gider_Kargo=("Gider_Kargo", "sum"),
        Gider_Tax=("Gider_Tax", "sum"),
    )
    grouped["Gider"] = grouped["Gider_Kargo"] + grouped["Gider_Tax"]
    grouped["Kargo Firmasi"] = carrier_name
    grouped["Satir Sayisi"] = df.groupby("TrackingKey").size().values

    return grouped, currency_warning, genel_gider


def build_report(income_df, cost_dfs):
    """Gelir ve (bir veya daha fazla kargo firmasindan) gider verisini birlestirir."""
    if cost_dfs:
        cost_all = pd.concat(cost_dfs, ignore_index=True)
        cost_summary = (
            cost_all.groupby("TrackingKey", as_index=False)
            .agg(
                Gider_Kargo=("Gider_Kargo", "sum"),
                Gider_Tax=("Gider_Tax", "sum"),
                Gider=("Gider", "sum"),
                Kargo_Firmalari=("Kargo Firmasi", lambda x: ", ".join(sorted(set(x)))),
            )
        )
    else:
        cost_summary = pd.DataFrame(columns=["TrackingKey", "Gider_Kargo", "Gider_Tax", "Gider", "Kargo_Firmalari"])

    merged = income_df.merge(cost_summary, on="TrackingKey", how="left")

    def status(row):
        if not row["Takip_Var_Mi"]:
            return "Takip no yok"
        if pd.isna(row["Gider"]):
            return "Gider bulunamadi"
        return "Eslesti"

    merged["Durum"] = merged.apply(status, axis=1)
    merged["Kar"] = merged["Invoice Amount"] - merged["Gider"]

    income_keys = set(income_df["TrackingKey"])
    unmatched_cost = cost_summary[~cost_summary["TrackingKey"].isin(income_keys)].copy()

    return merged, unmatched_cost


def summarize(merged, genel_gider=0.0):
    """Ozet metrikler.

    genel_gider: pakete baglanamayan vergi/komisyon gibi gider toplami
    (orn. UPS Brokerage/Government Charges). Pakete dagitilmaz, sadece
    net kardan ayrica dusulur.
    """
    matched = merged[merged["Durum"] == "Eslesti"]
    toplam_kar = matched["Kar"].sum()
    return {
        "toplam_gelir": merged["Invoice Amount"].sum(),
        "toplam_gider_kargo": matched["Gider_Kargo"].sum(),
        "toplam_gider_tax": matched["Gider_Tax"].sum(),
        "toplam_gider_eslesen": matched["Gider"].sum(),
        "toplam_kar": toplam_kar,
        "genel_gider": genel_gider,
        "net_kar": toplam_kar - genel_gider,
        "toplam_gonderi": len(merged),
        "eslesen_sayisi": len(matched),
        "takip_no_yok_sayisi": (merged["Durum"] == "Takip no yok").sum(),
        "gider_bulunamadi_sayisi": (merged["Durum"] == "Gider bulunamadi").sum(),
    }
