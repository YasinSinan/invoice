"""
Gelir-gider eslestirme mantigi.
Gelir dosyasi formati sabit (WH_CUSTOMER_SHIPMENT_LIST).
Gider dosyalari kargo firmasina gore degisir; her firma icin bir
CARRIER_PROFILES girdisi tanimlanir. Yeni bir kargo firmasi eklemek
icin sadece bu sozluge yeni bir profil eklemek yeterli.
"""

import pandas as pd

NO_TRACKING_VALUES = {"No Tracking Number", "Customer Label", "nan", "", "None"}

# Her kargo firmasi icin: takip numarasi kolonu ve ucret kolonu (veya kolonlari)
CARRIER_PROFILES = {
    "Asendia": {
        "tracking_col": "CustomerTrackingNumberOriginal",
        "charge_col": "TOTALCHARGE",
        "currency_col": "CurrencyType",
        "date_col": "JobDate",
        "invoice_col": "Invoice Number",
    },
}


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

    Ayni takip numarasi birden fazla satirda gecerse (tekrar/surcharge satiri vs.)
    ucretler toplanir - hicbir satir atilmaz.
    """
    if carrier_name not in CARRIER_PROFILES:
        raise ValueError(f"Taninmayan kargo firmasi: {carrier_name}")

    profile = CARRIER_PROFILES[carrier_name]
    df = pd.read_excel(file_obj)

    track_col = profile["tracking_col"]
    charge_col = profile["charge_col"]
    for col in (track_col, charge_col):
        if col not in df.columns:
            raise ValueError(f"{carrier_name} dosyasinda '{col}' kolonu bulunamadi")

    df = df.dropna(subset=[track_col]).copy()
    df["TrackingKey"] = df[track_col].astype(str).str.strip()

    currency_col = profile.get("currency_col")
    currency_warning = None
    if currency_col and currency_col in df.columns:
        currencies = df[currency_col].dropna().unique()
        if len(currencies) > 1 or (len(currencies) == 1 and currencies[0] != "USD"):
            currency_warning = f"{carrier_name} dosyasinda USD disinda para birimi bulundu: {list(currencies)}"

    grouped = df.groupby("TrackingKey", as_index=False)[charge_col].sum()
    grouped = grouped.rename(columns={charge_col: "Gider"})
    grouped["Kargo Firmasi"] = carrier_name
    grouped["Satir Sayisi"] = df.groupby("TrackingKey").size().values

    return grouped, currency_warning


def build_report(income_df, cost_dfs):
    """Gelir ve (bir veya daha fazla kargo firmasindan) gider verisini birlestirir."""
    if cost_dfs:
        cost_all = pd.concat(cost_dfs, ignore_index=True)
        cost_summary = (
            cost_all.groupby("TrackingKey", as_index=False)
            .agg(
                Gider=("Gider", "sum"),
                Kargo_Firmalari=("Kargo Firmasi", lambda x: ", ".join(sorted(set(x)))),
            )
        )
    else:
        cost_summary = pd.DataFrame(columns=["TrackingKey", "Gider", "Kargo_Firmalari"])

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


def summarize(merged):
    """Ozet metrikler."""
    matched = merged[merged["Durum"] == "Eslesti"]
    return {
        "toplam_gelir": merged["Invoice Amount"].sum(),
        "toplam_gider_eslesen": matched["Gider"].sum(),
        "toplam_kar": matched["Kar"].sum(),
        "toplam_gonderi": len(merged),
        "eslesen_sayisi": len(matched),
        "takip_no_yok_sayisi": (merged["Durum"] == "Takip no yok").sum(),
        "gider_bulunamadi_sayisi": (merged["Durum"] == "Gider bulunamadi").sum(),
    }
