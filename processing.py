"""
Gelir-gider eslestirme mantigi.
Gelir dosyasi formati sabit (WH_CUSTOMER_SHIPMENT_LIST).
Gider dosyalari kargo firmasina gore degisir; her firma icin bir
CARRIER_PROFILES girdisi tanimlanir. Yeni bir kargo firmasi eklemek
icin sadece bu sozluge yeni bir profil eklemek yeterli.
"""

import re

import pandas as pd

from fx import TARGET_CURRENCY, get_rate

NO_TRACKING_VALUES = {"No Tracking Number", "Customer Label", "nan", "", "None"}

# Kullaniciya arayuzde gosterilen kargo firmalari (her biri kendi dosya formatina sahip).
# currency_col / date_col verilirse, ucret otomatik olarak USD'ye cevrilir
# (her satir kendi tarihindeki gunluk kur ile).
CARRIER_PROFILES = {
    "Asendia": {
        # Asendia farkli zamanlarda farkli kolon adlandirmasi kullanabiliyor
        # (orn. "CustomerTrackingNumberOriginal" vs "Customer Tracking Number
        # Original"). Liste olarak verilen alanlar, dosyada hangisi varsa o
        # kullanilir.
        "tracking_col": ["CustomerTrackingNumberOriginal", "Customer Tracking Number Original"],
        "charge_col": ["TOTALCHARGE", "total charge", "Total Charge"],
        "currency_col": ["CurrencyType", "Currency Type"],
        "date_col": ["JobDate", "Job Date"],
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
        "tax_category_values": ["US Customs Duties", "Government Charges", "Brokerage Charges", "Import Shipment Detail"],
    },
    "Asendia - Vergi/Gumruk": {
        # Asendia'nin ayri Duty & Tax raporu. Sadece "2026" sayfasi islenir;
        # "2025" sayfasinda Customer Tracking Number Original kolonu yok ve
        # gelir penceresiyle (2026 Nisan-Mayis) tarihsel ortusmesi de yok.
        "tracking_col": "Customer Tracking Number Original",
        "charge_col": "Total Charge",
        "date_col": "Job Date",
        "invoice_col": "Invoice Number",
        "sheet_name": "2026",
        "all_tax": True,
    },
    "FedEx": {
        # FedEx'in detayli fatura raporu: her gonderi tek satir, ama her satirda
        # 51 ayri ucret kalemi (Description/Amount cifti) yan yana kolon olarak
        # gelir. Her cift kendi aciklamasina gore Kargo/Vergi olarak ayrilir.
        "tracking_col": "Express or Ground Tracking ID",
        "charge_col": "Net Charge Amount",
        "date_col": "Invoice Date",
        "invoice_col": "Invoice Number",
        "wide_charge_pairs": True,
        "base_charge_col": "Transportation Charge Amount",
        "desc_col_prefix": "Tracking ID Charge Description",
        "amount_col_prefix": "Tracking ID Charge Amount",
        "max_pairs": 51,
        "tax_category_values": [
            "Original VAT",
            "Customs Duty",
            "Canada GST",
            "Canada HST",
            "Clearance Entry Fee",
            "US Inbound Processing Fee",
            "Other Government Agency Fee",
            "Rebill Duty",
            "Additional Tax Admin",
            "Broker Document Transfer Fee",
            "Additional Entry Line Items Fee",
        ],
    },
}

# ByeLabel dosyasi (shipments-...xlsx) tek tabloda birden fazla firma icerir.
# Carrier & Service kolonundaki degere gore filtrelenip ayri profil olarak tanimlanir.
# Bu profiller kullaniciya TEK TEK gosterilmez - arayuzde sadece BYELABEL_GROUP_LABEL
# secilir, load_byelabel_group() hepsini otomatik calistirir.
_BYELABEL_BASE = {
    "tracking_col": "Master Tracking Number",
    "charge_col": "Cost",
    "tax_col": "Tax",
    "date_col": "Create Date",
    "service_filter_col": "Carrier & Service",
}

