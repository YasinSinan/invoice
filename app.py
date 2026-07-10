"""
Depo gelir-gider karsilastirma araci.

Calistirmak icin:
    streamlit run app.py
"""

import io
from datetime import datetime, timezone

import altair as alt
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

# --------------------------------------------------------------- temalar ---
TEMALAR = {
    "Warmlime x Olive Ink": {"accent": "#a8c93a", "koyu": "#2b2f1e"},
    "Burnt Orange x Vanilla": {"accent": "#cc6a2e", "koyu": "#2e2013"},
    "Electric Orchid x Deep Plum": {"accent": "#d946c4", "koyu": "#2f0a38"},
    "Sky Mint x Graphite": {"accent": "#3ddc97", "koyu": "#24262a"},
    "Electric Indigo x Soft Lilac": {"accent": "#6f2dda", "koyu": "#241335"},
    "Neon Lime x Violet Ink": {"accent": "#c6ff00", "koyu": "#221333"},
}
_TEMA_SIRASI = list(TEMALAR.keys())

if "secili_tema" not in st.session_state:
    st.session_state["secili_tema"] = _TEMA_SIRASI[0]
if "tema_ters" not in st.session_state:
    st.session_state["tema_ters"] = False


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, int(v))):02x}" for v in rgb)


def _renk_karistir(hex1, hex2, oran):
    """hex1'i hex2 yonunde 'oran' (0-1) kadar karistirir."""
    r1, r2 = _hex_to_rgb(hex1), _hex_to_rgb(hex2)
    return _rgb_to_hex(tuple(a + (b - a) * oran for a, b in zip(r1, r2)))


def _parlaklik(h):
    r, g, b = _hex_to_rgb(h)
    return 0.299 * r + 0.587 * g + 0.114 * b


_ham_tema = TEMALAR[st.session_state["secili_tema"]]
if st.session_state["tema_ters"]:
    _accent, _koyu = _ham_tema["koyu"], _ham_tema["accent"]
else:
    _accent, _koyu = _ham_tema["accent"], _ham_tema["koyu"]

_tema = {
    "accent": _accent,
    "koyu": _koyu,
    "koyu2": _renk_karistir(_koyu, "#ffffff", 0.12),
    "yazi": "#1f2430" if _parlaklik(_accent) > 150 else "#ffffff",
    "sidebar_yazi": "#c3c9d4" if _parlaklik(_koyu) < 150 else "#2a2d33",
    "panel_bg": _renk_karistir("#f4f5f8", _accent, 0.05),
    "border_light": _renk_karistir("#c7cbd6", _accent, 0.22),
    "kart_bg": _renk_karistir("#ffffff", _accent, 0.02),
}

_accent_rgb = _hex_to_rgb(_tema["accent"])
_ACCENT_RGBA_16 = f"rgba({_accent_rgb[0]}, {_accent_rgb[1]}, {_accent_rgb[2]}, 0.16)"
_ACCENT_RGBA_08 = f"rgba({_accent_rgb[0]}, {_accent_rgb[1]}, {_accent_rgb[2]}, 0.08)"

# "Sellivox" tarzi acik panel temasi: koyu genis sidebar + beyaz ana alan +
# renkli sol-kenarlikli KPI kartlari.
_ana_css = """
    <style>
    :root {
        --panel-bg: %%PANEL_BG%%;
        --card-bg: %%KART_BG%%;
        --text-dark: #1f2430;
        --text-muted: #5f6779;
        --border-light: %%BORDER_LIGHT%%;
        --accent-blue: %%ACCENT%%;
        --sidebar-bg: %%KOYU%%;
        --sidebar-bg-2: %%KOYU2%%;
        --sidebar-text: %%SIDEBAR_YAZI%%;
    }

    /* Ana arka plan - acik gri */
    .stApp {
        background-color: var(--panel-bg) !important;
        color: var(--text-dark) !important;
    }

    .main .block-container,
    [data-testid="stMainBlockContainer"] {
        background-color: var(--panel-bg) !important;
        padding-top: 0 !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        max-width: 100% !important;
    }

    /* Streamlit'in ust bosluk birakan gizli header/toolbar alani.
       Not: yukseklik 0 yapilmiyor, cunku sidebar acma/kapama oku bu alanin
       icinde - sadece dekoratif kisimlar (renkli ust cizgi, deploy/menu
       araç çubugu) gizleniyor, ok butonu gorunur kaliyor. */
    [data-testid="stHeader"] {
        background: var(--panel-bg) !important;
        height: 0.6rem !important;
        min-height: 0.6rem !important;
        position: static !important;
        overflow: visible !important;
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

    /* Dosya yukleme alani (dropzone + yuklenen dosya satirlari) - lacivert
       zemin, acik renk yazi. Yuklenen dosyanin adi da bu alanin icinde
       render edildigi icin genis bir secici (stFileUploader) kullaniliyor. */
    [data-testid="stFileUploader"] {
        background-color: transparent !important;
    }
    [data-testid="stFileUploaderDropzone"] {
        background-color: var(--sidebar-bg) !important;
        border: 1px dashed var(--sidebar-bg-2) !important;
        border-radius: 10px !important;
    }
    [data-testid="stFileUploaderDropzone"] *,
    [data-testid="stFileUploader"] * {
        color: var(--sidebar-text) !important;
    }
    [data-testid="stFileUploaderDropzone"] svg,
    [data-testid="stFileUploader"] svg {
        fill: var(--sidebar-text) !important;
    }
    [data-testid="stFileUploaderDropzone"] small {
        color: var(--sidebar-text) !important;
        opacity: 0.75;
    }
    [data-testid="stFileUploaderDropzone"] button,
    [data-testid="stFileUploader"] button {
        background-color: var(--sidebar-bg-2) !important;
        color: var(--sidebar-text) !important;
        border: 1px solid var(--accent-blue) !important;
        border-radius: 6px !important;
    }
    [data-testid="stFileUploaderFile"],
    [data-testid="stFileUploaderFileName"] {
        background-color: var(--sidebar-bg) !important;
        color: var(--sidebar-text) !important;
        border-radius: 8px !important;
    }
    [data-testid="stFileUploaderFile"] *,
    [data-testid="stFileUploaderFileName"] * {
        color: var(--sidebar-text) !important;
    }

    /* Manuel giris tablolari (data_editor) - tema koyu rengi, acik renk yazi */
    [data-testid="stDataEditorGrid"],
    [data-testid="stDataFrameResizable"] canvas {
        background-color: var(--sidebar-bg) !important;
    }
    .stDataEditor [data-testid="stElementToolbar"] {
        background-color: var(--sidebar-bg) !important;
    }
    .stDataEditor {
        background-color: var(--sidebar-bg) !important;
        border: 1px solid var(--sidebar-bg-2) !important;
    }
    .stDataEditor * {
        color: var(--sidebar-text) !important;
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

    /* Sidebar - koyu, genis panel. Her zaman acik ve sabit genislikte kalir,
       kapatilamaz - boylece kapatma okunun gorunmemesi gibi sorunlar bir
       daha yasanmaz. */
    [data-testid="stSidebar"] {
        background-color: var(--sidebar-bg) !important;
        border-right: 1px solid #22252d !important;
        min-width: 248px !important;
        max-width: 248px !important;
        width: 248px !important;
        transform: none !important;
        visibility: visible !important;
        margin-left: 0 !important;
    }
    [data-testid="stSidebar"] * {
        color: var(--sidebar-text) !important;
    }

    /* Sidebar'i kapatma/acma oklari tamamen gizlendi - sidebar artik hep acik */
    [data-testid="stSidebarCollapseButton"],
    [data-testid="collapsedControl"] {
        display: none !important;
    }

    .stApp > header {
        background: var(--panel-bg) !important;
        border-bottom: 1px solid var(--border-light) !important;
    }

    [data-baseweb="select"] {
        background: var(--card-bg) !important;
    }
    [data-baseweb="select"] * {
        color: var(--text-dark) !important;
    }
    [data-baseweb="menu"] {
        background: var(--card-bg) !important;
        border: 1px solid var(--border-light) !important;
    }
    [data-baseweb="menu"] * {
        color: var(--text-dark) !important;
    }
    [data-baseweb="tag"] {
        background: var(--accent-blue) !important;
    }
    [data-baseweb="tag"] * {
        color: #ffffff !important;
    }
    [data-testid="stTooltipIcon"] svg {
        fill: var(--text-muted) !important;
    }
    </style>
    """

