"""
Depo gelir-gider karsilastirma araci.

Calistirmak icin:
    streamlit run app.py
"""

import io
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from processing import (
    BYELABEL_GROUP_LABEL,
    CARRIER_PROFILES,
    KNOWN_CARRIERS,
    apply_per_package_carrier_fee,
    build_report,
    carrier_breakdown,
    country_breakdown,
    customer_breakdown,
    customer_country_breakdown,
    europe_summary,
    load_byelabel_group,
    load_cost_file,
    load_income_file,
    manual_expense_total,
    summarize,
)
from github_storage import (
    GithubStorageError,
    list_periods,
    list_raw_files,
    load_gider_meta,
    load_raw_file,
    merge_and_save_raw_file,
    save_gider_meta,
)

st.set_page_config(
    page_title="Gelir-Gider Karsilastirma",
    layout="wide",
    initial_sidebar_state="expanded",
)

# "Sellivox" tarzi acik panel temasi: koyu genis sidebar + beyaz ana alan +
# renkli sol-kenarlikli KPI kartlari.
st.markdown(
    """
    <style>
    :root {
        --panel-bg: #f4f5f8;
        --card-bg: #ffffff;
        --text-dark: #1f2430;
        --text-muted: #5f6779;
        --border-light: #c7cbd6;
        --accent-blue: #3b82f6;
        --sidebar-bg: #14161c;
        --sidebar-bg-2: #1b1e26;
        --sidebar-text: #c3c9d4;
    }

    /* Ana arka plan - acik gri */
    .stApp {
        background-color: var(--panel-bg) !important;
        color: var(--text-dark) !important;
    }

    .main .block-container,
    [data-testid="stMainBlockContainer"] {
        background-color: var(--panel-bg) !important;
        padding-top: 3.4rem !important;
        max-width: 1400px !important;
    }

    /* Streamlit'in ust bosluk birakan gizli header/toolbar alani.
       Not: yukseklik 0 yapilmiyor, cunku sidebar acma/kapama oku bu alanin
       icinde - sadece dekoratif kisimlar (renkli ust cizgi, deploy/menu
       araç çubugu) gizleniyor, ok butonu gorunur kaliyor. */
    [data-testid="stHeader"] {
        background: var(--panel-bg) !important;
        height: 2.75rem !important;
        min-height: 2.75rem !important;
    }
    [data-testid="stToolbar"] {
        visibility: hidden !important;
    }
    [data-testid="stDecoration"] {
        display: none !important;
    }

    /* Elemanlar arasi dikey bosluklari sikistir */
    [data-testid="stVerticalBlock"] {
        gap: 0.55rem !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        gap: 0.55rem !important;
    }

    /* Ayirici (divider) - tek, ince, duz cizgi (tarayici varsayilan "oluklu" gorunumu kaldirildi) */
    hr {
        margin: 0.4rem 0 !important;
        border: none !important;
        border-top: 1px solid var(--border-light) !important;
        background: none !important;
        height: 0 !important;
    }

    h1, h2, h3, h4 {
        color: var(--text-dark) !important;
        font-weight: 700 !important;
        margin-top: 0.2rem !important;
        margin-bottom: 0.4rem !important;
    }

    p, span, label, .stMarkdown {
        color: var(--text-dark) !important;
    }

    .stApp header {
        background-color: var(--panel-bg) !important;
    }

    /* Ana butonlar - mavi dolgu */
    .stButton > button {
        background-color: var(--accent-blue) !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        box-shadow: 0 1px 2px rgba(16, 24, 40, 0.08) !important;
    }
    .stButton > button:hover {
        background-color: #2563eb !important;
        color: #ffffff !important;
    }

    /* Indirme butonlari - Export Report tarzi acik mavi outline */
    [data-testid="stDownloadButton"] > button {
        background-color: #eef4ff !important;
        color: var(--accent-blue) !important;
        border: 1px solid #cfe0fd !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }
    [data-testid="stDownloadButton"] > button:hover {
        background-color: #dbe8fe !important;
        color: var(--accent-blue) !important;
    }

    /* Tablolar - beyaz kart */
    .stDataFrame, [data-testid="stDataFrame"], [data-testid="stDataFrameResizable"] {
        background-color: var(--card-bg) !important;
        border-radius: 10px !important;
        border: 1.5px solid var(--border-light) !important;
    }

    /* Input alanlari */
    .stTextInput > div > div > input,
    .stSelectbox > div > div,
    .stMultiSelect > div > div {
        background-color: var(--card-bg) !important;
        color: var(--text-dark) !important;
        border: 1.5px solid var(--border-light) !important;
        border-radius: 8px !important;
    }

    .stCheckbox > label {
        color: var(--text-dark) !important;
    }

    /* Expander / Accordion */
    .streamlit-expanderHeader {
        background-color: var(--card-bg) !important;
        color: var(--accent-blue) !important;
        border-radius: 8px !important;
        border: 1.5px solid var(--border-light) !important;
    }

    /* Tab */
    .stTabs [data-baseweb="tab-list"] {
        background-color: var(--card-bg) !important;
        border-radius: 8px !important;
    }
    .stTabs [data-baseweb="tab"] {
        color: var(--text-muted) !important;
    }
    .stTabs [aria-selected="true"] {
        color: var(--accent-blue) !important;
        border-bottom-color: var(--accent-blue) !important;
    }

    .stCaption, [data-testid="stCaptionContainer"] {
        color: var(--text-muted) !important;
    }

    .stDataEditor {
        background: var(--card-bg) !important;
        border-radius: 10px !important;
    }

    /* Dosya yukleme kutusu - lacivert zemin, acik renk yazi */
    [data-testid="stFileUploaderDropzone"] {
        background-color: #16213e !important;
        border: 1px dashed #2e3f66 !important;
        border-radius: 10px !important;
    }
    [data-testid="stFileUploaderDropzone"] * {
        color: #e5e9f2 !important;
    }
    [data-testid="stFileUploaderDropzone"] svg {
        fill: #e5e9f2 !important;
    }
    [data-testid="stFileUploaderDropzone"] small {
        color: #a9b2c6 !important;
    }
    [data-testid="stFileUploaderDropzone"] button {
        background-color: #223258 !important;
        color: #ffffff !important;
        border: 1px solid #3b4c7a !important;
        border-radius: 6px !important;
    }
    [data-testid="stFileUploaderFile"] {
        background-color: #16213e !important;
        color: #e5e9f2 !important;
        border-radius: 8px !important;
    }
    [data-testid="stFileUploaderFile"] * {
        color: #e5e9f2 !important;
    }

    /* Manuel giris tablolari (data_editor) - lacivert zemin, acik renk yazi */
    [data-testid="stDataEditorGrid"],
    [data-testid="stDataFrameResizable"] canvas {
        background-color: #16213e !important;
    }
    .stDataEditor [data-testid="stElementToolbar"] {
        background-color: #16213e !important;
    }
    .stDataEditor {
        background-color: #16213e !important;
        border: 1px solid #2e3f66 !important;
    }
    .stDataEditor * {
        color: #e5e9f2 !important;
    }

    [data-testid="metric-container"] {
        background: var(--card-bg) !important;
        border-radius: 10px !important;
        padding: 12px !important;
        border: 1.5px solid var(--border-light) !important;
    }
    [data-testid="stMetricValue"] {
        color: var(--accent-blue) !important;
    }
    [data-testid="stMetricLabel"] {
        color: var(--text-muted) !important;
    }

    .stAlert {
        background-color: var(--card-bg) !important;
        border-radius: 8px !important;
        border: 1.5px solid var(--border-light) !important;
    }

    /* Sidebar - koyu, genis panel */
    [data-testid="stSidebar"] {
        background-color: var(--sidebar-bg) !important;
        border-right: 1px solid #22252d !important;
    }
    [data-testid="stSidebar"] * {
        color: var(--sidebar-text) !important;
    }

    /* Sidebar'i kapatma oku (sidebar acikken, sidebar icinde) - acik renk */
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapseButton"] button,
    [data-testid="stSidebarCollapseButton"] svg {
        visibility: visible !important;
        opacity: 1 !important;
        color: #ffffff !important;
        fill: #ffffff !important;
        stroke: #ffffff !important;
    }

    /* Sidebar'i acma oku (sidebar kapaliyken, ana alanin sol ustunde) - koyu renk */
    [data-testid="collapsedControl"] {
        background: var(--card-bg) !important;
        border: 1.5px solid var(--border-light) !important;
        border-radius: 6px !important;
    }
    [data-testid="collapsedControl"] button,
    [data-testid="collapsedControl"] svg {
        color: var(--text-dark) !important;
        fill: var(--text-dark) !important;
        stroke: var(--text-dark) !important;
        opacity: 1 !important;
    }

    .stApp > header {
        background: var(--panel-bg) !important;
        border-bottom: 1px solid var(--border-light) !important;
    }

    [data-baseweb="select"] {
        background: var(--card-bg) !important;
    }
    [data-baseweb="menu"] {
        background: var(--card-bg) !important;
        border: 1px solid var(--border-light) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)




def _hex_to_rgba(hex_renk, alpha):
    hex_renk = hex_renk.lstrip("#")
    r, g, b = int(hex_renk[0:2], 16), int(hex_renk[2:4], 16), int(hex_renk[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def renkli_kart(etiket, deger, renk, icon=""):
    """Sellivox tarzi: beyaz kart, hafif golge, sol renkli kenarlik."""
    st.markdown(
        f"""
        <div style="
            background: #ffffff;
            border-left: 5px solid {renk};
            border-radius: 10px;
            padding: 14px 18px;
            margin-bottom: 6px;
            box-shadow: 0 1px 4px rgba(16, 24, 40, 0.10);
            border-top: 1.5px solid #c7cbd6;
            border-right: 1.5px solid #c7cbd6;
            border-bottom: 1.5px solid #c7cbd6;
        ">
            <div style="font-size: 25px; font-weight: 800; color: #1f2430; line-height: 1.2;">{icon} {deger}</div>
            <div style="font-size: 12px; font-weight: 600; color: #5f6779; letter-spacing: 0.04em; margin-top: 4px;">{etiket}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kar_zarar_stil(val):
    """Kar/zarar hucresini pozitifse yesil, negatifse kirmizi vurgular (acik tema)."""
    if pd.isna(val):
        return ""
    if val < 0:
        return "background-color: rgba(220, 38, 38, 0.08); color: #b91c1c; font-weight: 700;"
    if val > 0:
        return "background-color: rgba(16, 185, 129, 0.10); color: #047857; font-weight: 700;"
    return ""


def indirme_butonlari(df, dosya_adi, key_prefix):
    """Bir tablo icin CSV ve Excel indirme butonlarini yan yana gosterir."""
    col_csv, col_excel = st.columns(2)
    with col_csv:
        csv_data = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "CSV olarak indir",
            data=csv_data,
            file_name=f"{dosya_adi}.csv",
            mime="text/csv",
            key=f"{key_prefix}_csv",
        )
    with col_excel:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False)
        st.download_button(
            "Excel olarak indir",
            data=buf.getvalue(),
            file_name=f"{dosya_adi}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{key_prefix}_excel",
        )