BYELABEL_SUB_PROFILES = {
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

BYELABEL_GROUP_LABEL = "ByeLabel (Tum Firmalar)"

# load_cost_file'in carrier_name'e gore profil bulabilmesi icin birlestirilmis sozluk.
_ALL_PROFILES = {**CARRIER_PROFILES, **BYELABEL_SUB_PROFILES}

# Ayni firmanin farkli yazimlarini (orn. "FedEx", "FedEx BL", "FEDEX BL",
# "FedEx (ByeLabel)") tek bir isim altinda birlestirmek icin. Anahtar: aranacak
# alt-string (kucuk harfle, bosluk/alt cizgi/tire onemsiz), deger: gosterilecek
# tek/kanonik isim. Yeni bir firma icin birlestirme istenirse buraya bir satir
# eklemek yeterli.
CARRIER_NAME_ALIASES = {
    "asendia": "Asendia",
    "epost": "ePost Global",
    "fedex": "FedEx",
    "intelcom": "Intelcom",
    "purolator": "Purolator",
    "ups": "UPS",
}


def _simplify(s):
    """Kucuk harfe cevirir ve harf/sayi olmayan karakterleri (bosluk, alt cizgi,
    tire vb.) kaldirir - boylece 'E_POST', 'ePost Global', 'e-post' gibi farkli
    yazimlar karsilastirilabilir hale gelir."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _normalize_carrier_name(name):
    """CARRIER_NAME_ALIASES'e gore farkli yazimlari tek isim altinda birlestirir.
    Eslesme yoksa orijinal ismi degistirmeden dondurur."""
    if pd.isna(name):
        return name
    simplified = _simplify(name)
    for key, canonical in CARRIER_NAME_ALIASES.items():
        if _simplify(key) in simplified:
            return canonical
    return name


# Manuel firma-bazinda gider girisinde (orn. "US-CA arasi kargo ucreti")
# secilebilecek bilinen kargo firmalari.
KNOWN_CARRIERS = [
    "Asendia",
    "UniUni",
    "UPS",
    "FedEx",
    "ePost Global",
    "DHL",
    "intelcom",
    "APC",
    "USPS",
    "Evri",
    "Purolator",
]


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


def _resolve_col(df, name_or_list, carrier_name, required=True):
    """Profildeki bir alan adi tek string veya alternatif isimlerin listesi
    olabilir (orn. Asendia zaman zaman "JobDate", zaman zaman "Job Date"
    kullanabiliyor). Dosyada hangisi varsa onu dondurur.

    required=False ise ve hicbiri bulunamazsa None doner (hata firlatmaz) -
    opsiyonel alanlar (orn. currency_col, date_col) icin kullanilir.
    """
    candidates = name_or_list if isinstance(name_or_list, list) else [name_or_list]
    for c in candidates:
        if c in df.columns:
            return c
    if not required:
        return None
    secenekler = ", ".join(f"'{c}'" for c in candidates)
    raise ValueError(f"{carrier_name} dosyasinda beklenen kolon(lar) bulunamadi: {secenekler}")


def load_income_file(file_obj, only_paid=True, exclude_unassigned_carrier=True):
    """Gelir dosyasini okur, ihtiyac duyulan kolonlari secer.

    only_paid=True ise sadece Status="Paid" olan gonderiler dahil edilir
    (User Cancelled, New Shipment, Payment Waiting vb. disarida tutulur).

    exclude_unassigned_carrier=True ise Carrier Name (kargo firmasi) bos/atanmamis
    olan gonderiler tamamen disarida tutulur (analizin hicbir yerinde gorunmezler).
    """
    df = pd.read_excel(file_obj)

    required = [
        "Shipment No",
        "Track Number",
        "Carrier Name",
        "Invoice Amount",
        "Status",
        "Added Date",
        "Receiver Country",
        "User No",
        "User Name",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Gelir dosyasinda eksik kolon(lar): {', '.join(missing)}")

    out = df[required].copy()
    if only_paid:
        out = out[out["Status"] == "Paid"].reset_index(drop=True)
    if exclude_unassigned_carrier:
        bos = out["Carrier Name"].isna() | (out["Carrier Name"].astype(str).str.strip() == "")
        out = out[~bos].reset_index(drop=True)
    out["Carrier Name"] = out["Carrier Name"].apply(_normalize_carrier_name)
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

    Returns: (grouped_df, currency_warning, genel_gider_tutari, breakdown_df)
    breakdown_df: hangi kategori/sutunun Kargo / Vergi / Genel Gider olarak
    siniflandirildigini ve ne kadar tutar tasidigini gosterir (seffaflik icin).
    """
    if carrier_name not in _ALL_PROFILES:
        raise ValueError(f"Taninmayan kargo firmasi: {carrier_name}")

    empty_cols = ["TrackingKey", "Gider_Kargo", "Gider_Tax", "Gider_Kalemleri", "Gider", "Kargo Firmasi", "Satir Sayisi"]
    empty_breakdown = pd.DataFrame(columns=["Kargo Firmasi", "Kategori/Sutun", "Kaynak Sutun", "Siniflandirma", "Tutar"])

    profile = _ALL_PROFILES[carrier_name]
    display_name = _normalize_carrier_name(carrier_name)
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    df = pd.read_excel(file_obj, sheet_name=profile.get("sheet_name", 0))

    track_col = _resolve_col(df, profile["tracking_col"], carrier_name)
    charge_col = _resolve_col(df, profile["charge_col"], carrier_name)
    tax_col = _resolve_col(df, profile["tax_col"], carrier_name, required=False) if profile.get("tax_col") else None
    currency_col = (
        _resolve_col(df, profile["currency_col"], carrier_name, required=False)
        if profile.get("currency_col")
        else None
    )
    date_col = _resolve_col(df, profile["date_col"], carrier_name, required=False) if profile.get("date_col") else None
    tax_category_col = profile.get("tax_category_col")
    tax_category_values = profile.get("tax_category_values")

    filter_col = profile.get("service_filter_col")
    filter_contains = profile.get("service_filter_contains")
    if filter_col:
        if filter_col not in df.columns:
            raise ValueError(f"{carrier_name} dosyasinda '{filter_col}' kolonu bulunamadi")
        df = df[df[filter_col].astype(str).str.contains(filter_contains, case=False, na=False)].copy()
        if df.empty:
            return pd.DataFrame(columns=empty_cols), None, 0.0, empty_breakdown

    # Bazi firmalar (orn. FedEx) her gonderi icin bircok ayri ucret kalemini
    # ayni satirda yan yana kolonlar olarak verir (Description/Amount cifti
    # tekrarlanir). Bu durumda her cift kendi aciklamasina gore Kargo/Vergi
    # olarak siniflandirilip satir bazinda toplanir.
    wide_breakdown_rows = []
    if profile.get("wide_charge_pairs"):
        desc_prefix = profile["desc_col_prefix"]
        amount_prefix = profile["amount_col_prefix"]
        wide_tax_values = set(profile.get("tax_category_values", []))
        max_pairs = profile.get("max_pairs", 60)

        indices = [""] + [f".{i}" for i in range(1, max_pairs)]
        pairs = [
            (f"{desc_prefix}{idx}", f"{amount_prefix}{idx}")
            for idx in indices
            if f"{desc_prefix}{idx}" in df.columns and f"{amount_prefix}{idx}" in df.columns
        ]
        if not pairs:
            raise ValueError(f"{carrier_name} dosyasinda '{desc_prefix}' / '{amount_prefix}' kolonlari bulunamadi")

        kargo_raw = pd.Series(0.0, index=df.index)
        tax_raw = pd.Series(0.0, index=df.index)
        cat_totals = {}
        cat_kaynak_sutun = {}
        item_desc_cols = []

        base_col = profile.get("base_charge_col")
        if base_col and base_col in df.columns:
            base_amt = df[base_col].apply(_parse_money_text).fillna(0.0)
            kargo_raw = kargo_raw + base_amt
            cat_totals[base_col] = cat_totals.get(base_col, 0.0) + float(base_amt.sum())
            cat_kaynak_sutun[base_col] = base_col
            base_formatted = (base_col + ": $" + base_amt.round(2).astype(str)).where(base_amt != 0)
            item_desc_cols.append(base_formatted)

        for desc_col, amt_col in pairs:
            amt = df[amt_col].apply(_parse_money_text).fillna(0.0)
            desc = df[desc_col]
            is_tax_line = desc.isin(wide_tax_values)
            kargo_raw = kargo_raw + amt.where(~is_tax_line, 0.0)
            tax_raw = tax_raw + amt.where(is_tax_line, 0.0)

            formatted = (desc.astype(str) + ": $" + amt.round(2).astype(str)).where(amt != 0)
            item_desc_cols.append(formatted)

            for d, total in amt.groupby(desc).sum().items():
                if pd.isna(d):
                    continue
                cat_totals[d] = cat_totals.get(d, 0.0) + float(total)
                cat_kaynak_sutun[d] = desc_prefix

        item_desc_df = pd.concat(item_desc_cols, axis=1).copy()
        df = df.copy()
        df["_item_desc"] = item_desc_df.apply(lambda row: "; ".join(row.dropna()), axis=1)

        df = pd.concat(
            [df, pd.DataFrame({"_wide_kargo": kargo_raw, "_wide_tax": tax_raw, "_wide_total": kargo_raw + tax_raw})],
            axis=1,
        )
        charge_col = "_wide_total"

        for d, total in cat_totals.items():
            label = "Vergi" if d in wide_tax_values else "Kargo"
            wide_breakdown_rows.append((display_name, d, cat_kaynak_sutun.get(d, ""), label, total))

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

    breakdown_rows = []
    if tax_category_col and tax_category_col in df.columns:
        overhead_by_cat = df.loc[overhead_mask].groupby(tax_category_col)[charge_col].sum()
        for cat, total in overhead_by_cat.items():
            breakdown_rows.append((display_name, cat, tax_category_col, "Genel Gider (pakete baglanamiyor)", float(total)))

    df = df[~overhead_mask].copy()
    df = df.dropna(subset=[track_col]).copy()
    df["TrackingKey"] = df[track_col].astype(str).str.strip()

    if profile.get("charge_is_money_text"):
        df = df.dropna(subset=[charge_col])

    if "_wide_kargo" in df.columns:
        # Satir bazinda zaten Kargo/Vergi olarak hesaplanmis (wide_charge_pairs).
        # "_item_desc" da ayni adimda zaten olusturuldu.
        df["_kargo_raw"] = df["_wide_kargo"]
        df["_tax_raw"] = df["_wide_tax"]
        breakdown_rows.extend(wide_breakdown_rows)
    elif profile.get("all_tax"):
        # Tum dosya zaten bir vergi/gumruk dosyasi (orn. Asendia Duty & Tax raporu) -
        # charge_col'un tamami Vergi sayilir, Kargo payi yok.
        df["_kargo_raw"] = 0.0
        df["_tax_raw"] = df[charge_col]
        df["_item_desc"] = display_name + ": $" + df[charge_col].round(2).astype(str)
        breakdown_rows.append((display_name, charge_col, charge_col, "Vergi", float(df[charge_col].sum())))
    elif tax_category_col and tax_category_col in df.columns:
        # Ayni tutar kolonu (charge_col), baska bir kolonun degerine gore
        # kargo / vergi olarak ikiye bolunur (orn. UPS'te "Brokerage Charges" gibi
        # satirlar Net Amount Due icinde ama vergi sayilmasi gerekiyor).
        is_tax = df[tax_category_col].isin(tax_category_values)
        df["_kargo_raw"] = df[charge_col].where(~is_tax, 0.0)
        df["_tax_raw"] = df[charge_col].where(is_tax, 0.0)
        df["_item_desc"] = (
            df[tax_category_col].astype(str) + ": $" + df[charge_col].round(2).astype(str)
        ).where(df[charge_col] != 0)

        cat_totals = df.groupby(tax_category_col)[charge_col].sum()
        for cat, total in cat_totals.items():
            label = "Vergi" if cat in tax_category_values else "Kargo"
            breakdown_rows.append((display_name, cat, tax_category_col, label, float(total)))
    elif tax_col:
        df["_kargo_raw"] = df[charge_col]
        df["_tax_raw"] = df[tax_col].fillna(0)
        kargo_part = (charge_col + ": $" + df[charge_col].round(2).astype(str)).where(df[charge_col] != 0)
        tax_part = (tax_col + ": $" + df[tax_col].fillna(0).round(2).astype(str)).where(df[tax_col].fillna(0) != 0)
        df["_item_desc"] = pd.concat([kargo_part, tax_part], axis=1).apply(lambda row: "; ".join(row.dropna()), axis=1)
        breakdown_rows.append((display_name, charge_col, charge_col, "Kargo", float(df[charge_col].sum())))
        breakdown_rows.append((display_name, tax_col, tax_col, "Vergi", float(df[tax_col].fillna(0).sum())))
    else:
        df["_kargo_raw"] = df[charge_col]
        df["_tax_raw"] = 0.0
        df["_item_desc"] = display_name + ": $" + df[charge_col].round(2).astype(str)
        breakdown_rows.append((display_name, charge_col, charge_col, "Kargo", float(df[charge_col].sum())))

    breakdown_df = pd.DataFrame(
        breakdown_rows, columns=["Kargo Firmasi", "Kategori/Sutun", "Kaynak Sutun", "Siniflandirma", "Tutar"]
    )

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
        Gider_Kalemleri=("_item_desc", lambda x: "; ".join(x.dropna())),
    )
    grouped["Gider"] = grouped["Gider_Kargo"] + grouped["Gider_Tax"]
    grouped["Kargo Firmasi"] = display_name
    grouped["Satir Sayisi"] = df.groupby("TrackingKey").size().values

    return grouped, currency_warning, genel_gider, breakdown_df