_ana_css = (
    _ana_css
    .replace("%%ACCENT%%", _tema["accent"])
    .replace("%%KOYU%%", _tema["koyu"])
    .replace("%%KOYU2%%", _tema["koyu2"])
    .replace("%%PANEL_BG%%", _tema["panel_bg"])
    .replace("%%KART_BG%%", _tema["kart_bg"])
    .replace("%%BORDER_LIGHT%%", _tema["border_light"])
    .replace("%%SIDEBAR_YAZI%%", _tema["sidebar_yazi"])
    .replace("%%ACCENT_RGBA_08%%", _ACCENT_RGBA_08)
)
st.markdown(_ana_css, unsafe_allow_html=True)

# ------------------------------------------------------------- giris (auth) ---
def _kullanicilari_yukle():
    """Streamlit Cloud Secrets'taki [auth] bolumunden kullanici bilgilerini
    okur. Secrets kurulmamissa acik ve anlasilir bir hata gosterir.

    Not: Daha once 'streamlit-authenticator' kutuphanesi kullaniliyordu, ama
    bu kutuphane (extra-streamlit-components uzerinden) her sayfa
    yuklemesinde otomatik olarak gorunmez bir cerez bileseni baslatiyordu -
    bu bilesen guncel Streamlit surumuyle uyumsuz calisip sayfayi tamamen
    bombos birakiyordu. Bu yuzden hicbir ucuncu parti bilesene ihtiyac
    duymayan, sade bir session_state tabanli sisteme gecildi."""
    try:
        auth_cfg = st.secrets["auth"]
        return dict(auth_cfg["credentials"]["usernames"])
    except Exception:
        st.error(
            "🔒 Giris sistemi henuz kurulmamis. Streamlit Cloud'da uygulama "
            "ayarlarindan **Secrets** bolumune `[auth]` yapilandirmasini "
            "eklemen gerekiyor. Claude'a 'secrets nasil eklenir' diye sorabilirsin."
        )
        st.stop()


_kullanicilar = _kullanicilari_yukle()