st.markdown(
    """
    <div style="
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 4px 0 4px 0;
        margin-bottom: 4px;
    ">
        <div>
            <div style="font-size: 26px; font-weight: 800; color: #1f2430; line-height: 1.2;">
                📦 Depo Paneli
            </div>
            <div style="font-size: 13px; color: #5f6779; margin-top: 2px;">
                Kargo faturalari ile musteri odemelerini otomatik eslestir
            </div>
        </div>
        <div style="
            width: 40px; height: 40px;
            background: #eef4ff;
            border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-size: 18px;
            flex-shrink: 0;
            border: 1.5px solid #c7cbd6;
        ">👤</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.divider()

# --------------------------------------------------------- sol menu (sidebar) ---
_hesapla_var = st.session_state.get("hesapla_tiklandi") and "income_df_cache" in st.session_state

BASE_MENU_ITEMS = [
    ("🏠", "Ana Sayfa"),
    ("📤", "Kargo Firmasina Gore Dosya Yukle"),
    ("🗄️", "GitHub Arsivinden Dosya Sec ve Hesapla"),
]
REPORT_MENU_ITEMS = [
    ("🚚", "Kargo Firmalarina Gore"),
    ("🌍", "Ulkelere Gore"),
    ("🗺️", "Avrupa Ozeti"),
    ("👥", "Musterilere Gore"),
    ("🔗", "Musteri x Ulke"),
    ("📋", "Detayli Rapor"),
    ("🔍", "Gider Bulunamayanlar"),
    ("⚖️", "Eslesmeyen Gider"),
]
MENU_ITEMS = BASE_MENU_ITEMS + (REPORT_MENU_ITEMS if _hesapla_var else [])

if "analiz_secimi" not in st.session_state:
    st.session_state["analiz_secimi"] = None  # None = Ana Sayfa

with st.sidebar:
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] {
            min-width: 248px !important;
            max-width: 248px !important;
            background-color: #14161c;
            border-right: 1px solid #22252d;
        }
        [data-testid="stSidebar"] > div:first-child {
            padding: 0 !important;
        }
        div[data-testid="stSidebarContent"] .stButton button {
            width: 100% !important;
            justify-content: flex-start !important;
            padding: 9px 14px !important;
            margin: 2px 0 !important;
            border-radius: 8px !important;
            display: flex;
            align-items: center;
            font-size: 14px !important;
            font-weight: 500 !important;
            background: transparent !important;
            border: none !important;
            color: #c3c9d4 !important;
            box-shadow: none !important;
            transition: background 0.15s;
        }
        div[data-testid="stSidebarContent"] .stButton button:hover {
            background: rgba(255,255,255,0.06) !important;
            color: #ffffff !important;
        }
        div[data-testid="stSidebarContent"] .stButton button p {
            font-size: 14px !important;
            margin: 0 !important;
            text-align: left !important;
        }
        .sidebar-logo {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 20px 18px 16px 18px;
            border-bottom: 1px solid #22252d;
            margin-bottom: 10px;
        }
        .sidebar-logo .box {
            width: 32px; height: 32px;
            background: linear-gradient(135deg, #3b82f6, #6366f1);
            border-radius: 8px;
            display: flex; align-items: center; justify-content: center;
            font-size: 16px;
        }
        .sidebar-logo .name {
            color: #ffffff !important;
            font-size: 16px;
            font-weight: 800;
        }
        .sidebar-section {
            color: #8891a1 !important;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.06em;
            padding: 14px 18px 6px 18px;
            text-transform: uppercase;
        }
        </style>
        <div class="sidebar-logo">
            <div class="box">📦</div>
            <div class="name">ComfyShip</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _aktif_etiket = st.session_state["analiz_secimi"] or "Ana Sayfa"
    _tum_etiketler = [label for _, label in MENU_ITEMS]
    if _aktif_etiket in _tum_etiketler:
        active_index = _tum_etiketler.index(_aktif_etiket)
        st.markdown(
            f"""
            <style>
            div[data-testid="stSidebarContent"] .stButton:nth-of-type({active_index + 1}) button {{
                background: rgba(59, 130, 246, 0.16) !important;
                color: #ffffff !important;
                box-shadow: inset 3px 0 0 #3b82f6 !important;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('<div class="sidebar-section">Ana Menu</div>', unsafe_allow_html=True)
    icon, label = BASE_MENU_ITEMS[0]
    if st.button(f"{icon}  {label}", key=f"nav_{label}", width="stretch"):
        st.session_state["analiz_secimi"] = None
        st.rerun()

    st.markdown('<div class="sidebar-section">Dosya Islemleri</div>', unsafe_allow_html=True)
    for icon, label in BASE_MENU_ITEMS[1:]:
        if st.button(f"{icon}  {label}", key=f"nav_{label}", width="stretch"):
            st.session_state["analiz_secimi"] = label
            st.rerun()

    if _hesapla_var:
        st.markdown('<div class="sidebar-section">Raporlar</div>', unsafe_allow_html=True)
        for icon, label in REPORT_MENU_ITEMS:
            if st.button(f"{icon}  {label}", key=f"nav_{label}", width="stretch"):
                st.session_state["analiz_secimi"] = label
                st.rerun()

analiz_secimi = st.session_state.get("analiz_secimi")

# ---------------------------------------------- kargo firmasina gore yukle ---
if analiz_secimi == "Kargo Firmasina Gore Dosya Yukle":
    st.subheader("📤 Kargo Firmasina Gore Dosya Yukle")
    st.caption(
        "Bir kargo firmasindan fatura geldikce, tum formu doldurmadan sadece "
        "o dosyayi secip GitHub'a kaydet. Ayni doneme, ayni firmadan tekrar "
        "dosya yuklersen otomatik birlestirilir (tekrarlar elenir, yeni "
        "satirlar eklenir)."
    )
    _tekli_donem = st.text_input(
        "Donem etiketi (orn. 2026-07)",
        value="",
        key="tekli_arsiv_donem",
        placeholder="orn. 2026-07",
    )
    _tekli_secenekler = ["Gelir (WH_CUSTOMER_SHIPMENT_LIST)"] + list(CARRIER_PROFILES.keys()) + [BYELABEL_GROUP_LABEL]
    _tekli_secim = st.selectbox("Kargo firmasi / dosya turu", options=_tekli_secenekler, key="tekli_arsiv_secim")
    _tekli_dosya = st.file_uploader(
        "Dosyayi sec", type=["xlsx"], key="tekli_arsiv_dosya"
    )
    if st.button(
        "📤 Bu Dosyayi Arsivle",
        key="tekli_arsivle_btn",
        disabled=_tekli_dosya is None or not _tekli_donem.strip(),
    ):
        try:
            _kategori = "gelir" if _tekli_secim.startswith("Gelir") else "gider"
            sonuc = merge_and_save_raw_file(
                _tekli_donem, _kategori, _tekli_dosya.name, _tekli_dosya.getvalue()
            )
            if _kategori == "gider":
                _mevcut_meta = load_gider_meta(_tekli_donem)
                _mevcut_meta[_tekli_dosya.name] = _tekli_secim
                save_gider_meta(_tekli_donem, _mevcut_meta)

            if sonuc["durum"] == "yeni":
                st.success(f"'{_tekli_dosya.name}' yeni dosya olarak '{_tekli_donem}' donemine kaydedildi ({sonuc['sonuc_satir']} satir).")
            else:
                st.success(
                    f"'{_tekli_dosya.name}' mevcut dosyayla birlestirildi "
                    f"(eski {sonuc['eski_satir']} + yeni {sonuc['yeni_satir']} satir → "
                    f"toplam {sonuc['sonuc_satir']} satir, tekrarlar elendi"
                    + (f", anahtar: {sonuc['dedup_anahtari']}" if sonuc["dedup_anahtari"] else "")
                    + ")."
                )
        except GithubStorageError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Arsivlenirken hata olustu: {e}")

# ------------------------------------------------------- github arsivi ---
elif analiz_secimi == "GitHub Arsivinden Dosya Sec ve Hesapla":
    st.subheader("🗄️ GitHub Arsivinden Dosya Sec ve Hesapla")
    st.caption(
        "Bilgisayarindan dosya yuklemek yerine, daha once GitHub'a arsivledigin "
        "gelir/gider dosyalarindan istedigini sec ve Hesapla'ya bas."
    )
    try:
        _kayitli_donemler = list_periods()
    except GithubStorageError as e:
        _kayitli_donemler = []
        st.warning(str(e))

    if not _kayitli_donemler:
        st.info("Henuz arsivlenmis bir donem yok. 'Kargo Firmasina Gore Dosya Yukle' bolumunden dosyalarini arsivleyebilirsin.")
    else:
        _secilen_arsiv_donemi = st.selectbox("Donem sec", options=_kayitli_donemler, key="arsiv_donem_sec")

        try:
            _gelir_secenekleri = list_raw_files(_secilen_arsiv_donemi, "gelir")
            _gider_secenekleri = list_raw_files(_secilen_arsiv_donemi, "gider")
            _gider_carrier_map_ekran = load_gider_meta(_secilen_arsiv_donemi)
        except GithubStorageError as e:
            _gelir_secenekleri, _gider_secenekleri, _gider_carrier_map_ekran = [], [], {}
            st.warning(str(e))

        _secili_gelir_dosyalari = st.multiselect(
            "Gelir dosyasi/dosyalari",
            options=_gelir_secenekleri,
            default=_gelir_secenekleri,
            key="arsiv_gelir_secim",
        )
        _gider_etiketli = {
            f"{ad}  →  {_gider_carrier_map_ekran.get(ad, 'bilinmiyor')}": ad for ad in _gider_secenekleri
        }
        _secili_gider_etiketleri = st.multiselect(
            "Gider (fatura) dosyasi/dosyalari",
            options=list(_gider_etiketli.keys()),
            default=list(_gider_etiketli.keys()),
            key="arsiv_gider_secim",
        )
        _secili_gider_dosyalari = [_gider_etiketli[e] for e in _secili_gider_etiketleri]

        if st.button(
            "📥 Dosyalari Yukle",
            type="primary",
            key="arsiv_hesapla_btn",
            disabled=not _secili_gelir_dosyalari,
            help="Dosyalari yukler ve Ana Sayfa'ya yonlendirir - orada manuel gelir/gider ekleyip Yeniden Hesapla'ya basabilirsin.",
        ):
            try:
                gider_carrier_map = _gider_carrier_map_ekran

                gelir_dfs_arsiv = []
                for gelir_dosya in _secili_gelir_dosyalari:
                    gelir_bytes = load_raw_file(_secilen_arsiv_donemi, "gelir", gelir_dosya)
                    gelir_dfs_arsiv.append(
                        load_income_file(
                            io.BytesIO(gelir_bytes),
                            only_paid=True,
                            exclude_unassigned_carrier=True,
                        )
                    )
                income_df_arsiv = pd.concat(gelir_dfs_arsiv, ignore_index=True)

                cost_dfs_arsiv = []
                warnings_arsiv = []
                carrier_overhead_arsiv = 0.0
                breakdown_dfs_arsiv = []
                for gider_dosya in _secili_gider_dosyalari:
                    gider_bytes = load_raw_file(_secilen_arsiv_donemi, "gider", gider_dosya)
                    secilen_carrier = gider_carrier_map.get(gider_dosya, BYELABEL_GROUP_LABEL)
                    if secilen_carrier == BYELABEL_GROUP_LABEL:
                        g_cost_dfs, g_warnings, g_genel_gider, g_breakdown_dfs = load_byelabel_group(
                            io.BytesIO(gider_bytes)
                        )
                        cost_dfs_arsiv.extend(g_cost_dfs)
                        warnings_arsiv.extend(g_warnings)
                        carrier_overhead_arsiv += g_genel_gider
                        breakdown_dfs_arsiv.extend(g_breakdown_dfs)
                    else:
                        cost_df, warning, genel_gider, breakdown_df = load_cost_file(
                            io.BytesIO(gider_bytes), secilen_carrier
                        )
                        cost_dfs_arsiv.append(cost_df)
                        if warning:
                            warnings_arsiv.append(warning)
                        carrier_overhead_arsiv += genel_gider
                        if not breakdown_df.empty:
                            breakdown_dfs_arsiv.append(breakdown_df)

                # Not: burada hesapla_tiklandi=True SET EDILMIYOR - kullanici
                # once Ana Sayfa'da manuel gelir/gider eklemeli, sonra kendi
                # "Yeniden Hesapla"ya basarak hesaplamayi tetiklemeli. Onceki
                # bir hesaplamadan kalma bayrak varsa temizlenir, aksi halde
                # otomatik olarak rapor sekmesine yonlendirilir.
                st.session_state["hesapla_tiklandi"] = False
                st.session_state["income_df_cache"] = income_df_arsiv
                st.session_state["cost_dfs_cache"] = cost_dfs_arsiv
                st.session_state["breakdown_dfs_cache"] = breakdown_dfs_arsiv
                st.session_state["carrier_overhead_cache"] = carrier_overhead_arsiv
                st.session_state["warnings_cache"] = warnings_arsiv
                st.session_state["analiz_secimi"] = None
                st.success(
                    f"'{_secilen_arsiv_donemi}' donemi dosyalari yuklendi. Ana Sayfa'ya "
                    "yonlendiriliyorsunuz - istersen manuel gelir/gider ekleyip "
                    "'Yeniden Hesapla'ya bas."
                )
                st.rerun()
            except GithubStorageError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Hesaplanirken hata olustu: {e}")

# ------------------------------------------------------------- ana sayfa ---
else:

    # Yuklu parametreler varsa widget varsayilan degerlerine uygula
    _params = st.session_state.get("yuklu_parametreler", {})

    # ---------------------------------------------------------------- yukleme ---
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Gelir")
        st.caption("WH_CUSTOMER_SHIPMENT_LIST formatinda, musteriden alinan tutarlari iceren dosya.")
        income_file = st.file_uploader("Gelir Excel dosyasini secin", type=["xlsx"], key="income")
        only_paid = st.checkbox(
            "Sadece odenmis gonderileri dahil et (Status = Paid)",
            value=_params.get("only_paid", True),
            help="Isaretliyse User Cancelled, New Shipment, Payment Waiting gibi durumlar disarida tutulur.",
        )
        exclude_unassigned_carrier = st.checkbox(
            "Kargo firmasi atanmamis gonderileri haric tut",
            value=_params.get("exclude_unassigned_carrier", True),
            help="Isaretliyse Carrier Name (kargo firmasi) bos olan gonderiler analize hic dahil edilmez.",
        )

        st.markdown("**Manuel gelir (opsiyonel)**")
        st.caption(
            "Hicbir pakete baglanmayan, dogrudan net kara eklenecek gelirler "
            "(orn. depo kirasi geliri, danismanlik geliri)."
        )
        _gelir_default = pd.DataFrame(_params.get("manuel_gelir", [])) if _params else pd.DataFrame({"Aciklama": pd.Series(dtype="str"), "Tutar": pd.Series(dtype="float")})
        if _gelir_default.empty or list(_gelir_default.columns) != ["Aciklama", "Tutar"]:
            _gelir_default = pd.DataFrame({"Aciklama": pd.Series(dtype="str"), "Tutar": pd.Series(dtype="float")})
        manual_income_df = st.data_editor(
            _gelir_default,
            num_rows="dynamic",
            column_config={
                "Aciklama": st.column_config.TextColumn("Aciklama"),
                "Tutar": st.column_config.NumberColumn("Tutar ($)", format="$%.2f"),
            },
            width="stretch",
            key="manual_income_editor",
        )

    with col2:
        st.subheader("Gider")
        st.caption("Kargo firmasindan gelen fatura dosyalari. Birden fazla dosya secebilirsiniz.")
        cost_files = st.file_uploader(
            "Gider Excel dosyasini/dosyalarini secin",
            type=["xlsx"],
            accept_multiple_files=True,
            key="cost",
        )

        carrier_for_file = {}
        if cost_files:
            st.write("Her dosya icin kargo firmasini secin:")
            for f in cost_files:
                carrier_for_file[f.name] = st.selectbox(
                    f"  {f.name}",
                    options=list(CARRIER_PROFILES.keys()) + [BYELABEL_GROUP_LABEL],
                    key=f"carrier_{f.name}",
                )
            st.caption(
                "Su an Asendia, UniUni, UPS ve Asendia'nin ayri Vergi/Gumruk dosyasi "
                "dogrudan destekleniyor. ByeLabel dosyasini (shipments-...xlsx) sectiginde "
                "icindeki tum firmalar (ePost Global, DHL, intelcom, APC, USPS, Evri, "
                "Purolator, FedEx, UPS) otomatik ayri ayri islenir."
            )

        dahil_et_genel_gider = True  # Pakete baglanamayan giderler her zaman dahil edilir (yarisı otomatik manuel gidere eklenir)

        st.markdown("**Manuel gider (opsiyonel)**")
        st.caption(
            "Hicbir pakete baglanmayan, dogrudan net kardan dusulecek giderler "
            "(orn. depo kirasi, personel maasi, internet faturasi)."
        )
        _gider_default = pd.DataFrame(_params.get("manuel_gider", [])) if _params else pd.DataFrame({"Aciklama": pd.Series(dtype="str"), "Tutar": pd.Series(dtype="float")})
        if _gider_default.empty or list(_gider_default.columns) != ["Aciklama", "Tutar"]:
            _gider_default = pd.DataFrame({"Aciklama": pd.Series(dtype="str"), "Tutar": pd.Series(dtype="float")})

        # Otomatik satirlari en alta ekle (onceki otomatik satirlari temizle, yenileri ekle)
        otomatik_satirlar = st.session_state.get("otomatik_genel_gider_satirlari", [])
        if otomatik_satirlar:
            otomatik_aciklamalar = {s["Aciklama"] for s in otomatik_satirlar}
            _gider_default = _gider_default[
                ~_gider_default["Aciklama"].astype(str).isin(otomatik_aciklamalar)
            ]
            _gider_default = pd.concat(
                [_gider_default, pd.DataFrame(otomatik_satirlar)], ignore_index=True
            )

        manual_expenses_df = st.data_editor(
            _gider_default,
            num_rows="dynamic",
            column_config={
                "Aciklama": st.column_config.TextColumn("Aciklama"),
                "Tutar": st.column_config.NumberColumn("Tutar ($)", format="$%.2f"),
            },
            width="stretch",
            key="manual_expenses_editor",
        )

        st.markdown("**Paket basina ek gider - firma bazinda (opsiyonel)**")
        st.caption(
            "Belirli bir kargo firmasinin, gideri ZATEN eslesmis olan HER paketine "
            "ayni tutari ekler (orn. UniUni icin paket basina $2). Tutar otomatik "
            "olarak eslesen paket sayisiyla carpilir ve her paketin kar/zarar "
            "hesabina islenir - tum tablolarda (ulke, firma, musteri) otomatik "
            "yansir. Gideri eslesmemis paketlere bu tutar uygulanmaz."
        )
        _paket_cols = {"Kargo Firmasi": pd.Series(dtype="str"), "Aciklama": pd.Series(dtype="str"), "Paket Basi Tutar": pd.Series(dtype="float")}
        _paket_default = pd.DataFrame(_params.get("paket_basi_gider", [])) if _params else pd.DataFrame(_paket_cols)
        if _paket_default.empty or list(_paket_default.columns) != list(_paket_cols.keys()):
            _paket_default = pd.DataFrame(_paket_cols)
        manual_carrier_expenses_df = st.data_editor(
            _paket_default,
            num_rows="dynamic",
            column_config={
                "Kargo Firmasi": st.column_config.SelectboxColumn("Kargo Firmasi", options=KNOWN_CARRIERS),
                "Aciklama": st.column_config.TextColumn("Aciklama"),
                "Paket Basi Tutar": st.column_config.NumberColumn("Paket Basi Tutar ($)", format="$%.2f"),
            },
            width="stretch",
            key="manual_carrier_expenses_editor",
        )

    col_hesapla, col_yeniden = st.columns([2, 1])
    with col_hesapla:
        if st.button("Hesapla", type="primary", disabled=income_file is None):
            # Dosyalari oku ve session_state'e kaydet
            try:
                st.session_state["income_df_cache"] = load_income_file(
                    income_file, only_paid=only_paid, exclude_unassigned_carrier=exclude_unassigned_carrier
                )
            except ValueError as e:
                st.error(f"Gelir dosyasi okunamadi: {e}")
                st.stop()

            cost_dfs = []
            warnings_list = []
            carrier_overhead_toplam = 0.0
            breakdown_dfs = []
            for f in cost_files or []:
                try:
                    secilen = carrier_for_file[f.name]
                    if secilen == BYELABEL_GROUP_LABEL:
                        group_cost_dfs, group_warnings, group_genel_gider, group_breakdown_dfs = load_byelabel_group(f)
                        cost_dfs.extend(group_cost_dfs)
                        warnings_list.extend(group_warnings)
                        if group_genel_gider:
                            carrier_overhead_toplam += group_genel_gider
                        for bd in group_breakdown_dfs:
                            breakdown_dfs.append(bd)
                    else:
                        cost_df, warning, genel_gider, breakdown_df = load_cost_file(f, secilen)
                        cost_dfs.append(cost_df)
                        if warning:
                            warnings_list.append(warning)
                        if genel_gider:
                            carrier_overhead_toplam += genel_gider
                        if not breakdown_df.empty:
                            breakdown_dfs.append(breakdown_df)
                except ValueError as e:
                    st.error(f"{f.name} okunamadi: {e}")
                    st.stop()

            st.session_state["cost_dfs_cache"] = cost_dfs
            st.session_state["breakdown_dfs_cache"] = breakdown_dfs
            st.session_state["carrier_overhead_cache"] = carrier_overhead_toplam
            st.session_state["warnings_cache"] = warnings_list
            st.session_state["hesapla_tiklandi"] = True

    with col_yeniden:
        yeniden_disabled = "income_df_cache" not in st.session_state
        if st.button(
            "Yeniden Hesapla",
            disabled=yeniden_disabled,
            help="Dosyalari tekrar yuklemeden, sadece filtre/manuel giris degisikliklerini uygular.",
        ):
            st.session_state["hesapla_tiklandi"] = True

    # ------------------------------------------------------- github arsivle ---
    with st.expander("🗄️ Bu Dosyalari GitHub'a Arsivle", expanded=False):
        st.caption(
            "Yukarida sectigin gelir/gider dosyalarini bir doneme (orn. ay) etiketleyip "
            "GitHub'a kaydeder. Ayni isimli dosyayi tekrar yuklersen, eski veriyle "
            "otomatik birlestirilir: ayni takip numarasina sahip satirlar guncellenir, "
            "yeni satirlar eklenir - hicbir veri kaybolmaz."
        )
        _arsiv_donemi = st.text_input(
            "Donem etiketi (orn. 2026-07)", value="", key="arsiv_donem_input", placeholder="orn. 2026-07"
        )
        _arsiv_disabled = (income_file is None and not cost_files) or not _arsiv_donemi.strip()
        if st.button("📤 GitHub'a Arsivle", key="arsivle_btn", disabled=_arsiv_disabled):
            try:
                _sonuc_mesajlari = []
                if income_file is not None:
                    sonuc = merge_and_save_raw_file(_arsiv_donemi, "gelir", income_file.name, income_file.getvalue())
                    if sonuc["durum"] == "yeni":
                        _sonuc_mesajlari.append(f"📄 {income_file.name}: yeni dosya olarak kaydedildi ({sonuc['sonuc_satir']} satir).")
                    else:
                        _sonuc_mesajlari.append(
                            f"📄 {income_file.name}: mevcut dosyayla birlestirildi "
                            f"(eski {sonuc['eski_satir']} + yeni {sonuc['yeni_satir']} satir → "
                            f"toplam {sonuc['sonuc_satir']} satir, tekrarlar elendi"
                            + (f", anahtar: {sonuc['dedup_anahtari']}" if sonuc["dedup_anahtari"] else "")
                            + ")."
                        )
                _gider_meta = {}
                for f in cost_files or []:
                    sonuc = merge_and_save_raw_file(_arsiv_donemi, "gider", f.name, f.getvalue())
                    _gider_meta[f.name] = carrier_for_file.get(f.name, BYELABEL_GROUP_LABEL)
                    if sonuc["durum"] == "yeni":
                        _sonuc_mesajlari.append(f"📄 {f.name}: yeni dosya olarak kaydedildi ({sonuc['sonuc_satir']} satir).")
                    else:
                        _sonuc_mesajlari.append(
                            f"📄 {f.name}: mevcut dosyayla birlestirildi "
                            f"(eski {sonuc['eski_satir']} + yeni {sonuc['yeni_satir']} satir → "
                            f"toplam {sonuc['sonuc_satir']} satir, tekrarlar elendi"
                            + (f", anahtar: {sonuc['dedup_anahtari']}" if sonuc["dedup_anahtari"] else "")
                            + ")."
                        )
                if _gider_meta:
                    save_gider_meta(_arsiv_donemi, _gider_meta)
                st.success(f"'{_arsiv_donemi}' donemine kaydedildi:")
                for m in _sonuc_mesajlari:
                    st.caption(m)
            except GithubStorageError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Arsivlenirken hata olustu: {e}")

    # ---------------------------------------------------------------- hesapla ---
    if st.session_state.get("hesapla_tiklandi") and "income_df_cache" in st.session_state:

        # Dosyalari her seferinde yeniden yuklemek yerine cache'den al.
        # Sadece "Hesapla" butonuna basildiginda cache guncellenir.
        # "Yeniden Hesapla" ise ayni cache'i kullanarak filtre/girdi degisikliklerini uygular.
        income_df = st.session_state["income_df_cache"]
        cost_dfs = st.session_state["cost_dfs_cache"]
        breakdown_dfs = st.session_state["breakdown_dfs_cache"]
        carrier_overhead_toplam = st.session_state["carrier_overhead_cache"]

        # Filtreler degismisse gelir dosyasini cache'den yeniden isle
        # (only_paid / exclude_unassigned_carrier degisebilir - bunlar dosya
        # okumadan ayri hesaplama adimi oldugu icin burada uygulanir)
        if income_file is not None:
            try:
                income_df = load_income_file(
                    income_file, only_paid=only_paid, exclude_unassigned_carrier=exclude_unassigned_carrier
                )
            except Exception:
                pass  # cache'dekini kullanmaya devam et

        for w in st.session_state.get("warnings_cache", []):
            st.warning(w)

        # Pakete baglanamayan giderlerin her kalemi ayrı satır olarak,
        # yarı tutarıyla otomatik manuel gider listesine eklenir.
        full_breakdown_erken = pd.concat(breakdown_dfs, ignore_index=True) if breakdown_dfs else pd.DataFrame()
        if not full_breakdown_erken.empty:
            genel_gider_satirlari = full_breakdown_erken[
                full_breakdown_erken["Siniflandirma"] == "Genel Gider (pakete baglanamiyor)"
            ][["Kategori/Sutun", "Tutar"]]
            otomatik_satirlar = [
                {
                    "Aciklama": f"{row['Kategori/Sutun']} (yarisi) - otomatik",
                    "Tutar": round(row["Tutar"] / 2, 2),
                }
                for _, row in genel_gider_satirlari.iterrows()
                if row["Tutar"] > 0
            ]
        else:
            otomatik_satirlar = []
        st.session_state["otomatik_genel_gider_satirlari"] = otomatik_satirlar

        manuel_gider_toplam = manual_expense_total(manual_expenses_df)
        # carrier_overhead_toplam buraya EKLENMIYOR — onun yarisi zaten
        # manuel_expenses_df'e otomatik satir olarak eklendi, manual_expense_total
        # onu zaten sayiyor. Tam tutari ayrica eklemek cift sayima yol acar.
        toplam_genel_gider = manuel_gider_toplam
        manuel_gelir_toplam = manual_expense_total(manual_income_df)

        full_breakdown = full_breakdown_erken
        if not full_breakdown.empty:
            genel_gider_kategori_detay = full_breakdown[
                full_breakdown["Siniflandirma"] == "Genel Gider (pakete baglanamiyor)"
            ][["Kargo Firmasi", "Kategori/Sutun", "Kaynak Sutun", "Tutar"]].rename(columns={"Tutar": "Genel Gider"})
        else:
            genel_gider_kategori_detay = pd.DataFrame()

        merged, unmatched_cost = build_report(income_df, cost_dfs)
        merged = apply_per_package_carrier_fee(merged, manual_carrier_expenses_df)
        summary = summarize(merged, genel_gider=toplam_genel_gider, manuel_gelir=manuel_gelir_toplam)

        st.divider()
        st.subheader("📊 Ozet")

        renkli_kart("Toplam Paket Sayisi", f"{summary['toplam_gonderi']:,}", "#6366f1", "📦")

        st.markdown("")
        col_gelir, col_gider = st.columns(2)
        with col_gelir:
            st.markdown("**💰 Gelir**")
            renkli_kart("Toplam Gelir", f"${summary['toplam_gelir']:,.2f}", "#10b981", "💵")

        with col_gider:
            st.markdown("**💸 Gider**")
            renkli_kart("Kargo Gideri", f"${summary['toplam_gider_kargo']:,.2f}", "#f59e0b", "🚚")
            renkli_kart("Vergi/Gumruk Gideri", f"${summary['toplam_gider_tax']:,.2f}", "#f97316", "🛂")
            renkli_kart("Toplam Gider", f"${summary['toplam_gider_eslesen']:,.2f}", "#ef4444", "🧾")

        gecerli_paket_basi = manual_carrier_expenses_df.dropna(subset=["Kargo Firmasi", "Paket Basi Tutar"])
        gecerli_paket_basi = gecerli_paket_basi[gecerli_paket_basi["Kargo Firmasi"].astype(str).str.strip() != ""]
        has_per_package_fee = not gecerli_paket_basi.empty

        if toplam_genel_gider or manuel_gelir_toplam:
            col_gelir2, col_gider2 = st.columns(2)
            with col_gelir2:
                renkli_kart(
                    "Manuel Gelir",
                    f"${summary['manuel_gelir']:,.2f}",
                    "#14b8a6",
                    "✍️",
                )
            with col_gider2:
                renkli_kart(
                    "Genel Gider",
                    f"${summary['genel_gider']:,.2f}",
                    "#dc2626",
                    "⚠️",
                )

        gecerli_manuel_gelir = manual_income_df.dropna(subset=["Aciklama", "Tutar"])
        gecerli_manuel_gelir = gecerli_manuel_gelir[gecerli_manuel_gelir["Aciklama"].astype(str).str.strip() != ""]
        gecerli_manuel_gider = manual_expenses_df.dropna(subset=["Aciklama", "Tutar"])
        gecerli_manuel_gider = gecerli_manuel_gider[gecerli_manuel_gider["Aciklama"].astype(str).str.strip() != ""]
        # Otomatik eklenen satirlari dashboard gosteriminden cikar (sadece kullanicinin yazdiklarini goster)
        _otomatik_aciklamalar = {s["Aciklama"] for s in st.session_state.get("otomatik_genel_gider_satirlari", [])}
        gecerli_manuel_gider_gosterim = gecerli_manuel_gider[
            ~gecerli_manuel_gider["Aciklama"].astype(str).isin(_otomatik_aciklamalar)
        ]

        if not gecerli_manuel_gelir.empty or not gecerli_manuel_gider_gosterim.empty or has_per_package_fee:
            col_mg, col_mgid = st.columns(2)
            with col_mg:
                if not gecerli_manuel_gelir.empty:
                    st.caption("Manuel gelir kalemleri:")
                    st.dataframe(
                        gecerli_manuel_gelir.style.format({"Tutar": "${:,.2f}"}),
                        width="stretch",
                        hide_index=True,
                    )
            with col_mgid:
                if not gecerli_manuel_gider_gosterim.empty or otomatik_satirlar:
                    st.caption("Manuel gider kalemleri:")
                    _goster_df = gecerli_manuel_gider_gosterim.copy()
                    if otomatik_satirlar:
                        _goster_df = pd.concat(
                            [_goster_df, pd.DataFrame(otomatik_satirlar)], ignore_index=True
                        )
                    st.dataframe(
                        _goster_df.style.format({"Tutar": "${:,.2f}"}),
                        width="stretch",
                        hide_index=True,
                    )

        st.markdown("")
        _, kar_orta, _ = st.columns([1, 1, 1])
        with kar_orta:
            net_kar_renk = "#10b981" if summary["net_kar"] >= 0 else "#dc2626"
            net_kar_icon = "📈" if summary["net_kar"] >= 0 else "📉"
            renkli_kart("Net Kar", f"${summary['net_kar']:,.2f}", net_kar_renk, net_kar_icon)

        if not genel_gider_kategori_detay.empty:
            st.caption("⚠️ Pakete baglanamayan vergi/komisyon - otomatik tespit edilen (Net Kar'a dahil):")

            kaynaklar = genel_gider_kategori_detay[["Kargo Firmasi", "Kaynak Sutun"]].drop_duplicates()
            for _, kr in kaynaklar.iterrows():
                st.caption(f"📂 {kr['Kargo Firmasi']} icin kaynak kolon: *{kr['Kaynak Sutun']}*")

            st.dataframe(
                genel_gider_kategori_detay.drop(columns=["Kaynak Sutun"]).style.format({"Genel Gider": "${:,.2f}"}),
                width="stretch",
                hide_index=True,
            )
            indirme_butonlari(genel_gider_kategori_detay, "genel_gider_detayi", "genel_gider_detay")

        eslesme_orani = summary["eslesen_sayisi"] / summary["toplam_gonderi"] * 100 if summary["toplam_gonderi"] else 0
        st.caption(f"Eslesme orani: %{eslesme_orani:.1f}")

        st.caption(
            f"Toplam {summary['toplam_gonderi']} gonderi  |  "
            f"{summary['eslesen_sayisi']} eslesti  |  "
            f"{summary['gider_bulunamadi_sayisi']} gider bulunamadi  |  "
            f"{summary['takip_no_yok_sayisi']} takip no yok"
        )

        # Rapor sekmelerinden biri secili degilse (orn. hesaplama az once bitti),
        # varsayilan olarak ilk rapor sekmesini goster.
        _rapor_etiketleri = [label for _, label in REPORT_MENU_ITEMS]
        if analiz_secimi not in _rapor_etiketleri:
            analiz_secimi = REPORT_MENU_ITEMS[0][1]
            st.session_state["analiz_secimi"] = analiz_secimi

        st.divider()

        if analiz_secimi == "Kargo Firmalarina Gore":
            st.subheader("🚚 Kargo Firmalarina Gore Analiz")
            st.caption(
                "Kargo firmasi (gelir dosyasindaki Carrier Name) bazinda paket sayisi, "
                "gelir, gider ve kar/zarar dagilimi."
            )
            carrier_table = carrier_breakdown(merged)
            st.dataframe(
                carrier_table.style.format(
                    {
                        "Toplam Gelir (Tum)": "${:,.2f}",
                        "Eslesen Gelir": "${:,.2f}",
                        "Kargo Gideri": "${:,.2f}",
                        "Vergi Gideri": "${:,.2f}",
                        "Toplam Gider": "${:,.2f}",
                        "Kar/Zarar": "${:,.2f}",
                        "Paket Basi Kar/Zarar": "${:,.2f}",
                    }
                ).map(kar_zarar_stil, subset=["Kar/Zarar", "Paket Basi Kar/Zarar"]),
                width="stretch",
                hide_index=True,
            )
            indirme_butonlari(carrier_table, "kargo_firmasi_analizi", "carrier_table")

            if not full_breakdown.empty:
                st.caption(
                    "Asagidaki tablo her dosyada hangi kategori/sutunun Kargo, hangisinin "
                    "Vergi, hangisinin (takip numarasi olmadigi icin) Genel Gider sayildigini "
                    "ve ne kadar tutar tasidigini gosterir."
                )
                st.dataframe(
                    full_breakdown.style.format({"Tutar": "${:,.2f}"}),
                    width="stretch",
                    hide_index=True,
                )
                indirme_butonlari(full_breakdown, "kargo_vergi_siniflandirma", "full_breakdown")

        elif analiz_secimi == "Ulkelere Gore":
            st.subheader("🌍 Ulkeye gore analiz")
            st.caption(
                "Toplam gelir ve gonderi sayisi tum gonderileri kapsar. Kargo/Vergi/Kar "
                "sutunlari sadece gider dosyasinda eslesen gonderilerden gelir."
            )
            cb = country_breakdown(merged)
            st.dataframe(
                cb.style.format(
                    {
                        "Toplam_Gelir": "${:,.2f}",
                        "Eslesen_Gelir": "${:,.2f}",
                        "Kargo_Gideri": "${:,.2f}",
                        "Vergi_Gideri": "${:,.2f}",
                        "Toplam_Gider": "${:,.2f}",
                        "Kar": "${:,.2f}",
                        "Paket_Basi_Kar": "${:,.2f}",
                    }
                ).map(kar_zarar_stil, subset=["Kar", "Paket_Basi_Kar"]),
                width="stretch",
                hide_index=True,
            )
            indirme_butonlari(cb, "ulkeye_gore_analiz", "country_table")

        elif analiz_secimi == "Avrupa Ozeti":
            eu = europe_summary(merged)
            if eu:
                st.subheader("🌍 Avrupa Toplam Ozeti")
                st.caption(
                    "UK, Turkiye, Kibris, Israel dahil tum Avrupa ulkelerine ait gonderilerin toplu ozeti. "
                    "Dahil edilen ulkeler: " + " · ".join(eu["ulkeler"])
                )
                eu_col1, eu_col2, eu_col3 = st.columns(3)
                with eu_col1:
                    renkli_kart("Gonderi Sayisi (Tum)", f"{eu['gonderi_sayisi']:,}", "#6366f1", "📦")
                    renkli_kart("Eslesen Sayisi", f"{eu['eslesen_sayisi']:,}", "#8b5cf6", "✅")
                with eu_col2:
                    renkli_kart("Toplam Gelir (Tum)", f"${eu['toplam_gelir']:,.2f}", "#10b981", "💵")
                    renkli_kart("Eslesen Gelir", f"${eu['eslesen_gelir']:,.2f}", "#34d399", "💵")
                with eu_col3:
                    renkli_kart("Kargo Gideri", f"${eu['kargo_gideri']:,.2f}", "#f59e0b", "🚚")
                    renkli_kart("Vergi/Gumruk", f"${eu['vergi_gideri']:,.2f}", "#f97316", "🛂")
                eu_col4, eu_col5 = st.columns(2)
                with eu_col4:
                    renkli_kart("Toplam Gider", f"${eu['toplam_gider']:,.2f}", "#ef4444", "🧾")
                with eu_col5:
                    eu_renk = "#10b981" if eu["kar_zarar"] >= 0 else "#dc2626"
                    eu_icon = "📈" if eu["kar_zarar"] >= 0 else "📉"
                    renkli_kart("Kar/Zarar", f"${eu['kar_zarar']:,.2f}", eu_renk, eu_icon)
            else:
                st.info("Avrupa ulkelerine ait gonderi bulunamadi.")

        elif analiz_secimi == "Musterilere Gore":
            st.subheader("👥 Musteriye gore analiz")
            st.caption(
                "Gelir dosyasindaki User No / User Name'e gore musteri bazinda paket "
                "sayisi, bize odedigi tutar, firmaya odedigimiz tutar, kar/zarar ve "
                "gonderdigi ulkeler. Eslesen Sayisi/Firmaya Odenen/Kar sutunlari sadece "
                "ESLESEN gonderilerden gelir."
            )
            cust_table = customer_breakdown(merged)
            st.dataframe(
                cust_table.style.format(
                    {
                        "Bize Odenen (Gelir)": "${:,.2f}",
                        "Firmaya Odenen (Gider)": "${:,.2f}",
                        "Kar/Zarar": "${:,.2f}",
                        "Paket Basi Kar/Zarar": "${:,.2f}",
                    }
                ).map(kar_zarar_stil, subset=["Kar/Zarar", "Paket Basi Kar/Zarar"]),
                width="stretch",
                hide_index=True,
            )
            indirme_butonlari(cust_table, "musteriye_gore_analiz", "cust_table")

        elif analiz_secimi == "Musteri x Ulke":
            st.subheader("👥 Musteri x Ulke Analizi")
            st.caption(
                "Her musterinin HER ULKEDE ayri ayri kar mi zarar mi ettirdigini gosterir "
                "(en zararli kombinasyonlar basta). Genel toplamda kar gibi gorunen bir "
                "musteri, bazi ulkelerde zarar ettiriyor olabilir."
            )
            cust_country_table = customer_country_breakdown(merged)
            st.dataframe(
                cust_country_table.style.format(
                    {
                        "Gelir": "${:,.2f}",
                        "Gider": "${:,.2f}",
                        "Kar/Zarar": "${:,.2f}",
                    }
                ).map(kar_zarar_stil, subset=["Kar/Zarar"]),
                width="stretch",
                hide_index=True,
            )
            indirme_butonlari(cust_country_table, "musteri_x_ulke_analizi", "cust_country_table")

        elif analiz_secimi == "Detayli Rapor":
            st.subheader("📋 Detayli Rapor")
            detayli_rapor_df = merged.sort_values("Added Date")[
                [
                    "Shipment No", "Track Number", "Carrier Name", "Invoice Amount",
                    "Gider_Kargo", "Gider_Tax", "Gider", "Gider_Kalemleri", "Kar",
                ]
            ].rename(columns={
                "Gider_Kargo": "Kargo Gideri", "Gider_Tax": "Vergi/Gumruk",
                "Gider": "Toplam Gider", "Gider_Kalemleri": "Gider Kalemleri",
            })
            st.dataframe(
                detayli_rapor_df.style.format(
                    {"Invoice Amount": "${:,.2f}", "Kargo Gideri": "${:,.2f}",
                     "Vergi/Gumruk": "${:,.2f}", "Toplam Gider": "${:,.2f}", "Kar": "${:,.2f}"}
                ).map(kar_zarar_stil, subset=["Kar"]),
                width="stretch",
                hide_index=True,
            )
            indirme_butonlari(detayli_rapor_df, "detayli_rapor", "tab1")

        elif analiz_secimi == "Gider Bulunamayanlar":
            st.subheader("🔍 Gider Bulunamayanlar")
            not_found = merged[merged["Durum"] == "Gider bulunamadi"]
            st.caption(
                "Bu gonderiler icin takip numarasi var ama yuklenen gider dosyalarinda "
                "karsiligi bulunamadi. Henuz faturalanmamis olabilir, veya ait oldugu "
                "kargo firmasinin dosyasi yuklenmemis olabilir."
            )
            not_found_display = not_found[["Shipment No", "Track Number", "Carrier Name", "Status", "Invoice Amount"]]
            st.dataframe(not_found_display, width="stretch", hide_index=True)
            indirme_butonlari(not_found_display, "gider_bulunamayanlar", "tab2")

        elif analiz_secimi == "Eslesmeyen Gider":
            st.subheader("⚖️ Eslesmeyen Gider")
            st.caption(
                "Bu takip numaralari kargo firmasinin fatura listesinde var ama gelir "
                "dosyasinda eslesen bir gonderi bulunamadi. Farkli ay/musteri donemine "
                "ait olabilir, kontrol etmekte fayda var."
            )
            st.dataframe(unmatched_cost, width="stretch", hide_index=True)
            indirme_butonlari(unmatched_cost, "eslesmeyen_gider", "tab3")



        st.divider()

        # Excel export icin tum analizleri hesapla (sidebar seciminden bagimsiz)
        _carrier_table_export = carrier_breakdown(merged)
        _cb_export = country_breakdown(merged)
        _cust_table_export = customer_breakdown(merged)
        _cust_country_table_export = customer_country_breakdown(merged)

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            merged.drop(columns=["Takip_Var_Mi", "TrackingKey"]).to_excel(writer, sheet_name="Detayli Rapor", index=False)
            merged[merged["Durum"] == "Gider bulunamadi"].drop(columns=["Takip_Var_Mi", "TrackingKey"], errors="ignore").to_excel(
                writer, sheet_name="Gider Bulunamayan", index=False
            )
            unmatched_cost.to_excel(writer, sheet_name="Eslesmeyen Gider", index=False)
            if not full_breakdown.empty:
                full_breakdown.to_excel(writer, sheet_name="Kargo-Vergi Detayi", index=False)
            _cb_export.to_excel(writer, sheet_name="Ulke Bazinda", index=False)
            _carrier_table_export.to_excel(writer, sheet_name="Kargo Firmasi Bazinda", index=False)
            _cust_table_export.to_excel(writer, sheet_name="Musteri Bazinda", index=False)
            _cust_country_table_export.to_excel(writer, sheet_name="Musteri x Ulke", index=False)
            if manuel_gider_toplam:
                manual_expenses_df.to_excel(writer, sheet_name="Manuel Giderler", index=False)
            if has_per_package_fee:
                manual_carrier_expenses_df.to_excel(writer, sheet_name="Paket Basi Ek Gider", index=False)
            if manuel_gelir_toplam:
                manual_income_df.to_excel(writer, sheet_name="Manuel Gelirler", index=False)

        st.download_button(
            "Raporu Excel olarak indir",
            data=buffer.getvalue(),
            file_name="gelir_gider_raporu.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    elif "income_df_cache" not in st.session_state:
        st.info("Baslamak icin once gelir dosyasini yukleyin ve 'Hesapla' butonuna basin.")