def load_byelabel_group(file_obj):
    """ByeLabel dosyasini (shipments-...xlsx) tek seferde yukler, icindeki
    butun firmalari (ePost Global, DHL, intelcom, APC, USPS, Evri, Purolator,
    FedEx, UPS) otomatik olarak ayri ayri isler.

    Kullaniciya arayuzde tek bir secenek ("ByeLabel - Tum Firmalar") gosterilir,
    ama sonuctaki tablolarda her firma kendi adiyla (orn. "DHL", "ePost Global")
    ayri ayri gorunur - cunku her biri kendi profiliyle load_cost_file()
    uzerinden ayri ayri islenir.

    Returns: (cost_dfs, warnings, toplam_genel_gider, breakdown_dfs)
    """
    cost_dfs = []
    warnings = []
    toplam_genel_gider = 0.0
    breakdown_dfs = []

    for sub_carrier in BYELABEL_SUB_PROFILES:
        grouped, warning, genel_gider, breakdown_df = load_cost_file(file_obj, sub_carrier)
        if not grouped.empty:
            cost_dfs.append(grouped)
        if warning:
            warnings.append(warning)
        toplam_genel_gider += genel_gider
        if not breakdown_df.empty:
            breakdown_dfs.append(breakdown_df)

    return cost_dfs, warnings, toplam_genel_gider, breakdown_dfs


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
                Gider_Kalemleri=("Gider_Kalemleri", lambda x: "; ".join(v for v in x if v)),
                Kargo_Firmalari=("Kargo Firmasi", lambda x: ", ".join(sorted(set(x)))),
            )
        )
    else:
        cost_summary = pd.DataFrame(
            columns=["TrackingKey", "Gider_Kargo", "Gider_Tax", "Gider", "Gider_Kalemleri", "Kargo_Firmalari"]
        )

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