if not st.session_state.get("authentication_status"):
    st.markdown(
        """
        <style>
        [data-testid="stForm"] {
            background: #ffffff !important;
            border: 1.5px solid #c7cbd6 !important;
            border-radius: 16px !important;
            padding: 32px 28px !important;
            box-shadow: 0 4px 16px rgba(16, 24, 40, 0.10) !important;
        }
        [data-testid="stForm"] label p {
            color: #1f2430 !important;
            font-weight: 600 !important;
            font-size: 14px !important;
        }
        [data-testid="stForm"] input {
            color: #1f2430 !important;
            background: #f8f9fb !important;
            border: 1.5px solid #c7cbd6 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    _bos_sol, _form_orta, _bos_sag = st.columns([1, 1.1, 1])
    with _form_orta:
        st.markdown(
            """
            <div style="text-align:center; margin-bottom: 18px; margin-top: 6vh;">
                <div style="font-size: 40px;">📦</div>
                <div style="font-size: 22px; font-weight: 800; color: #1f2430;">Depo Paneli</div>
                <div style="font-size: 13px; color: #5f6779; margin-top: 2px;">Devam etmek icin giris yap</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        _sifre_goster = st.checkbox("👁️ Sifreyi goster", key="sifre_goster_toggle")

        with st.form("giris_formu", clear_on_submit=False, border=False):
            _email = st.text_input("Email", autocomplete="off", key="giris_email")
            _sifre = st.text_input(
                "Sifre",
                type="default" if _sifre_goster else "password",
                autocomplete="off",
                key="giris_sifre",
            )
            _gonderildi = st.form_submit_button("Giris Yap", type="primary", width="stretch")

        if _gonderildi:
            _kullanici = _kullanicilar.get(_email)
            if _kullanici and _sifre and _kullanici.get("password") == _sifre:
                st.session_state["authentication_status"] = True
                st.session_state["username"] = _email
                st.session_state["name"] = (
                    f"{_kullanici.get('first_name', '')} {_kullanici.get('last_name', '')}".strip()
                    or _email
                )
                st.rerun()
            else:
                st.error("Email veya sifre hatali.")

    st.stop()





def _hex_to_rgba(hex_renk, alpha):
    hex_renk = hex_renk.lstrip("#")
    r, g, b = int(hex_renk[0:2], 16), int(hex_renk[2:4], 16), int(hex_renk[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _dosya_listesine_ekle(liste_key, ad, veri_bytes, ekstra=None):
    """Ana Sayfa'daki gelir/gider dosya listesine (session_state) bir dosya
    ekler. Ayni isimde dosya varsa uzerine yazar (guncellenmis kabul edilir)."""
    mevcut = {d["ad"]: d for d in st.session_state.get(liste_key, [])}
    kayit = {"ad": ad, "bytes": veri_bytes}
    if ekstra:
        kayit.update(ekstra)
    mevcut[ad] = kayit
    st.session_state[liste_key] = list(mevcut.values())


def _dosya_listesinden_cikar(liste_key, ad):
    st.session_state[liste_key] = [
        d for d in st.session_state.get(liste_key, []) if d["ad"] != ad
    ]


def _her_seyi_sifirla():
    """Ana Sayfa'ya donerken yuklu dosyalari, hesaplanmis sonuclari, manuel
    giris tablolarini ve arsiv sayfalarindaki secimleri tamamen temizler -
    kullanici tertemiz bir sayfayla baslar. Giris (authentication) bilgilerine
    dokunulmaz."""
    _silinecek_anahtarlar = [
        "gelir_dosyalari",
        "gider_dosyalari",
        "income_df_cache",
        "cost_dfs_cache",
        "breakdown_dfs_cache",
        "carrier_overhead_cache",
        "warnings_cache",
        "hesapla_tiklandi",
        "yuklu_parametreler",
        "yuklu_donem",
        "manual_income_editor",
        "manual_expenses_editor",
        "manual_carrier_expenses_editor",
        "arsiv_donem_sec",
        "arsiv_gelir_secim",
        "arsiv_gider_secim",
        "tekli_arsiv_donem",
        "tekli_arsiv_secim",
        "arsiv_donem_input",
    ]
    for anahtar in _silinecek_anahtarlar:
        st.session_state.pop(anahtar, None)

    # Dosya yukleyici widget'larini da gorsel olarak sifirlamak icin
    # anahtarlarini bir sonraki surume geçiriyoruz (Streamlit dosya
    # yukleyicileri kod ile dogrudan bosaltilamaz, sadece key degisince
    # sifirlanir).
    st.session_state["gelir_uploader_versiyon"] = st.session_state.get("gelir_uploader_versiyon", 0) + 1
    st.session_state["gider_uploader_versiyon"] = st.session_state.get("gider_uploader_versiyon", 0) + 1


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


_tema_buton_css = """
    <style>
    [data-testid="stHorizontalBlock"]:has(#baslik-satiri) {
        align-items: center !important;
    }
    [data-testid="stHorizontalBlock"]:has(#tema-secici-satiri) {
        gap: 4px !important;
    }
    div[data-testid="stHorizontalBlock"]:has(#tema-secici-satiri) [data-testid="stButton"] button {
        width: 22px !important;
        height: 22px !important;
        min-width: 22px !important;
        padding: 0 !important;
        border-radius: 50% !important;
        font-size: 0 !important;
        line-height: 0 !important;
        box-shadow: 0 0 0 1px var(--border-light) !important;
    }
"""
for _i, _tema_adi in enumerate(_TEMA_SIRASI):
    _renkler = TEMALAR[_tema_adi]
    _tema_buton_css += f"""
    div[data-testid="stHorizontalBlock"]:has(#tema-secici-satiri) [data-testid="stButton"]:nth-of-type({_i + 1}) button {{
        background: linear-gradient(135deg, {_renkler['accent']} 50%, {_renkler['koyu']} 50%) !important;
        border: none !important;
    }}
    """
_secili_index = _TEMA_SIRASI.index(st.session_state["secili_tema"])
_tema_buton_css += f"""
    div[data-testid="stHorizontalBlock"]:has(#tema-secici-satiri) [data-testid="stButton"]:nth-of-type({_secili_index + 1}) button {{
        box-shadow: 0 0 0 2px var(--card-bg), 0 0 0 4px {_tema['accent']} !important;
    }}
    div[data-testid="stHorizontalBlock"]:has(#tema-secici-satiri) [data-testid="stButton"]:last-of-type button {{
        background: var(--card-bg) !important;
        box-shadow: 0 0 0 1px var(--border-light) !important;
        font-size: 12px !important;
    }}
    </style>
"""
st.markdown(_tema_buton_css, unsafe_allow_html=True)

# --------------------------------------------------------- tema secici ---
st.markdown('<span id="tema-secici-satiri"></span>', unsafe_allow_html=True)
_tema_kolonlari = st.columns([1] * len(_TEMA_SIRASI) + [1, 10])
for _i, _tema_adi in enumerate(_TEMA_SIRASI):
    with _tema_kolonlari[_i]:
        if st.button(" ", key=f"tema_sec_{_i}", help=_tema_adi):
            st.session_state["secili_tema"] = _tema_adi
            st.rerun()
with _tema_kolonlari[len(_TEMA_SIRASI)]:
    if st.button("⇄", key="tema_ters_cevir", help="Renkleri ters cevir"):
        st.session_state["tema_ters"] = not st.session_state["tema_ters"]
        st.rerun()

_col_baslik, _col_info, _col_btn = st.columns([3.2, 1.2, 0.6])
with _col_baslik:
    st.markdown(
        """
        <span id="baslik-satiri"></span>
        <div style="padding: 2px 0;">
            <div style="font-size: 24px; font-weight: 800; color: #1f2430; line-height: 1.2;">
                📦 Depo Paneli
            </div>
            <div style="font-size: 13px; color: #5f6779; margin-top: 2px;">
                Kargo faturalari ile musteri odemelerini otomatik eslestir
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with _col_info:
    st.markdown(
        f"""
        <div style="display: flex; align-items: center; justify-content: flex-end; gap: 8px; white-space: nowrap;">
            <div style="
                width: 28px; height: 28px;
                background: {_ACCENT_RGBA_16};
                border-radius: 50%;
                display: flex; align-items: center; justify-content: center;
                font-size: 13px;
                flex-shrink: 0;
                border: 1.5px solid {_tema['accent']};
            ">👤</div>
            <span style="font-size: 13px; font-weight: 700; color: #1f2430;">{st.session_state.get('name', '')}</span>
            <span style="font-size: 11px; color: #8a90a0;">· Giris yapildi</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
with _col_btn:
    if st.button("🚪 Cikis Yap", key="cikis_butonu"):
        for _k in ["authentication_status", "name", "username"]:
            st.session_state.pop(_k, None)
        st.rerun()

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
    ("🔎", "Takip No Sorgula"),
    ("💰", "Tahsil Edilmeyen Vergi/Gumruk"),
    ("📦", "Boyut/Agirlik Uyusmazligi"),
    ("🔍", "Gider Bulunamayanlar"),
    ("⚖️", "Eslesmeyen Gider"),
]
MENU_ITEMS = BASE_MENU_ITEMS + REPORT_MENU_ITEMS

if "analiz_secimi" not in st.session_state:
    st.session_state["analiz_secimi"] = None  # None = Ana Sayfa

with st.sidebar:
    _sidebar_css = """
        <style>
        [data-testid="stSidebar"] {
            min-width: 248px !important;
            max-width: 248px !important;
            background-color: %%KOYU%%;
            border-right: 1px solid #22252d;
        }
        [data-testid="stSidebar"] > div:first-child {
            padding: 0 !important;
        }
        [data-testid="stSidebarContent"] {
            padding-top: 0.25rem !important;
        }
        [data-testid="stSidebarContent"] [data-testid="stVerticalBlock"] {
            align-items: flex-start !important;
        }
        div[data-testid="stSidebarContent"] .stButton {
            width: 100% !important;
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
            color: var(--sidebar-text) !important;
            box-shadow: none !important;
            transition: background 0.15s;
            text-align: left !important;
        }
        div[data-testid="stSidebarContent"] .stButton button div {
            justify-content: flex-start !important;
            width: 100% !important;
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
            padding: 8px 18px 14px 18px;
            border-bottom: 1px solid #22252d;
            margin-bottom: 10px;
        }
        .sidebar-logo .box {
            width: 32px; height: 32px;
            background: linear-gradient(135deg, %%ACCENT%%, %%KOYU2%%);
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
        """
    _sidebar_css = (
        _sidebar_css
        .replace("%%ACCENT%%", _tema["accent"])
        .replace("%%KOYU%%", _tema["koyu"])
        .replace("%%KOYU2%%", _tema["koyu2"])
    )
    st.markdown(_sidebar_css, unsafe_allow_html=True)

    _aktif_etiket = st.session_state["analiz_secimi"] or "Ana Sayfa"
    _tum_etiketler = [label for _, label in MENU_ITEMS]
    if _aktif_etiket in _tum_etiketler:
        active_index = _tum_etiketler.index(_aktif_etiket)
        st.markdown(
            f"""
            <style>
            div[data-testid="stSidebarContent"] .stButton:nth-of-type({active_index + 1}) button {{
                background: {_ACCENT_RGBA_16} !important;
                color: #ffffff !important;
                box-shadow: inset 3px 0 0 {_tema['accent']} !important;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('<div class="sidebar-section">Ana Menu</div>', unsafe_allow_html=True)
    icon, label = BASE_MENU_ITEMS[0]
    if st.button(f"{icon}  {label}", key=f"nav_{label}", width="stretch"):
        _her_seyi_sifirla()
        st.session_state["analiz_secimi"] = None
        st.rerun()

    st.markdown('<div class="sidebar-section">Dosya Islemleri</div>', unsafe_allow_html=True)
    for icon, label in BASE_MENU_ITEMS[1:]:
        if st.button(f"{icon}  {label}", key=f"nav_{label}", width="stretch"):
            st.session_state["analiz_secimi"] = label
            st.rerun()

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
            with st.spinner("📤 GitHub'a kaydediliyor..."):
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
        with st.spinner("🔄 GitHub'daki donemler yukleniyor..."):
            _kayitli_donemler = list_periods()
    except GithubStorageError as e:
        _kayitli_donemler = []
        st.warning(str(e))

    if not _kayitli_donemler:
        st.info("Henuz arsivlenmis bir donem yok. 'Kargo Firmasina Gore Dosya Yukle' bolumunden dosyalarini arsivleyebilirsin.")
    else:
        _secilen_arsiv_donemi = st.selectbox("Donem sec", options=_kayitli_donemler, key="arsiv_donem_sec")

        try:
            with st.spinner(f"🔄 '{_secilen_arsiv_donemi}' donemine ait dosya listesi yukleniyor..."):
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
            help="Dosyalari Ana Sayfa'daki yukleme alanlarina ekler ve yonlendirir - orada dosya ekleyip/cikarabilir, sonra Hesapla'ya basabilirsin.",
        ):
            try:
                with st.spinner(
                    f"📥 {len(_secili_gelir_dosyalari) + len(_secili_gider_dosyalari)} dosya GitHub'dan indiriliyor..."
                ):
                    for gelir_dosya in _secili_gelir_dosyalari:
                        gelir_bytes = load_raw_file(_secilen_arsiv_donemi, "gelir", gelir_dosya)
                        _dosya_listesine_ekle("gelir_dosyalari", gelir_dosya, gelir_bytes)

                    for gider_dosya in _secili_gider_dosyalari:
                        gider_bytes = load_raw_file(_secilen_arsiv_donemi, "gider", gider_dosya)
                        secilen_carrier = _gider_carrier_map_ekran.get(gider_dosya, BYELABEL_GROUP_LABEL)
                        _dosya_listesine_ekle(
                            "gider_dosyalari", gider_dosya, gider_bytes, {"firma": secilen_carrier}
                        )

                st.session_state["analiz_secimi"] = None
                st.success(
                    f"'{_secilen_arsiv_donemi}' donemi dosyalari Ana Sayfa'daki yukleme "
                    "alanlarina eklendi. Istersen baska dosya da ekleyip 'Hesapla'ya bas."
                )
                st.rerun()
            except GithubStorageError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Dosyalar yuklenirken hata olustu: {e}")

# ------------------------------------------------------------- ana sayfa ---
else:

    _rapor_etiketleri_tumu = [label for _, label in REPORT_MENU_ITEMS]
    if analiz_secimi in _rapor_etiketleri_tumu and not _hesapla_var:
        st.warning("⚠️ Once dosyalarini yukleyip 'Hesapla'ya basmalisin. Asagida dosyalarini yukleyebilirsin.")

    # Yuklu parametreler varsa widget varsayilan degerlerine uygula
    _params = st.session_state.get("yuklu_parametreler", {})

    # ---------------------------------------------------------------- yukleme ---
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Gelir")
        st.caption("WH_CUSTOMER_SHIPMENT_LIST formatinda, musteriden alinan tutarlari iceren dosya.")

        if "gelir_dosyalari" not in st.session_state:
            st.session_state["gelir_dosyalari"] = []
        if "gelir_uploader_versiyon" not in st.session_state:
            st.session_state["gelir_uploader_versiyon"] = 0

        _gelir_listesi = st.session_state["gelir_dosyalari"]
        if _gelir_listesi:
            for _d in list(_gelir_listesi):
                _c1, _c2 = st.columns([6, 1])
                _c1.markdown(f"📄 {_d['ad']}")
                if _c2.button("🗑️", key=f"gelir_sil_{_d['ad']}", help="Listeden cikar"):
                    _dosya_listesinden_cikar("gelir_dosyalari", _d["ad"])
                    st.rerun()

        _yeni_gelir_dosyalari = st.file_uploader(
            "Gelir Excel dosyasi ekle" if _gelir_listesi else "Gelir Excel dosyasini secin",
            type=["xlsx"],
            accept_multiple_files=True,
            key=f"income_uploader_{st.session_state['gelir_uploader_versiyon']}",
        )
        if _yeni_gelir_dosyalari:
            for _f in _yeni_gelir_dosyalari:
                _dosya_listesine_ekle("gelir_dosyalari", _f.name, _f.getvalue())
            st.session_state["gelir_uploader_versiyon"] += 1
            st.rerun()

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

        if "gider_dosyalari" not in st.session_state:
            st.session_state["gider_dosyalari"] = []
        if "gider_uploader_versiyon" not in st.session_state:
            st.session_state["gider_uploader_versiyon"] = 0

        _tum_firma_secenekleri = list(CARRIER_PROFILES.keys()) + [BYELABEL_GROUP_LABEL]
        _gider_listesi = st.session_state["gider_dosyalari"]
        if _gider_listesi:
            for _d in list(_gider_listesi):
                _c1, _c2, _c3 = st.columns([4, 3, 1])
                _c1.markdown(f"📄 {_d['ad']}")
                _mevcut_firma = _d.get("firma", BYELABEL_GROUP_LABEL)
                _yeni_firma = _c2.selectbox(
                    "Firma",
                    options=_tum_firma_secenekleri,
                    index=_tum_firma_secenekleri.index(_mevcut_firma) if _mevcut_firma in _tum_firma_secenekleri else 0,
                    key=f"gider_firma_{_d['ad']}",
                    label_visibility="collapsed",
                )
                if _yeni_firma != _mevcut_firma:
                    _d["firma"] = _yeni_firma
                    st.session_state["gider_dosyalari"] = _gider_listesi
                if _c3.button("🗑️", key=f"gider_sil_{_d['ad']}", help="Listeden cikar"):
                    _dosya_listesinden_cikar("gider_dosyalari", _d["ad"])
                    st.rerun()

        _yeni_gider_dosyalari = st.file_uploader(
            "Gider Excel dosyasi ekle" if _gider_listesi else "Gider Excel dosyasini/dosyalarini secin",
            type=["xlsx"],
            accept_multiple_files=True,
            key=f"cost_uploader_{st.session_state['gider_uploader_versiyon']}",
        )
        if _yeni_gider_dosyalari:
            for _f in _yeni_gider_dosyalari:
                _dosya_listesine_ekle(
                    "gider_dosyalari", _f.name, _f.getvalue(), {"firma": BYELABEL_GROUP_LABEL}
                )
            st.session_state["gider_uploader_versiyon"] += 1
            st.rerun()

        if _gider_listesi:
            st.caption(
                "Su an Asendia, UniUni, UPS ve Asendia'nin ayri Vergi/Gumruk dosyasi "
                "dogrudan destekleniyor. ByeLabel dosyasini (shipments-...xlsx) sectiginde "
                "icindeki tum firmalar (ePost Global, DHL, intelcom, APC, USPS, Evri, "
                "Purolator, FedEx, UPS) otomatik ayri ayri islenir."
            )

        dahil_et_genel_gider = True  # Pakete baglanamayan giderler bilgi amacli gosterilir, otomatik eklenmez

        st.markdown("**Manuel gider (opsiyonel)**")
        st.caption(
            "Hicbir pakete baglanmayan, dogrudan net kardan dusulecek giderler "
            "(orn. depo kirasi, personel maasi, internet faturasi)."
        )
        _gider_default = pd.DataFrame(_params.get("manuel_gider", [])) if _params else pd.DataFrame({"Aciklama": pd.Series(dtype="str"), "Tutar": pd.Series(dtype="float")})
        if _gider_default.empty or list(_gider_default.columns) != ["Aciklama", "Tutar"]:
            _gider_default = pd.DataFrame({"Aciklama": pd.Series(dtype="str"), "Tutar": pd.Series(dtype="float")})

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

    _bos_sol, _hesapla_orta, _bos_sag = st.columns([1, 1, 1])
    with _hesapla_orta:
        if st.button(
            "Hesapla",
            type="primary",
            disabled=not st.session_state.get("gelir_dosyalari"),
            width="stretch",
        ):
            with st.spinner("⏳ Dosyalar okunuyor ve hesaplaniyor..."):
                # Dosyalari oku ve session_state'e kaydet
                try:
                    _gelir_dfs = []
                    for _d in st.session_state["gelir_dosyalari"]:
                        _gelir_dfs.append(
                            load_income_file(
                                io.BytesIO(_d["bytes"]),
                                only_paid=only_paid,
                                exclude_unassigned_carrier=exclude_unassigned_carrier,
                            )
                        )
                    st.session_state["income_df_cache"] = pd.concat(_gelir_dfs, ignore_index=True)
                except ValueError as e:
                    st.error(f"Gelir dosyasi okunamadi: {e}")
                    st.stop()

                cost_dfs = []
                warnings_list = []
                carrier_overhead_toplam = 0.0
                breakdown_dfs = []
                for _d in st.session_state.get("gider_dosyalari", []):
                    try:
                        secilen = _d.get("firma", BYELABEL_GROUP_LABEL)
                        if secilen == BYELABEL_GROUP_LABEL:
                            group_cost_dfs, group_warnings, group_genel_gider, group_breakdown_dfs = load_byelabel_group(
                                io.BytesIO(_d["bytes"])
                            )
                            cost_dfs.extend(group_cost_dfs)
                            warnings_list.extend(group_warnings)
                            if group_genel_gider:
                                carrier_overhead_toplam += group_genel_gider
                            for bd in group_breakdown_dfs:
                                breakdown_dfs.append(bd)
                        else:
                            cost_df, warning, genel_gider, breakdown_df = load_cost_file(
                                io.BytesIO(_d["bytes"]), secilen
                            )
                            cost_dfs.append(cost_df)
                            if warning:
                                warnings_list.append(warning)
                            if genel_gider:
                                carrier_overhead_toplam += genel_gider
                            if not breakdown_df.empty:
                                breakdown_dfs.append(breakdown_df)
                    except ValueError as e:
                        st.error(f"{_d['ad']} okunamadi: {e}")
                        st.stop()

                st.session_state["cost_dfs_cache"] = cost_dfs
                st.session_state["breakdown_dfs_cache"] = breakdown_dfs
                st.session_state["carrier_overhead_cache"] = carrier_overhead_toplam
                st.session_state["warnings_cache"] = warnings_list
                st.session_state["hesapla_tiklandi"] = True

    # ---------------------------------------------------------------- hesapla ---
    if st.session_state.get("hesapla_tiklandi") and "income_df_cache" in st.session_state:

        # Dosyalari her seferinde yeniden yuklemek yerine cache'den al.
        # "Hesapla" butonuna basildiginda cache guncellenir; sayfa tekrar
        # render edildiginde (orn. filtre degisince) asagidaki blok mevcut
        # dosya listesinden guncel filtrelerle income_df'i yeniden hesaplar.
        income_df = st.session_state["income_df_cache"]
        cost_dfs = st.session_state["cost_dfs_cache"]
        breakdown_dfs = st.session_state["breakdown_dfs_cache"]
        carrier_overhead_toplam = st.session_state["carrier_overhead_cache"]

        # Filtreler degismisse gelir dosyalarini cache'deki listeden yeniden isle
        # (only_paid / exclude_unassigned_carrier degisebilir - bunlar dosya
        # okumadan ayri hesaplama adimi oldugu icin burada uygulanir)
        if st.session_state.get("gelir_dosyalari"):
            try:
                _gelir_dfs_yeniden = [
                    load_income_file(
                        io.BytesIO(_d["bytes"]),
                        only_paid=only_paid,
                        exclude_unassigned_carrier=exclude_unassigned_carrier,
                    )
                    for _d in st.session_state["gelir_dosyalari"]
                ]
                income_df = pd.concat(_gelir_dfs_yeniden, ignore_index=True)
            except Exception:
                pass  # cache'dekini kullanmaya devam et

        for w in st.session_state.get("warnings_cache", []):
            st.warning(w)

        # Pakete baglanamayan giderler (Brokerage/Government Charges vb.)
        # artik otomatik olarak manuel gider listesine eklenmiyor. Kullanici
        # isterse bunlari kendisi manuel gider tablosuna elle girebilir.
        full_breakdown_erken = pd.concat(breakdown_dfs, ignore_index=True) if breakdown_dfs else pd.DataFrame()

        manuel_gider_toplam = manual_expense_total(manual_expenses_df)
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

        renkli_kart("Toplam Paket Sayisi", f"{summary['toplam_gonderi']:,}", _tema["accent"], "📦")

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
        gecerli_manuel_gider_gosterim = gecerli_manuel_gider

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
        _, kar_orta, kar_yuzde_orta, _ = st.columns([1, 1, 1, 1])
        with kar_orta:
            net_kar_renk = "#10b981" if summary["net_kar"] >= 0 else "#dc2626"
            net_kar_icon = "📈" if summary["net_kar"] >= 0 else "📉"
            renkli_kart("Net Kar", f"${summary['net_kar']:,.2f}", net_kar_renk, net_kar_icon)
        with kar_yuzde_orta:
            renkli_kart("Net Kar Yuzdesi (%)", f"%{summary['net_kar_yuzde']:,.1f}", net_kar_renk, net_kar_icon)

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

            _genel_gider_toplam = genel_gider_kategori_detay["Genel Gider"].sum()
            st.markdown(
                f"""
                <div style="display: flex; justify-content: flex-end; margin-top: -6px;">
                    <div style="
                        background: #ffffff;
                        border: 1.5px solid #c7cbd6;
                        border-radius: 8px;
                        padding: 8px 16px;
                        font-size: 14px;
                    ">
                        <span style="color: #5f6779; font-weight: 600;">Toplam:</span>
                        <span style="color: #1f2430; font-weight: 800; margin-left: 6px;">${_genel_gider_toplam:,.2f}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
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
                        "Kar Yuzdesi (%)": "{:,.1f}%",
                    }
                ).map(kar_zarar_stil, subset=["Kar/Zarar", "Paket Basi Kar/Zarar", "Kar Yuzdesi (%)"]),
                width="stretch",
                hide_index=True,
            )
            indirme_butonlari(carrier_table, "kargo_firmasi_analizi", "carrier_table")

            if not carrier_table.empty:
                st.markdown("**📊 Kargo firmasina gore Kar/Zarar**")
                _carrier_chart_df = carrier_table[["Kargo Firmasi", "Kar/Zarar"]].copy()
                _carrier_chart_df["Renk"] = _carrier_chart_df["Kar/Zarar"].apply(
                    lambda v: "Kar" if v >= 0 else "Zarar"
                )
                _carrier_chart = (
                    alt.Chart(_carrier_chart_df)
                    .mark_bar()
                    .encode(
                        x=alt.X("Kar/Zarar:Q", title="Kar/Zarar ($)"),
                        y=alt.Y("Kargo Firmasi:N", sort="-x", title=None),
                        color=alt.Color(
                            "Renk:N",
                            scale=alt.Scale(domain=["Kar", "Zarar"], range=["#10b981", "#dc2626"]),
                            legend=None,
                        ),
                        tooltip=["Kargo Firmasi", alt.Tooltip("Kar/Zarar:Q", format="$,.2f")],
                    )
                    .properties(height=max(120, 32 * len(_carrier_chart_df)))
                )
                st.altair_chart(_carrier_chart, width="stretch")

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
                        "Kar_Yuzde": "{:,.1f}%",
                    }
                ).map(kar_zarar_stil, subset=["Kar", "Paket_Basi_Kar", "Kar_Yuzde"]),
                width="stretch",
                hide_index=True,
            )
            indirme_butonlari(cb, "ulkeye_gore_analiz", "country_table")

            if not cb.empty:
                st.markdown("**📊 En cok gelir getiren 10 ulke**")
                _cb_top = cb.nlargest(10, "Toplam_Gelir")[["Ulke", "Toplam_Gelir", "Kar"]]
                _cb_chart = (
                    alt.Chart(_cb_top)
                    .mark_bar(color=_tema["accent"])
                    .encode(
                        x=alt.X("Toplam_Gelir:Q", title="Toplam Gelir ($)"),
                        y=alt.Y("Ulke:N", sort="-x", title=None),
                        tooltip=["Ulke", alt.Tooltip("Toplam_Gelir:Q", format="$,.2f"), alt.Tooltip("Kar:Q", format="$,.2f")],
                    )
                    .properties(height=max(120, 32 * len(_cb_top)))
                )
                st.altair_chart(_cb_chart, width="stretch")

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
                    renkli_kart("Gonderi Sayisi (Tum)", f"{eu['gonderi_sayisi']:,}", _tema["accent"], "📦")
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
                    renkli_kart("Kar Yuzdesi (%)", f"%{eu['kar_yuzde']:,.1f}", eu_renk, eu_icon)
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
                        "Kar Yuzdesi (%)": "{:,.1f}%",
                    }
                ).map(kar_zarar_stil, subset=["Kar/Zarar", "Paket Basi Kar/Zarar", "Kar Yuzdesi (%)"]),
                width="stretch",
                hide_index=True,
            )
            indirme_butonlari(cust_table, "musteriye_gore_analiz", "cust_table")

            if not cust_table.empty:
                st.markdown("**📊 En cok gelir getiren 10 musteri**")
                _cust_top = cust_table.nlargest(10, "Bize Odenen (Gelir)")[
                    ["Musteri Adi", "Bize Odenen (Gelir)", "Kar/Zarar"]
                ]
                _cust_chart = (
                    alt.Chart(_cust_top)
                    .mark_bar(color=_tema["accent"])
                    .encode(
                        x=alt.X("Bize Odenen (Gelir):Q", title="Bize Odenen ($)"),
                        y=alt.Y("Musteri Adi:N", sort="-x", title=None),
                        tooltip=[
                            "Musteri Adi",
                            alt.Tooltip("Bize Odenen (Gelir):Q", format="$,.2f"),
                            alt.Tooltip("Kar/Zarar:Q", format="$,.2f"),
                        ],
                    )
                    .properties(height=max(120, 32 * len(_cust_top)))
                )
                st.altair_chart(_cust_chart, width="stretch")

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
                        "Kar Yuzdesi (%)": "{:,.1f}%",
                    }
                ).map(kar_zarar_stil, subset=["Kar/Zarar", "Kar Yuzdesi (%)"]),
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

        elif analiz_secimi == "Takip No Sorgula":
            st.subheader("🔎 Takip No Sorgula")
            st.caption(
                "Bir veya birden fazla takip numarasi gir (her satira bir tane, "
                "veya virgulle ayirarak da yazabilirsin) - gelir ve giderini "
                "yan yana, her biri alt alta gorursun."
            )
            _takip_girdi = st.text_area(
                "Takip numaralari",
                placeholder="orn.\n1Z999AA10123456784\n1Z999AA10123456785\n... (10'a kadar veya daha fazla)",
                height=140,
                key="takip_no_sorgu_girdi",
            )

            if st.button("🔎 Sorgula", type="primary", key="takip_no_sorgula_btn"):
                _ham_liste = [
                    p.strip()
                    for parca in _takip_girdi.splitlines()
                    for p in parca.split(",")
                ]
                _takip_listesi = [t for t in _ham_liste if t]

                if not _takip_listesi:
                    st.warning("Once en az bir takip numarasi gir.")
                else:
                    _sonuc_satirlari = []
                    for _tn in _takip_listesi:
                        _eslesen = merged[
                            merged["Track Number"].astype(str).str.strip().str.lower() == _tn.lower()
                        ]
                        if _eslesen.empty:
                            _sonuc_satirlari.append({
                                "Takip No": _tn,
                                "Durum": "Bulunamadi",
                                "Kargo Firmasi": "-",
                                "Musteri": "-",
                                "Ulke": "-",
                                "Gelir": None,
                                "Gider": None,
                                "Kar/Zarar": None,
                            })
                        else:
                            for _, _satir in _eslesen.iterrows():
                                _sonuc_satirlari.append({
                                    "Takip No": _tn,
                                    "Durum": _satir["Durum"],
                                    "Kargo Firmasi": _satir["Carrier Name"],
                                    "Musteri": _satir.get("User Name", "-"),
                                    "Ulke": _satir.get("Receiver Country", "-"),
                                    "Gelir": _satir["Invoice Amount"],
                                    "Gider": _satir["Gider"] if pd.notna(_satir["Gider"]) else None,
                                    "Kar/Zarar": _satir["Kar"] if pd.notna(_satir["Kar"]) else None,
                                })

                    _sonuc_df = pd.DataFrame(_sonuc_satirlari)
                    _bulunan_sayisi = (_sonuc_df["Durum"] != "Bulunamadi").sum()
                    st.caption(f"{len(_takip_listesi)} takip numarasi sorgulandi, {_bulunan_sayisi} tanesi bulundu.")

                    st.dataframe(
                        _sonuc_df.style.format(
                            {"Gelir": "${:,.2f}", "Gider": "${:,.2f}", "Kar/Zarar": "${:,.2f}"},
                            na_rep="-",
                        ).map(kar_zarar_stil, subset=["Kar/Zarar"]),
                        width="stretch",
                        hide_index=True,
                    )
                    indirme_butonlari(_sonuc_df, "takip_no_sorgu_sonuclari", "takip_sorgu")

        elif analiz_secimi == "Tahsil Edilmeyen Vergi/Gumruk":
            st.subheader("💰 Tahsil Edilmeyen Vergi/Gumruk")
            st.caption(
                "Kargo firmasina odedigimiz vergi/gumruk (Gider_Tax) ile musteriden "
                "gelir dosyasindaki 'Customs Duty Fee' sutunundan tahsil ettigimiz "
                "tutari karsilastirir. Odedigimizden AZ tahsil ettigimiz (veya hic "
                "tahsil etmedigimiz) gonderileri listeler."
            )

            _vergi_df = merged[merged["Durum"] == "Eslesti"].copy()
            _vergi_df["Musteriden_Alinan_Vergi"] = _vergi_df["Musteriden_Alinan_Vergi"].fillna(0.0)
            _vergi_df["Odenen_Vergi"] = _vergi_df["Gider_Tax"].fillna(0.0)
            _vergi_df["Fark"] = _vergi_df["Odenen_Vergi"] - _vergi_df["Musteriden_Alinan_Vergi"]

            _eksik_tahsilat = _vergi_df[_vergi_df["Fark"] > 0.01][
                [
                    "Track Number", "Carrier Name", "User No", "User Name", "Receiver Country",
                    "Odenen_Vergi", "Musteriden_Alinan_Vergi", "Fark",
                ]
            ].rename(columns={
                "Track Number": "Takip No",
                "Carrier Name": "Kargo Firmasi",
                "User No": "Musteri No",
                "User Name": "Musteri",
                "Receiver Country": "Ulke",
                "Odenen_Vergi": "Firmaya Odenen Vergi",
                "Musteriden_Alinan_Vergi": "Musteriden Tahsil Edilen",
                "Fark": "Eksik Tahsilat",
            }).sort_values("Eksik Tahsilat", ascending=False)

            if _eksik_tahsilat.empty:
                st.success("Butun eslesen gonderilerde vergi/gumruk tam tahsil edilmis gorunuyor. 🎉")
            else:
                _toplam_eksik = _eksik_tahsilat["Eksik Tahsilat"].sum()
                renkli_kart(
                    "Toplam Eksik Tahsilat", f"${_toplam_eksik:,.2f}", "#dc2626", "⚠️"
                )
                st.caption(f"{len(_eksik_tahsilat)} gonderide musteriden eksik vergi/gumruk tahsil edilmis.")
                st.dataframe(
                    _eksik_tahsilat.style.format(
                        {
                            "Firmaya Odenen Vergi": "${:,.2f}",
                            "Musteriden Tahsil Edilen": "${:,.2f}",
                            "Eksik Tahsilat": "${:,.2f}",
                        }
                    ).map(
                        lambda v: "background-color: rgba(220, 38, 38, 0.08); color: #b91c1c; font-weight: 700;",
                        subset=["Eksik Tahsilat"],
                    ),
                    width="stretch",
                    hide_index=True,
                )
                indirme_butonlari(_eksik_tahsilat, "tahsil_edilmeyen_vergi", "vergi_farki")

        elif analiz_secimi == "Boyut/Agirlik Uyusmazligi":
            st.subheader("📦 Boyut/Agirlik Uyusmazligi (Zarar Eden Paketler)")
            st.caption(
                "Musteriye beyan ettigimiz (gelir dosyasindaki) boyut/agirlik ile "
                "kargo firmasinin faturasindaki olculen boyut/agirligi karsilastirir. "
                "Sadece ZARAR ettigimiz (Kar/Zarar < 0) ve firmanin boyut verisi olan "
                "gonderileri gosterir - genelde firma bizim beyan ettigimizden daha "
                "buyuk/agir olcup daha fazla ucret yansittiginda zarar olusur.\n\n"
                "⚠️ Not: Su an sadece **FedEx, Asendia ve UniUni** fatura dosyalarinda "
                "boyut/agirlik bilgisi bulunuyor. UPS ve ByeLabel grubu firmalarinin "
                "fatura formatlarinda bu bilgi yok, bu yuzden o gonderiler bu listede "
                "gorunmez."
            )

            _boyut_df = merged[
                (merged["Durum"] == "Eslesti")
                & (merged["Kar"] < 0)
                & (merged["Firma_Weight"].notna())
            ].copy()

            if _boyut_df.empty:
                st.success("Zarar eden ve firma boyut verisi olan bir gonderi bulunamadi. 🎉")
            else:
                _boyut_tablo = _boyut_df[[
                    "Track Number", "Carrier Name", "User Name",
                    "Musteri_Weight", "Firma_Weight",
                    "Musteri_Length", "Firma_Length",
                    "Musteri_Width", "Firma_Width",
                    "Musteri_Height", "Firma_Height",
                    "Kar",
                ]].rename(columns={
                    "Track Number": "Takip No",
                    "Carrier Name": "Kargo Firmasi",
                    "User Name": "Musteri",
                    "Musteri_Weight": "Bizim Agirlik",
                    "Firma_Weight": "Firma Agirlik",
                    "Musteri_Length": "Bizim Uzunluk",
                    "Firma_Length": "Firma Uzunluk",
                    "Musteri_Width": "Bizim Genislik",
                    "Firma_Width": "Firma Genislik",
                    "Musteri_Height": "Bizim Yukseklik",
                    "Firma_Height": "Firma Yukseklik",
                    "Kar": "Kar/Zarar",
                }).sort_values("Kar/Zarar")
                _boyut_tablo["Takip No"] = _boyut_tablo["Takip No"].astype(str)

                renkli_kart(
                    "Zarar Eden Boyut Uyusmazlikli Paket Sayisi", f"{len(_boyut_tablo)}", "#dc2626", "📦"
                )
                st.caption(
                    f"Toplam zarar: ${_boyut_tablo['Kar/Zarar'].sum():,.2f} "
                    f"({len(_boyut_tablo)} gonderi)"
                )

                st.dataframe(
                    _boyut_tablo.style.format(
                        {
                            "Bizim Agirlik": "{:,.2f}",
                            "Firma Agirlik": "{:,.2f}",
                            "Bizim Uzunluk": "{:,.1f}",
                            "Firma Uzunluk": "{:,.1f}",
                            "Bizim Genislik": "{:,.1f}",
                            "Firma Genislik": "{:,.1f}",
                            "Bizim Yukseklik": "{:,.1f}",
                            "Firma Yukseklik": "{:,.1f}",
                            "Kar/Zarar": "${:,.2f}",
                        },
                        na_rep="-",
                    ).map(kar_zarar_stil, subset=["Kar/Zarar"]),
                    width="stretch",
                    hide_index=True,
                )
                indirme_butonlari(_boyut_tablo, "boyut_agirlik_uyusmazligi", "boyut_uyusmazlik")

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