def summarize(merged, genel_gider=0.0, manuel_gelir=0.0):
    """Ozet metrikler.

    genel_gider: pakete baglanamayan vergi/komisyon + manuel gider toplami
    (orn. UPS Brokerage/Government Charges, depo kirasi). Pakete dagitilmaz,
    net kardan dusulur.
    manuel_gelir: pakete baglanmayan, elle girilen gelir toplami. Net kara
    eklenir.
    """
    matched = merged[merged["Durum"] == "Eslesti"]
    toplam_kar = matched["Kar"].sum()
    toplam_gelir = merged["Invoice Amount"].sum()
    net_kar = toplam_kar - genel_gider + manuel_gelir
    return {
        "toplam_gelir": toplam_gelir,
        "toplam_gider_kargo": matched["Gider_Kargo"].sum(),
        "toplam_gider_tax": matched["Gider_Tax"].sum(),
        "toplam_gider_eslesen": matched["Gider"].sum(),
        "toplam_kar": toplam_kar,
        "genel_gider": genel_gider,
        "manuel_gelir": manuel_gelir,
        "net_kar": net_kar,
        "net_kar_yuzde": (net_kar / toplam_gelir * 100) if toplam_gelir else 0.0,
        "toplam_gonderi": len(merged),
        "eslesen_sayisi": len(matched),
        "takip_no_yok_sayisi": (merged["Durum"] == "Takip no yok").sum(),
        "gider_bulunamadi_sayisi": (merged["Durum"] == "Gider bulunamadi").sum(),
    }


# Ulke adindan ISO 3166-1 alpha-2 koduna esleme (bayrak emoji uretmek icin).
# Kucuk harfle karsilastirilir. Kapsamli degil ama uluslararasi kargo
# gonderimlerinde sik gorulen ulkelerin cogunu icerir - eslesme bulunamazsa
# ulke adi sadece bayraksiz gosterilir, hata vermez.
COUNTRY_TO_ISO = {
    "united states": "US", "usa": "US", "us": "US",
    "canada": "CA",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "france": "FR",
    "germany": "DE",
    "spain": "ES",
    "italy": "IT",
    "portugal": "PT",
    "netherlands": "NL", "netherlands the": "NL", "the netherlands": "NL",
    "belgium": "BE",
    "switzerland": "CH",
    "austria": "AT",
    "ireland": "IE",
    "australia": "AU",
    "singapore": "SG",
    "new zealand": "NZ",
    "japan": "JP",
    "south korea": "KR", "korea south": "KR", "korea": "KR",
    "china": "CN",
    "hong kong": "HK",
    "taiwan": "TW",
    "mexico": "MX",
    "brazil": "BR",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "poland": "PL",
    "czech republic": "CZ", "czechia": "CZ",
    "greece": "GR",
    "turkey": "TR", "turkiye": "TR",
    "israel": "IL",
    "united arab emirates": "AE", "uae": "AE",
    "saudi arabia": "SA",
    "south africa": "ZA",
    "india": "IN",
    "indonesia": "ID",
    "malaysia": "MY",
    "thailand": "TH",
    "vietnam": "VN",
    "philippines": "PH",
    "argentina": "AR",
    "chile": "CL",
    "colombia": "CO",
    "peru": "PE",
    "russia": "RU",
    "ukraine": "UA",
    "romania": "RO",
    "hungary": "HU",
    "bulgaria": "BG",
    "croatia": "HR",
    "slovenia": "SI",
    "slovakia": "SK",
    "estonia": "EE",
    "latvia": "LV",
    "lithuania": "LT",
    "luxembourg": "LU",
    "iceland": "IS",
    "malta": "MT",
    "cyprus": "CY",
    "egypt": "EG",
    "morocco": "MA",
    "nigeria": "NG",
    "kenya": "KE",
    "pakistan": "PK",
    "bangladesh": "BD",
    "sri lanka": "LK",
    "qatar": "QA",
    "kuwait": "KW",
    "bahrain": "BH",
    "oman": "OM",
    "jordan": "JO",
    "lebanon": "LB",
    "serbia": "RS",
    "bosnia and herzegovina": "BA",
    "north macedonia": "MK",
    "albania": "AL",
    "georgia": "GE",
    "armenia": "AM",
    "azerbaijan": "AZ",
    "kazakhstan": "KZ",
}


def _country_flag(country_name):
    """Ulke adina karsilik gelen bayrak emojisini dondurur. Eslesme yoksa
    bos string doner (bayraksiz gosterilir, hata vermez)."""
    if pd.isna(country_name):
        return ""
    iso = COUNTRY_TO_ISO.get(str(country_name).strip().lower())
    if not iso:
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso)


def format_country_with_flag(country_name):
    """'Canada' -> '🇨🇦 Canada' gibi bayrakli gosterim uretir. Eslesme
    bulunamazsa ulke adini degistirmeden dondurur."""
    if pd.isna(country_name):
        return country_name
    flag = _country_flag(country_name)
    return f"{flag} {country_name}" if flag else str(country_name)


def country_breakdown(merged):
    """Ulkeye gore gelir, kargo gideri, vergi ve kar dagilimi.

    Gonderi Sayisi ve Toplam Gelir (Tum) TUM gonderileri kapsar.
    Eslesen Gelir, Kargo/Vergi/Toplam Gider ve Kar sutunlari sadece
    ESLESEN gonderilerden gelir.

    Kar = Eslesen Gelir - Toplam Gider (tutarli karsilastirma icin).
    """
    merged = merged.copy()
    merged["_eslesen_gelir"] = merged["Invoice Amount"].where(merged["Durum"] == "Eslesti")

    out = (
        merged.groupby("Receiver Country", as_index=False)
        .agg(
            Gonderi_Sayisi=("Shipment No", "count"),
            Eslesen_Sayisi=("Durum", lambda x: (x == "Eslesti").sum()),
            Toplam_Gelir=("Invoice Amount", "sum"),
            Eslesen_Gelir=("_eslesen_gelir", "sum"),
            Kargo_Gideri=("Gider_Kargo", "sum"),
            Vergi_Gideri=("Gider_Tax", "sum"),
            Toplam_Gider=("Gider", "sum"),
            Kar=("Kar", "sum"),
        )
        .rename(columns={"Receiver Country": "Ulke"})
        .sort_values("Toplam_Gelir", ascending=False)
        .reset_index(drop=True)
    )
    out["Ulke"] = out["Ulke"].apply(format_country_with_flag)
    out["Paket_Basi_Kar"] = [
        (kar / sayi) if sayi > 0 else 0.0
        for kar, sayi in zip(out["Kar"], out["Eslesen_Sayisi"])
    ]
    out["Kar_Yuzde"] = [
        (kar / gelir * 100) if gelir else 0.0
        for kar, gelir in zip(out["Kar"], out["Eslesen_Gelir"])
    ]
    return out


def carrier_breakdown(merged):
    """Kargo firmasina (gelir dosyasindaki Carrier Name) gore paket sayisi,
    gelir, gider ve kar/zarar dagilimi.

    Paket Sayisi ve Toplam Gelir TUM gonderileri kapsar.
    Eslesen Gelir, Kargo Gideri, Vergi Gideri, Toplam Gider ve Kar/Zarar
    sutunlari sadece ESLESEN gonderilerden gelir.

    Kar/Zarar = Eslesen Gelir - Toplam Gider (tutarli karsilastirma icin).
    """
    merged = merged.copy()
    merged["Carrier Name"] = merged["Carrier Name"].fillna("Atanmamis")
    merged["_eslesen_gelir"] = merged["Invoice Amount"].where(merged["Durum"] == "Eslesti")

    out = (
        merged.groupby("Carrier Name", as_index=False)
        .agg(
            **{
                "Paket Sayisi": ("Shipment No", "count"),
                "Eslesen Sayisi": ("Durum", lambda x: (x == "Eslesti").sum()),
                "Toplam Gelir (Tum)": ("Invoice Amount", "sum"),
                "Eslesen Gelir": ("_eslesen_gelir", "sum"),
                "Kargo Gideri": ("Gider_Kargo", "sum"),
                "Vergi Gideri": ("Gider_Tax", "sum"),
                "Toplam Gider": ("Gider", "sum"),
                "Kar/Zarar": ("Kar", "sum"),
            }
        )
        .rename(columns={"Carrier Name": "Kargo Firmasi"})
        .sort_values("Toplam Gelir (Tum)", ascending=False)
        .reset_index(drop=True)
    )
    out["Paket Basi Kar/Zarar"] = [
        (kar / sayi) if sayi > 0 else 0.0
        for kar, sayi in zip(out["Kar/Zarar"], out["Eslesen Sayisi"])
    ]
    out["Kar Yuzdesi (%)"] = [
        (kar / gelir * 100) if gelir else 0.0
        for kar, gelir in zip(out["Kar/Zarar"], out["Eslesen Gelir"])
    ]
    return out


def apply_per_package_carrier_fee(merged, fee_df):
    """Belirli bir kargo firmasinin HER takip edilebilir VE ZATEN GIDERI
    ESLESMIS paketine (Takip_Var_Mi = True, Durum = "Eslesti") sabit bir
    paket-basi ek gider ekler (orn. UniUni icin paket basina $2). Boylece
    eklenen tutar otomatik olarak paket sayisi ile carpilip her paketin
    Gider/Kar degerine islenir - toplam kar, ulke/firma/musteri kirilimlari
    dahil her yerde otomatik gorunur (hepsi merged'den hesaplanir).

    Gideri eslesmemis (Durum="Gider bulunamadi") paketlere bu ek gider
    UYGULANMAZ - sadece zaten gideri eslesmis paketlerin gider tutarina
    eklenir, "eslesme" durumunu degistirmez.

    merged'in guncellenmis bir KOPYASINI dondurur (orijinali degistirmez).
    """
    if fee_df is None or fee_df.empty:
        return merged

    valid = fee_df.dropna(subset=["Kargo Firmasi", "Paket Basi Tutar"])
    valid = valid[valid["Kargo Firmasi"].astype(str).str.strip() != ""]
    if valid.empty:
        return merged

    merged = merged.copy()

    for _, row in valid.iterrows():
        firma = _normalize_carrier_name(str(row["Kargo Firmasi"]).strip())
        tutar = float(row["Paket Basi Tutar"])

        mask = (
            (merged["Carrier Name"] == firma)
            & (merged["Takip_Var_Mi"])
            & (merged["Durum"] == "Eslesti")
        )
        if not mask.any():
            continue

        merged.loc[mask, "Gider_Kargo"] = merged.loc[mask, "Gider_Kargo"].fillna(0.0) + tutar
        merged.loc[mask, "Gider_Tax"] = merged.loc[mask, "Gider_Tax"].fillna(0.0)
        merged.loc[mask, "Gider"] = merged.loc[mask, "Gider_Kargo"] + merged.loc[mask, "Gider_Tax"]
        merged.loc[mask, "Kar"] = merged.loc[mask, "Invoice Amount"] - merged.loc[mask, "Gider"]

        not_etiketi = f"Paket basi ek ucret: ${tutar:.2f}"
        mevcut = merged.loc[mask, "Gider_Kalemleri"].fillna("")
        merged.loc[mask, "Gider_Kalemleri"] = mevcut.where(mevcut == "", mevcut + "; ") + not_etiketi

    return merged


def customer_breakdown(merged):
    """Musteri (User No) bazinda paket sayisi, gelir, gider, kar/zarar ve
    gonderdigi ulkeler.

    Paket Sayisi ve Bize Odenen TUM gonderileri kapsar. Eslesen Sayisi,
    Firmaya Odenen, Kar/Zarar sutunlari sadece ESLESEN gonderilerden gelir.
    """
    merged = merged.copy()
    merged["User No"] = merged["User No"].astype(str)
    merged["User Name"] = merged["User Name"].fillna("Bilinmiyor")

    out = (
        merged.groupby(["User No", "User Name"], as_index=False)
        .agg(
            **{
                "Paket Sayisi": ("Shipment No", "count"),
                "Eslesen Sayisi": ("Durum", lambda x: (x == "Eslesti").sum()),
                "Bize Odenen (Gelir)": ("Invoice Amount", "sum"),
                "Firmaya Odenen (Gider)": ("Gider", "sum"),
                "Kar/Zarar": ("Kar", "sum"),
                "Gonderdigi Ulkeler": (
                    "Receiver Country",
                    lambda x: ", ".join(format_country_with_flag(u) for u in sorted(set(x.dropna()))),
                ),
            }
        )
        .rename(columns={"User No": "Musteri No", "User Name": "Musteri Adi"})
        .sort_values("Bize Odenen (Gelir)", ascending=False)
        .reset_index(drop=True)
    )
    out["Paket Basi Kar/Zarar"] = [
        (kar / sayi) if sayi > 0 else 0.0
        for kar, sayi in zip(out["Kar/Zarar"], out["Eslesen Sayisi"])
    ]
    out["Kar Yuzdesi (%)"] = [
        (kar / gelir * 100) if gelir else 0.0
        for kar, gelir in zip(out["Kar/Zarar"], out["Bize Odenen (Gelir)"])
    ]
    return out


def customer_country_breakdown(merged):
    """Musteri x Ulke bazinda kar/zarar analizi.

    Hangi musterinin hangi ulkeye yaptigi gonderilerin kar mi zarar mi
    ettirdigini gosterir. En cok zarar ettiren kombinasyonlar basta gorunur.
    """
    merged = merged.copy()
    merged["User No"] = merged["User No"].astype(str)
    merged["User Name"] = merged["User Name"].fillna("Bilinmiyor")

    out = (
        merged.groupby(["User No", "User Name", "Receiver Country"], as_index=False)
        .agg(
            **{
                "Paket Sayisi": ("Shipment No", "count"),
                "Eslesen Sayisi": ("Durum", lambda x: (x == "Eslesti").sum()),
                "Gelir": ("Invoice Amount", "sum"),
                "Gider": ("Gider", "sum"),
                "Kar/Zarar": ("Kar", "sum"),
            }
        )
        .rename(columns={"User No": "Musteri No", "User Name": "Musteri Adi", "Receiver Country": "Ulke"})
        .sort_values("Kar/Zarar")
        .reset_index(drop=True)
    )
    out["Ulke"] = out["Ulke"].apply(format_country_with_flag)
    out["Kar Yuzdesi (%)"] = [
        (kar / gelir * 100) if gelir else 0.0
        for kar, gelir in zip(out["Kar/Zarar"], out["Gelir"])
    ]
    return out


def manual_expense_total(manual_df):
    """Kullanicinin elle ekledigi (Aciklama, Tutar) satirlarinin toplami.

    Bu giderler hicbir pakete baglanmaz, dogrudan net kardan dusulur - ayni
    UPS Brokerage Charges gibi pakete baglanamayan vergi kalemleri gibi.
    Bos/eksik satirlar (aciklama veya tutar olmayan) hesaba katilmaz.
    """
    if manual_df is None or manual_df.empty:
        return 0.0
    valid = manual_df.dropna(subset=["Aciklama", "Tutar"])
    valid = valid[valid["Aciklama"].astype(str).str.strip() != ""]
    if valid.empty:
        return 0.0
    return float(pd.to_numeric(valid["Tutar"], errors="coerce").fillna(0).sum())


# Avrupa bolgesine dahil edilen ulkeler (UK, Turkiye, Cyprus, Israel dahil).
# Receiver Country kolonu ile karsilastirilir (kucuk harfe indirgenerek).
EUROPE_COUNTRIES = {
    "united kingdom", "uk", "great britain",
    "france", "germany", "spain", "italy", "portugal",
    "netherlands", "netherlands the", "the netherlands",
    "belgium", "switzerland", "austria", "ireland",
    "sweden", "norway", "denmark", "finland",
    "poland", "czech republic", "czechia",
    "greece", "turkey", "turkiye",
    "cyprus", "israel",
    "romania", "hungary", "bulgaria", "croatia",
    "slovenia", "slovakia", "estonia", "latvia", "lithuania",
    "luxembourg", "iceland", "malta",
    "serbia", "bosnia and herzegovina", "north macedonia",
    "albania", "georgia", "armenia", "azerbaijan",
    "ukraine", "russia",
}


def europe_summary(merged):
    """Avrupa ulkelerine ait gonderileri toplu olarak ozetler.

    Tek bir ozet satiri dondurur: toplam gonderi/eslesen sayisi, toplam
    gelir (tum), eslesen gelir, kargo gideri, vergi/gumruk gideri,
    toplam gider ve kar/zarar.

    Avrupa'ya dahil edilen ulkeler EUROPE_COUNTRIES setinde tanimlidir
    (UK, Turkiye, Cyprus, Israel dahil).
    """
    merged = merged.copy()
    merged["_is_europe"] = merged["Receiver Country"].apply(
        lambda c: str(c).strip().lower() in EUROPE_COUNTRIES if not pd.isna(c) else False
    )
    eu = merged[merged["_is_europe"]]
    eslesen = eu[eu["Durum"] == "Eslesti"]

    if eu.empty:
        return None

    ulkeler = sorted(eu["Receiver Country"].dropna().unique())

    return {
        "ulkeler": [format_country_with_flag(u) for u in ulkeler],
        "gonderi_sayisi": len(eu),
        "eslesen_sayisi": int((eu["Durum"] == "Eslesti").sum()),
        "toplam_gelir": float(eu["Invoice Amount"].sum()),
        "eslesen_gelir": float(eslesen["Invoice Amount"].sum()),
        "kargo_gideri": float(eslesen["Gider_Kargo"].sum()),
        "vergi_gideri": float(eslesen["Gider_Tax"].sum()),
        "toplam_gider": float(eslesen["Gider"].sum()),
        "kar_zarar": float(eslesen["Kar"].sum()),
        "kar_yuzde": (
            float(eslesen["Kar"].sum() / eslesen["Invoice Amount"].sum() * 100)
            if eslesen["Invoice Amount"].sum() else 0.0
        ),
    }
