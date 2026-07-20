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
    load_income_file_fba,
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

# --------------------------------------------------------------- dil (i18n) ---
if "dil" not in st.session_state:
    st.session_state["dil"] = "tr"

CEVIRI = {
    "tr": {
        "app_baslik": "Depo Paneli",
        "app_altbaslik": "Kargo faturalari ile musteri odemelerini otomatik eslestir",
        "giris_yapildi": "Giris yapildi",
        "cikis_yap": "🚪 Cikis Yap",
        "ana_sayfa": "Ana Sayfa",
        "kargo_dosya_yukle": "Kargo Firmasina Gore Dosya Yukle",
        "github_arsiv_sec": "GitHub Arsivinden Dosya Sec ve Hesapla",
        "ana_menu": "Ana Menu",
        "dosya_islemleri": "Dosya Islemleri",
        "raporlar": "Raporlar",
        "kargo_firmalarina_gore": "Kargo Firmalarina Gore",
        "ulkelere_gore": "Ulkelere Gore",
        "avrupa_ozeti": "Avrupa Ozeti",
        "musterilere_gore": "Musterilere Gore",
        "musteri_x_ulke": "Musteri x Ulke",
        "detayli_rapor": "Detayli Rapor",
        "takip_no_sorgula": "Takip No Sorgula",
        "tahsil_edilmeyen_vergi": "Tahsil Edilmeyen Vergi/Gumruk",
        "boyut_agirlik": "Boyut/Agirlik Uyusmazligi",
        "gider_bulunamayanlar": "Gider Bulunamayanlar",
        "eslesmeyen_gider": "Eslesmeyen Gider",
        "hesap": "Hesap",
        "email": "Email",
        "sifre": "Sifre",
        "sifreyi_goster": "👁️ Sifreyi goster",
        "giris_yap": "Giris Yap",
        "giris_devam": "Devam etmek icin giris yap",
        "email_sifre_hatali": "Email veya sifre hatali.",
        "gelir": "Gelir",
        "gider": "Gider",
        "hesapla": "Hesapla",
        "yukleniyor": "⏳ Dosyalar okunuyor ve hesaplaniyor...",
        "indir_excel": "Excel olarak indir",
        "indir_csv": "CSV olarak indir",
        "toplam": "Toplam",
        "musteri": "Musteri",
        "ulke": "Ulke",
        "kargo_firmasi": "Kargo Firmasi",
        "takip_no": "Takip No",
        "kar_zarar": "Kar/Zarar",
        "toplam_gelir": "Toplam Gelir",
        "toplam_gider": "Toplam Gider",
        "net_kar": "Net Kar",
        "toplam_paket_sayisi": "Toplam Paket Sayisi",
        "ozet": "📊 Ozet",
        "kargo_analiz_baslik": "🚚 Kargo Firmalarina Gore Analiz",
        "ulke_analiz_baslik": "🌍 Ulkeye gore analiz",
        "avrupa_toplam_ozeti": "🌍 Avrupa Toplam Ozeti",
        "musteri_analiz_baslik": "👥 Musteriye gore analiz",
        "musteri_ulke_analiz_baslik": "👥 Musteri x Ulke Analizi",
        "kargo_yukle_baslik": "📤 Kargo Firmasina Gore Dosya Yukle",
        "github_arsiv_baslik": "🗄️ GitHub Arsivinden Dosya Sec ve Hesapla",
        "detayli_rapor_baslik": "📋 Detayli Rapor",
        "takip_sorgula_baslik": "🔎 Takip No Sorgula",
        "tahsil_edilmeyen_baslik": "💰 Tahsil Edilmeyen Vergi/Gumruk",
        "boyut_agirlik_baslik": "📦 Boyut/Agirlik Uyusmazligi (Zarar Eden Paketler)",
        "gider_bulunamayan_baslik": "🔍 Gider Bulunamayanlar",
        "eslesmeyen_gider_baslik": "⚖️ Eslesmeyen Gider",
        "eslesme_orani_metni": "Eslesme orani: %{oran:.1f}",
        "toplam_gonderi_ozet": "Toplam {toplam} gonderi  |  {eslesen} eslesti  |  {bulunamadi} gider bulunamadi  |  {takipsiz} takip no yok",
        "kaynak_kolon_metni": "📂 {firma} icin kaynak kolon: *{sutun}*",
        "avrupa_ozet_metni": "UK, Turkiye, Kibris, Israel dahil tum Avrupa ulkelerine ait gonderilerin toplu ozeti. Dahil edilen ulkeler: {ulkeler}",
        "takip_sorgu_ozet": "{toplam} takip numarasi sorgulandi, {bulunan} tanesi bulundu.",
        "eksik_tahsilat_ozet": "{sayi} gonderide musteriden eksik vergi/gumruk tahsil edilmis.",
        "toplam_zarar_metni": "Toplam zarar: ${tutar:,.2f} ({sayi} gonderi)",
        "manuel_gelir_baslik": "**Manuel gelir (opsiyonel)**",
        "manuel_gider_baslik": "**Manuel gider (opsiyonel)**",
        "paket_basi_gider_baslik": "**Paket basina ek gider - firma bazinda (opsiyonel)**",
        "gelir_kalin": "**💰 Gelir**",
        "gider_kalin": "**💸 Gider**",
        "kargo_kar_zarar_grafik": "**📊 Kargo firmasina gore Kar/Zarar**",
        "en_cok_gelir_ulke": "**📊 En cok gelir getiren 10 ulke**",
        "en_cok_gelir_musteri": "**📊 En cok gelir getiren 10 musteri**",
        "kargo_dosya_turu": "Kargo firmasi / dosya turu",
        "henuz_arsiv_yok": "Henuz arsivlenmis bir donem yok. 'Kargo Firmasina Gore Dosya Yukle' bolumunden dosyalarini arsivleyebilirsin.",
        "donem_sec": "Donem sec",
        "once_hesapla_uyari": "⚠️ Once dosyalarini yukleyip 'Hesapla'ya basmalisin. Asagida dosyalarini yukleyebilirsin.",
        "avrupa_gonderi_yok": "Avrupa ulkelerine ait gonderi bulunamadi.",
        "sorgula_buton": "🔎 Sorgula",
        "takip_no_gir_uyari": "Once en az bir takip numarasi gir.",
        "vergi_tam_tahsil": "Butun eslesen gonderilerde vergi/gumruk tam tahsil edilmis gorunuyor. 🎉",
        "baslamak_icin_yukle": "Baslamak icin once gelir dosyasini yukleyin ve 'Hesapla' butonuna basin.",
        "renkleri_ters_cevir": "Renkleri ters cevir",
        "dosyalari_yukle_help": "Dosyalari Ana Sayfa'daki yukleme alanlarina ekler ve yonlendirir - orada dosya ekleyip/cikarabilir, sonra Hesapla'ya basabilirsin.",
        "listeden_cikar": "Listeden cikar",
        "only_paid_label": "Sadece odenmis gonderileri dahil et (Status = Paid)",
        "only_paid_help": "Isaretliyse User Cancelled, New Shipment, Payment Waiting gibi durumlar disarida tutulur.",
        "exclude_carrier_label": "Kargo firmasi atanmamis gonderileri haric tut",
        "exclude_carrier_help": "Isaretliyse Carrier Name (kargo firmasi) bos olan gonderiler analize hic dahil edilmez.",
        "donem_placeholder": "orn. 2026-07",
        "donem_etiketi_label": "Donem etiketi (orn. 2026-07)",
        "dosyayi_sec": "Dosyayi sec",
        "takip_numaralari_label": "Takip numaralari",
        "takip_numaralari_placeholder": "orn.\n1Z999AA10123456784\n1Z999AA10123456785\n... (10'a kadar veya daha fazla)",
        "gelir_dosyasi_ekle": "Gelir Excel dosyasi ekle",
        "gelir_dosyasi_sec": "Gelir Excel dosyasini secin",
        "gider_dosyasi_ekle": "Gider Excel dosyasi ekle",
        "gider_dosyasi_sec": "Gider Excel dosyasini/dosyalarini secin",
        "bu_dosyayi_arsivle": "📤 Bu Dosyayi Arsivle",
        "dosyalari_yukle_buton": "📥 Dosyalari Yukle",
        "firma_label": "Firma",
    },
    "en": {
        "app_baslik": "Warehouse Panel",
        "app_altbaslik": "Automatically match carrier invoices with customer payments",
        "giris_yapildi": "Logged in",
        "cikis_yap": "🚪 Log Out",
        "ana_sayfa": "Home",
        "kargo_dosya_yukle": "Upload File by Carrier",
        "github_arsiv_sec": "Select from GitHub Archive & Calculate",
        "ana_menu": "Main Menu",
        "dosya_islemleri": "File Operations",
        "raporlar": "Reports",
        "kargo_firmalarina_gore": "By Carrier",
        "ulkelere_gore": "By Country",
        "avrupa_ozeti": "Europe Summary",
        "musterilere_gore": "By Customer",
        "musteri_x_ulke": "Customer x Country",
        "detayli_rapor": "Detailed Report",
        "takip_no_sorgula": "Track Number Lookup",
        "tahsil_edilmeyen_vergi": "Uncollected Tax/Duty",
        "boyut_agirlik": "Dimension/Weight Mismatch",
        "gider_bulunamayanlar": "Missing Expenses",
        "eslesmeyen_gider": "Unmatched Expenses",
        "hesap": "Account",
        "email": "Email",
        "sifre": "Password",
        "sifreyi_goster": "👁️ Show password",
        "giris_yap": "Log In",
        "giris_devam": "Log in to continue",
        "email_sifre_hatali": "Incorrect email or password.",
        "gelir": "Income",
        "gider": "Expense",
        "hesapla": "Calculate",
        "yukleniyor": "⏳ Reading files and calculating...",
        "indir_excel": "Download as Excel",
        "indir_csv": "Download as CSV",
        "toplam": "Total",
        "musteri": "Customer",
        "ulke": "Country",
        "kargo_firmasi": "Carrier",
        "takip_no": "Tracking No",
        "kar_zarar": "Profit/Loss",
        "toplam_gelir": "Total Income",
        "toplam_gider": "Total Expense",
        "net_kar": "Net Profit",
        "toplam_paket_sayisi": "Total Package Count",
        "ozet": "📊 Summary",
        "kargo_analiz_baslik": "🚚 Analysis by Carrier",
        "ulke_analiz_baslik": "🌍 Analysis by Country",
        "avrupa_toplam_ozeti": "🌍 Europe Total Summary",
        "musteri_analiz_baslik": "👥 Analysis by Customer",
        "musteri_ulke_analiz_baslik": "👥 Customer x Country Analysis",
        "kargo_yukle_baslik": "📤 Upload File by Carrier",
        "github_arsiv_baslik": "🗄️ Select from GitHub Archive & Calculate",
        "detayli_rapor_baslik": "📋 Detailed Report",
        "takip_sorgula_baslik": "🔎 Track Number Lookup",
        "tahsil_edilmeyen_baslik": "💰 Uncollected Tax/Duty",
        "boyut_agirlik_baslik": "📦 Dimension/Weight Mismatch (Loss-Making Packages)",
        "gider_bulunamayan_baslik": "🔍 Missing Expenses",
        "eslesmeyen_gider_baslik": "⚖️ Unmatched Expenses",
        "eslesme_orani_metni": "Match rate: {oran:.1f}%",
        "toplam_gonderi_ozet": "Total {toplam} shipments  |  {eslesen} matched  |  {bulunamadi} expense not found  |  {takipsiz} no tracking number",
        "kaynak_kolon_metni": "📂 Source column for {firma}: *{sutun}*",
        "avrupa_ozet_metni": "Combined summary of shipments to all European countries including UK, Turkey, Cyprus, Israel. Included countries: {ulkeler}",
        "takip_sorgu_ozet": "{toplam} tracking numbers looked up, {bulunan} found.",
        "eksik_tahsilat_ozet": "{sayi} shipments have under-collected tax/duty from the customer.",
        "toplam_zarar_metni": "Total loss: ${tutar:,.2f} ({sayi} shipments)",
        "manuel_gelir_baslik": "**Manual income (optional)**",
        "manuel_gider_baslik": "**Manual expense (optional)**",
        "paket_basi_gider_baslik": "**Per-package extra expense - by carrier (optional)**",
        "gelir_kalin": "**💰 Income**",
        "gider_kalin": "**💸 Expense**",
        "kargo_kar_zarar_grafik": "**📊 Profit/Loss by carrier**",
        "en_cok_gelir_ulke": "**📊 Top 10 countries by income**",
        "en_cok_gelir_musteri": "**📊 Top 10 customers by income**",
        "kargo_dosya_turu": "Carrier / file type",
        "henuz_arsiv_yok": "No archived period yet. You can archive your files from the 'Upload File by Carrier' section.",
        "donem_sec": "Select period",
        "once_hesapla_uyari": "⚠️ You need to upload your files and click 'Calculate' first. You can upload your files below.",
        "avrupa_gonderi_yok": "No shipments found for European countries.",
        "sorgula_buton": "🔎 Look Up",
        "takip_no_gir_uyari": "Enter at least one tracking number first.",
        "vergi_tam_tahsil": "Tax/duty appears to be fully collected on all matched shipments. 🎉",
        "baslamak_icin_yukle": "To get started, upload your income file and click the 'Calculate' button.",
        "renkleri_ters_cevir": "Invert colors",
        "dosyalari_yukle_help": "Adds the files to the upload areas on the Home page and redirects you there - you can add/remove files, then click Calculate.",
        "listeden_cikar": "Remove from list",
        "only_paid_label": "Include only paid shipments (Status = Paid)",
        "only_paid_help": "When checked, statuses like User Cancelled, New Shipment, Payment Waiting are excluded.",
        "exclude_carrier_label": "Exclude shipments with no assigned carrier",
        "exclude_carrier_help": "When checked, shipments with an empty Carrier Name are excluded from the analysis entirely.",
        "donem_placeholder": "e.g. 2026-07",
        "donem_etiketi_label": "Period label (e.g. 2026-07)",
        "dosyayi_sec": "Select file",
        "takip_numaralari_label": "Tracking numbers",
        "takip_numaralari_placeholder": "e.g.\n1Z999AA10123456784\n1Z999AA10123456785\n... (up to 10 or more)",
        "gelir_dosyasi_ekle": "Add income Excel file",
        "gelir_dosyasi_sec": "Select income Excel file",
        "gider_dosyasi_ekle": "Add expense Excel file",
        "gider_dosyasi_sec": "Select expense Excel file(s)",
        "bu_dosyayi_arsivle": "📤 Archive This File",
        "dosyalari_yukle_buton": "📥 Upload Files",
        "firma_label": "Carrier",
    },
}


def t(anahtar):
    """Secili dile gore ceviri metnini dondurur. Anahtar bulunamazsa
    anahtarin kendisini dondurur (cevrilmemis oldugunu belli eder)."""
    return CEVIRI.get(st.session_state["dil"], CEVIRI["tr"]).get(anahtar, anahtar)


# Uzun serbest metinler (st.caption/st.markdown aciklamalari) icin Turkce
# metni birebir anahtar olarak kullanan bir ceviri sozlugu. tc() sadece
# dil="en" oldugunda karsiligini arar, bulamazsa Turkce metni oldugu gibi
# dondurur (hicbir caption cevrilmeden kalmaz, en kotu ihtimalle Turkce gorunur).
_CAPTION_EN = {
    "Bir kargo firmasindan fatura geldikce, tum formu doldurmadan sadece o dosyayi secip GitHub'a kaydet. Ayni doneme, ayni firmadan tekrar dosya yuklersen otomatik birlestirilir (tekrarlar elenir, yeni satirlar eklenir).":
        "As invoices come in from a carrier, select just that file and save it to GitHub without filling out the whole form. If you upload another file from the same carrier for the same period again, it's automatically merged (duplicates removed, new rows added).",
    "Bilgisayarindan dosya yuklemek yerine, daha once GitHub'a arsivledigin gelir/gider dosyalarindan istedigini sec ve Hesapla'ya bas.":
        "Instead of uploading files from your computer, pick from the income/expense files you've previously archived to GitHub and click Calculate.",
    "WH_CUSTOMER_SHIPMENT_LIST formatinda, musteriden alinan tutarlari iceren dosya.":
        "File in WH_CUSTOMER_SHIPMENT_LIST format, containing amounts collected from customers.",
    "Hicbir pakete baglanmayan, dogrudan net kara eklenecek gelirler (orn. depo kirasi geliri, danismanlik geliri).":
        "Income not tied to any package, added directly to net profit (e.g. warehouse rental income, consulting income).",
    "Kargo firmasindan gelen fatura dosyalari. Birden fazla dosya secebilirsiniz.":
        "Invoice files from the carrier. You can select multiple files.",
    "Su an Asendia, UniUni, UPS ve Asendia'nin ayri Vergi/Gumruk dosyasi dogrudan destekleniyor. ByeLabel dosyasini (shipments-...xlsx) sectiginde icindeki tum firmalar (ePost Global, DHL, intelcom, APC, USPS, Evri, Purolator, FedEx, UPS) otomatik ayri ayri islenir.":
        "Asendia, UniUni, UPS and Asendia's separate Tax/Duty file are currently supported directly. When you select a ByeLabel file (shipments-...xlsx), all carriers inside it (ePost Global, DHL, intelcom, APC, USPS, Evri, Purolator, FedEx, UPS) are automatically processed separately.",
    "Hicbir pakete baglanmayan, dogrudan net kardan dusulecek giderler (orn. depo kirasi, personel maasi, internet faturasi).":
        "Expenses not tied to any package, deducted directly from net profit (e.g. warehouse rent, staff salary, internet bill).",
    "Belirli bir kargo firmasinin, gideri ZATEN eslesmis olan HER paketine ayni tutari ekler (orn. UniUni icin paket basina $2). Tutar otomatik olarak eslesen paket sayisiyla carpilir ve her paketin kar/zarar hesabina islenir - tum tablolarda (ulke, firma, musteri) otomatik yansir. Gideri eslesmemis paketlere bu tutar uygulanmaz.":
        "Adds the same amount to EVERY package of a given carrier that already has a matched expense (e.g. $2 per package for UniUni). The amount is automatically multiplied by the number of matched packages and applied to each package's profit/loss - it's automatically reflected in all tables (country, carrier, customer). This amount is not applied to packages without a matched expense.",
    "Manuel gelir kalemleri:": "Manual income items:",
    "Manuel gider kalemleri:": "Manual expense items:",
    "⚠️ Pakete baglanamayan vergi/komisyon - otomatik tespit edilen (Net Kar'a dahil):":
        "⚠️ Tax/commission not tied to a package - automatically detected (included in Net Profit):",
    "Kargo firmasi (gelir dosyasindaki Carrier Name) bazinda paket sayisi, gelir, gider ve kar/zarar dagilimi.":
        "Package count, income, expense and profit/loss breakdown by carrier (Carrier Name in the income file).",
    "Asagidaki tablo her dosyada hangi kategori/sutunun Kargo, hangisinin Vergi, hangisinin (takip numarasi olmadigi icin) Genel Gider sayildigini ve ne kadar tutar tasidigini gosterir.":
        "The table below shows, for each file, which category/column was counted as Shipping, which as Tax, and which as General Expense (because it has no tracking number), and how much amount each carries.",
    "Toplam gelir ve gonderi sayisi tum gonderileri kapsar. Kargo/Vergi/Kar sutunlari sadece gider dosyasinda eslesen gonderilerden gelir.":
        "Total income and shipment count cover all shipments. The Shipping/Tax/Profit columns come only from shipments matched in the expense file.",
    "Gelir dosyasindaki User No / User Name'e gore musteri bazinda paket sayisi, bize odedigi tutar, firmaya odedigimiz tutar, kar/zarar ve gonderdigi ulkeler. Eslesen Sayisi/Firmaya Odenen/Kar sutunlari sadece ESLESEN gonderilerden gelir.":
        "Package count, amount paid to us, amount we paid the carrier, profit/loss and destination countries by customer, based on User No / User Name in the income file. The Matched Count/Paid to Carrier/Profit columns come only from MATCHED shipments.",
    "Her musterinin HER ULKEDE ayri ayri kar mi zarar mi ettirdigini gosterir (en zararli kombinasyonlar basta). Genel toplamda kar gibi gorunen bir musteri, bazi ulkelerde zarar ettiriyor olabilir.":
        "Shows whether each customer makes a profit or a loss separately IN EACH COUNTRY (most loss-making combinations first). A customer that looks profitable overall may be causing losses in some countries.",
    "Bir veya birden fazla takip numarasi gir (her satira bir tane, veya virgulle ayirarak da yazabilirsin) - gelir ve giderini yan yana, her biri alt alta gorursun.":
        "Enter one or more tracking numbers (one per line, or comma-separated) - you'll see each one's income and expense side by side, stacked one below another.",
    "Kargo firmasina odedigimiz vergi/gumruk (Gider_Tax) ile musteriden gelir dosyasindaki 'Customs Duty Fee' sutunundan tahsil ettigimiz tutari karsilastirir. Odedigimizden AZ tahsil ettigimiz (veya hic tahsil etmedigimiz) gonderileri listeler.":
        "Compares the tax/duty we paid the carrier (Gider_Tax) with the amount we collected from the customer via the 'Customs Duty Fee' column in the income file. Lists shipments where we collected LESS than we paid (or collected nothing at all).",
    "Bu gonderiler icin takip numarasi var ama yuklenen gider dosyalarinda karsiligi bulunamadi. Henuz faturalanmamis olabilir, veya ait oldugu kargo firmasinin dosyasi yuklenmemis olabilir.":
        "These shipments have a tracking number, but no matching entry was found in the uploaded expense files. They may not have been invoiced yet, or the relevant carrier's file may not have been uploaded.",
    "Bu takip numaralari kargo firmasinin fatura listesinde var ama gelir dosyasinda eslesen bir gonderi bulunamadi. Farkli ay/musteri donemine ait olabilir, kontrol etmekte fayda var.":
        "These tracking numbers exist in the carrier's invoice list, but no matching shipment was found in the income file. They may belong to a different month/customer period - worth checking.",
    "Musteriye beyan ettigimiz (gelir dosyasindaki) ile kargo firmasinin faturasindaki olcumleri **hacim** (uzunluk x genislik x yukseklik) ve **agirlik** olarak karsilastirir - tek tek kenar (uzunluk/genislik/yukseklik) karsilastirilmaz, cunku firmalar hangi kenara 'uzunluk' hangisine 'genislik' dedigini bizden farkli siralayabiliyor; hacim carpimda sira onemli olmadigi icin bu sorunu ortadan kaldirir.\n\nSadece **hem bizim hem firmanin olcusu birlikte mevcut olan** ve ZARAR ettigimiz (Kar/Zarar < 0) gonderileri gosterir.\n\n⚠️ Not 1: Su an sadece **FedEx, Asendia ve UniUni** fatura dosyalarinda boyut/agirlik bilgisi bulunuyor. UPS ve ByeLabel grubu firmalarinin fatura formatlarinda bu bilgi yok, bu yuzden o gonderiler bu listede gorunmez.\n\n⚠️ Not 2: Bizim olcum birimimiz (inc/lb) ile bazi firmalarin kendi birimi (orn. cm/kg) farkli olabilir - 'Hacim Orani' sutunu TUM satirlarda benzer, tutarli bir kat gosteriyorsa (orn. hep ~16x gibi) bu bir birim farkindan kaynaklaniyor olabilir, gercek bir uyusmazliktan degil. Soyle bir durumda bana haber ver, birim cevrimini ekleyelim.":
        "Compares what we declared to the customer (in the income file) with the carrier's invoice measurements by **volume** (length x width x height) and **weight** - individual sides (length/width/height) are not compared one by one, because carriers may order which side is 'length' vs 'width' differently than we do; since order doesn't matter in a volume product, this removes that problem.\n\nOnly shows shipments where **both our measurement and the carrier's measurement are available together** and we made a LOSS (Profit/Loss < 0).\n\n⚠️ Note 1: Currently only **FedEx, Asendia and UniUni** invoice files contain dimension/weight information. UPS and the ByeLabel group of carriers don't have this in their invoice formats, so those shipments won't appear in this list.\n\n⚠️ Note 2: Our unit of measurement (in/lb) may differ from some carriers' own units (e.g. cm/kg) - if the 'Volume Ratio' column shows a similar, consistent multiple across ALL rows (e.g. always ~16x), this may be caused by a unit difference rather than a real mismatch. If you notice this, let me know and we'll add unit conversion.",
}


def tc(metin):
    """Serbest (uzun) aciklama metinlerini cevirir - sadece dil='en' iken
    _CAPTION_EN sozlugunde arar, bulamazsa metni oldugu gibi dondurur."""
    if st.session_state["dil"] == "en":
        return _CAPTION_EN.get(metin, metin)
    return metin

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
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", Helvetica, Arial, sans-serif !important;
    }

    .main .block-container,
    [data-testid="stMainBlockContainer"] {
        background-color: var(--panel-bg) !important;
        padding-top: 0 !important;
        padding-left: 0.75rem !important;
        padding-right: 0.75rem !important;
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

    /* Sidebar - koyu, genis panel. Genislik/pozisyon ayari asagidaki
       sidebar-ozel CSS blogunda (hover ile daralma/genisleme) yapiliyor. */
    [data-testid="stSidebar"] {
        background-color: var(--sidebar-bg) !important;
        border-right: 1px solid #22252d !important;
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
            f"""
            <div style="text-align:center; margin-bottom: 18px; margin-top: 2vh;">
                <div style="font-size: 40px;">📦</div>
                <div style="font-size: 22px; font-weight: 800; color: #1f2430;">{t('app_baslik')}</div>
                <div style="font-size: 13px; color: #5f6779; margin-top: 2px;">{t('giris_devam')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        _sifre_goster = st.checkbox(t("sifreyi_goster"), key="sifre_goster_toggle")

        st.markdown(
            """
            <style>
            .st-key-giris_dil_en_gb, .st-key-giris_dil_tr {
                width: 44px !important;
                min-width: 44px !important;
                max-width: 44px !important;
            }
            .st-key-giris_dil_en_gb button, .st-key-giris_dil_tr button {
                width: 44px !important;
                height: 34px !important;
                min-height: 34px !important;
                padding: 0 !important;
                margin: 0 !important;
                border-radius: 4px !important;
                border: none !important;
            }
            .st-key-giris_dil_en_gb button p, .st-key-giris_dil_tr button p {
                font-size: 26px !important;
                line-height: 1 !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        _giris_dil_kolonlari = st.columns([5, 1, 1])
        with _giris_dil_kolonlari[1]:
            if st.button("🇬🇧", key="giris_dil_en_gb", help="English"):
                st.session_state["dil"] = "en"
                st.rerun()
        with _giris_dil_kolonlari[2]:
            if st.button("🇹🇷", key="giris_dil_tr", help="Turkce"):
                st.session_state["dil"] = "tr"
                st.rerun()

        with st.form("giris_formu", clear_on_submit=False, border=False):
            _email = st.text_input(t("email"), autocomplete="off", key="giris_email")
            _sifre = st.text_input(
                t("sifre"),
                type="default" if _sifre_goster else "password",
                autocomplete="off",
                key="giris_sifre",
            )
            _gonderildi = st.form_submit_button(t("giris_yap"), type="primary", width="stretch")

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
                st.error(t("email_sifre_hatali"))

    st.stop()





def _hex_to_rgba(hex_renk, alpha):
    hex_renk = hex_renk.lstrip("#")
    r, g, b = int(hex_renk[0:2], 16), int(hex_renk[2:4], 16), int(hex_renk[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# comfylifeusa@gmail.com kullanicisinin gelir dosyasi farkli bir formatta
# (FBA_PLUS listesi) geliyor - dropcomfyship@gmail.com ve diger tum
# kullanicilar icin eskisi gibi WH_CUSTOMER_SHIPMENT_LIST formati kullanilir.
# Boylece iki kullanicinin dosya yapisi asla birbirine karismaz.
_FBA_FORMATI_KULLANAN_HESAPLAR = {"comfylifeusa@gmail.com"}


def _gelir_dosyasi_oku(file_obj, only_paid, exclude_unassigned_carrier):
    """Giris yapan kullaniciya gore doguru gelir dosyasi formatini secip okur."""
    kullanici_adi = st.session_state.get("username", "")
    if kullanici_adi in _FBA_FORMATI_KULLANAN_HESAPLAR:
        return load_income_file_fba(
            file_obj, only_paid=only_paid, exclude_unassigned_carrier=exclude_unassigned_carrier
        )
    return load_income_file(
        file_obj, only_paid=only_paid, exclude_unassigned_carrier=exclude_unassigned_carrier
    )


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


def _kart_html(etiket, deger, renk, icon=""):
    """Tek bir KPI kartinin HTML govdesini uretir (render etmez)."""
    return f"""
        <div style="
            background: #ffffff;
            border-left: 5px solid {renk};
            border-radius: 10px;
            padding: 16px 20px;
            box-shadow: 0 1px 4px rgba(16, 24, 40, 0.10);
            border-top: 1.5px solid #c7cbd6;
            border-right: 1.5px solid #c7cbd6;
            border-bottom: 1.5px solid #c7cbd6;
        ">
            <div style="font-size: 30px; font-weight: 800; color: #1f2430; line-height: 1.15; letter-spacing: -0.02em;">{icon} {deger}</div>
            <div style="font-size: 13px; font-weight: 500; color: #6b7280; margin-top: 4px;">{etiket}</div>
        </div>
        """


def renkli_kart(etiket, deger, renk, icon=""):
    """Sellivox tarzi: beyaz kart, hafif golge, sol renkli kenarlik. Tek basina render eder."""
    st.markdown(
        f'<div style="margin-bottom: 6px;">{_kart_html(etiket, deger, renk, icon)}</div>',
        unsafe_allow_html=True,
    )


def kart_izgarasi(*kartlar, min_genislik=190):
    """Birden fazla KPI kartini gercek bir CSS grid icinde (auto-fit,
    ekrana gore otomatik dizilen/saran) tek seferde render eder.
    kartlar: (etiket, deger, renk, icon) tuple'lari."""
    hucreler = "".join(_kart_html(*k) for k in kartlar)
    st.markdown(
        f"""
        <div style="
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax({min_genislik}px, 1fr));
            gap: 12px;
            margin-bottom: 12px;
        ">
            {hucreler}
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
            t("indir_csv"),
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
            t("indir_excel"),
            data=buf.getvalue(),
            file_name=f"{dosya_adi}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{key_prefix}_excel",
        )


_tema_buton_css = """
    <style>
"""
for _i, _tema_adi in enumerate(_TEMA_SIRASI):
    _renkler = TEMALAR[_tema_adi]
    _tema_buton_css += f"""
    .st-key-tema_sec_{_i} {{
        width: 32px !important;
        min-width: 32px !important;
        max-width: 32px !important;
    }}
    .st-key-tema_sec_{_i} button {{
        width: 32px !important;
        height: 32px !important;
        min-height: 32px !important;
        padding: 0 !important;
        margin: 0 !important;
        border-radius: 50% !important;
        font-size: 0 !important;
        line-height: 0 !important;
        border: none !important;
        box-shadow: none !important;
        background: linear-gradient(90deg, {_renkler['accent']} 50%, {_renkler['koyu']} 50%) !important;
    }}
    """
_secili_index = _TEMA_SIRASI.index(st.session_state["secili_tema"])
_tema_buton_css += f"""
    .st-key-tema_sec_{_secili_index} button {{
        transform: scale(1.25) !important;
    }}
    .st-key-tema_ters_cevir {{
        width: 32px !important;
        min-width: 32px !important;
        max-width: 32px !important;
    }}
    .st-key-tema_ters_cevir button {{
        width: 32px !important;
        height: 32px !important;
        min-height: 32px !important;
        padding: 0 !important;
        margin: 0 !important;
        border-radius: 50% !important;
        border: none !important;
        box-shadow: none !important;
        background: var(--card-bg) !important;
        color: var(--text-dark) !important;
    }}
    </style>
"""
st.markdown(_tema_buton_css, unsafe_allow_html=True)
st.markdown(
    """
    <style>
    .st-key-dil_en_gb, .st-key-dil_tr {
        width: 40px !important;
        min-width: 40px !important;
        max-width: 40px !important;
    }
    .st-key-dil_en_gb button, .st-key-dil_tr button {
        width: 40px !important;
        height: 32px !important;
        min-height: 32px !important;
        padding: 0 !important;
        margin: 0 !important;
        border-radius: 4px !important;
        border: none !important;
        box-shadow: 0 0 0 1px var(--border-light) !important;
    }
    .st-key-dil_en_gb button p, .st-key-dil_tr button p {
        font-size: 24px !important;
        line-height: 1 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------- ust satir (grid) ---
# Baslik, tema secici, dil secici, kullanici bilgisi ve cikis butonu artik
# TEK bir st.columns() satirinda - boylece hepsi ayni hizada, tek bir
# grid/satir gibi hizalanir (ayri ayri satirlar yerine).
st.markdown(
    """
    <style>
    [data-testid="stHorizontalBlock"]:has(#baslik-satiri) {
        align-items: center !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
_col_baslik, _col_tema, _col_dil, _col_info, _col_btn = st.columns([3.0, 2.3, 0.85, 1.4, 0.6])

with _col_baslik:
    st.markdown(
        f"""
        <span id="baslik-satiri"></span>
        <div style="padding: 2px 0;">
            <div style="font-size: 34px; font-weight: 800; color: #1f2430; line-height: 1.15; letter-spacing: -0.02em;">
                📦 {t('app_baslik')}
            </div>
            <div style="font-size: 13px; color: #6b7280; margin-top: 2px;">
                {t('app_altbaslik')}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with _col_tema:
    _tema_kolonlari = st.columns([1] * len(_TEMA_SIRASI) + [1])
    for _i, _tema_adi in enumerate(_TEMA_SIRASI):
        with _tema_kolonlari[_i]:
            if st.button(" ", key=f"tema_sec_{_i}", help=_tema_adi):
                st.session_state["secili_tema"] = _tema_adi
                st.rerun()
    with _tema_kolonlari[len(_TEMA_SIRASI)]:
        if st.button("⇄", key="tema_ters_cevir", help=t("renkleri_ters_cevir")):
            st.session_state["tema_ters"] = not st.session_state["tema_ters"]
            st.rerun()

with _col_dil:
    _dil_kolonlari = st.columns(2)
    with _dil_kolonlari[0]:
        if st.button("🇬🇧", key="dil_en_gb", help="English"):
            st.session_state["dil"] = "en"
            st.rerun()
    with _dil_kolonlari[1]:
        if st.button("🇹🇷", key="dil_tr", help="Turkce"):
            st.session_state["dil"] = "tr"
            st.rerun()

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
            <span style="font-size: 11px; color: #8a90a0;">· {t('giris_yapildi')}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
with _col_btn:
    if st.button(t("cikis_yap"), key="cikis_butonu"):
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

# Menu etiketleri (internal key - yonlendirme icin degismez) ile ceviri
# anahtarlarini eslestirir. Boylece analiz_secimi karsilastirmalari (kodun
# her yerinde kullanilan) hic degismeden kalir, sadece GORUNEN metin cevrilir.
_MENU_CEVIRI = {
    "Ana Sayfa": "ana_sayfa",
    "Kargo Firmasina Gore Dosya Yukle": "kargo_dosya_yukle",
    "GitHub Arsivinden Dosya Sec ve Hesapla": "github_arsiv_sec",
    "Kargo Firmalarina Gore": "kargo_firmalarina_gore",
    "Ulkelere Gore": "ulkelere_gore",
    "Avrupa Ozeti": "avrupa_ozeti",
    "Musterilere Gore": "musterilere_gore",
    "Musteri x Ulke": "musteri_x_ulke",
    "Detayli Rapor": "detayli_rapor",
    "Takip No Sorgula": "takip_no_sorgula",
    "Tahsil Edilmeyen Vergi/Gumruk": "tahsil_edilmeyen_vergi",
    "Boyut/Agirlik Uyusmazligi": "boyut_agirlik",
    "Gider Bulunamayanlar": "gider_bulunamayanlar",
    "Eslesmeyen Gider": "eslesmeyen_gider",
}


def _menu_metni(label):
    return t(_MENU_CEVIRI.get(label, label))

if "analiz_secimi" not in st.session_state:
    st.session_state["analiz_secimi"] = None  # None = Ana Sayfa

with st.sidebar:
    if "sidebar_daralt" not in st.session_state:
        st.session_state["sidebar_daralt"] = False
    _sb_daralt = st.session_state["sidebar_daralt"]
    _sb_genislik = "64px" if _sb_daralt else "248px"

    _sidebar_css = """
        <style>
        /* Sidebar genisligi tiklanabilir bir butonla (sidebar_daralt) kontrol
           edilir - fare hover'i ile DEGIL. Streamlit'in kendi sidebar'i,
           kullanicinin surukleyerek yeniden boyutlandirmasina izin vermek
           icin genisligini kendi JS'iyle aktif yonetiyor; bu yuzden CSS
           ':hover' tabanli otomatik genisleme/daralma guvenilmez sonuc
           veriyordu (bazen hic gorunmeme, bazen kapanmama). Sabit (statik)
           bir genislik zorlamasi - daha once basariyla kullandigimiz yontem -
           JS ile catismadan guvenilir sekilde calisiyor. Etiket metinlerinin
           gosterilip gizlenmesi de artik CSS numarasiyla degil, dogrudan
           Python tarafinda (asagida) kontrol ediliyor. */
        [data-testid="stSidebar"] {
            width: %%GENISLIK%% !important;
            min-width: %%GENISLIK%% !important;
            max-width: %%GENISLIK%% !important;
            background-color: %%KOYU%%;
            border-right: 1px solid #22252d;
            transform: none !important;
            visibility: visible !important;
            margin-left: 0 !important;
            transition: width 0.15s ease, min-width 0.15s ease, max-width 0.15s ease;
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
            font-size: %%FONT_BOYUTU%% !important;
            font-weight: 500 !important;
            background: transparent !important;
            border: none !important;
            color: var(--sidebar-text) !important;
            box-shadow: none !important;
            transition: background 0.15s;
            text-align: left !important;
            white-space: nowrap !important;
            overflow: hidden !important;
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
            font-size: inherit !important;
            margin: 0 !important;
            text-align: left !important;
            white-space: nowrap !important;
        }
        .sidebar-logo {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 18px 14px 18px;
            border-bottom: 1px solid #22252d;
            margin-bottom: 10px;
            white-space: nowrap;
            overflow: hidden;
        }
        .sidebar-logo .box {
            width: 32px; height: 32px;
            min-width: 32px;
            background: linear-gradient(135deg, %%ACCENT%%, %%KOYU2%%);
            border-radius: 8px;
            display: flex; align-items: center; justify-content: center;
            font-size: 16px;
            flex-shrink: 0;
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
            white-space: nowrap;
            overflow: hidden;
        }
        </style>
        """
    if _sb_daralt:
        _sidebar_css += """
        <div class="sidebar-logo">
            <div class="box">📦</div>
        </div>
        """
    else:
        _sidebar_css += """
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
        .replace("%%GENISLIK%%", _sb_genislik)
        .replace("%%FONT_BOYUTU%%", "24px" if _sb_daralt else "14px")
    )
    st.markdown(_sidebar_css, unsafe_allow_html=True)

    if st.button("☰" if _sb_daralt else "☰  Daralt", key="sidebar_toggle_btn"):
        st.session_state["sidebar_daralt"] = not _sb_daralt
        st.rerun()

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

    def _buton_metni(icon, label):
        return icon if _sb_daralt else f"{icon}  {_menu_metni(label)}"

    if not _sb_daralt:
        st.markdown(f'<div class="sidebar-section">{t("ana_menu")}</div>', unsafe_allow_html=True)
    icon, label = BASE_MENU_ITEMS[0]
    if st.button(_buton_metni(icon, label), key=f"nav_{label}", width="stretch"):
        _her_seyi_sifirla()
        st.session_state["analiz_secimi"] = None
        st.rerun()

    if not _sb_daralt:
        st.markdown(f'<div class="sidebar-section">{t("dosya_islemleri")}</div>', unsafe_allow_html=True)
    for icon, label in BASE_MENU_ITEMS[1:]:
        if st.button(_buton_metni(icon, label), key=f"nav_{label}", width="stretch"):
            st.session_state["analiz_secimi"] = label
            st.rerun()

    if not _sb_daralt:
        st.markdown(f'<div class="sidebar-section">{t("raporlar")}</div>', unsafe_allow_html=True)
    for icon, label in REPORT_MENU_ITEMS:
        if st.button(_buton_metni(icon, label), key=f"nav_{label}", width="stretch"):
            st.session_state["analiz_secimi"] = label
            st.rerun()

analiz_secimi = st.session_state.get("analiz_secimi")

# ---------------------------------------------- kargo firmasina gore yukle ---
if analiz_secimi == "Kargo Firmasina Gore Dosya Yukle":
    st.subheader(t("kargo_yukle_baslik"))
    st.caption(tc(
        "Bir kargo firmasindan fatura geldikce, tum formu doldurmadan sadece "
        "o dosyayi secip GitHub'a kaydet. Ayni doneme, ayni firmadan tekrar "
        "dosya yuklersen otomatik birlestirilir (tekrarlar elenir, yeni "
        "satirlar eklenir)."
    ))
    _tekli_donem = st.text_input(
        t("donem_etiketi_label"),
        value="",
        key="tekli_arsiv_donem",
        placeholder=t("donem_placeholder"),
    )
    _tekli_secenekler = ["Gelir (WH_CUSTOMER_SHIPMENT_LIST)"] + list(CARRIER_PROFILES.keys()) + [BYELABEL_GROUP_LABEL]
    _tekli_secim = st.selectbox(t("kargo_dosya_turu"), options=_tekli_secenekler, key="tekli_arsiv_secim")
    _tekli_dosya = st.file_uploader(
        t("dosyayi_sec"), type=["xlsx"], key="tekli_arsiv_dosya"
    )
    if st.button(
        t("bu_dosyayi_arsivle"),
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
    st.subheader(t("github_arsiv_baslik"))
    st.caption(tc(
        "Bilgisayarindan dosya yuklemek yerine, daha once GitHub'a arsivledigin "
        "gelir/gider dosyalarindan istedigini sec ve Hesapla'ya bas."
    ))
    try:
        with st.spinner("🔄 GitHub'daki donemler yukleniyor..."):
            _kayitli_donemler = list_periods()
    except GithubStorageError as e:
        _kayitli_donemler = []
        st.warning(str(e))

    if not _kayitli_donemler:
        st.info(t("henuz_arsiv_yok"))
    else:
        _secilen_arsiv_donemi = st.selectbox(t("donem_sec"), options=_kayitli_donemler, key="arsiv_donem_sec")

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
            t("dosyalari_yukle_buton"),
            type="primary",
            key="arsiv_hesapla_btn",
            disabled=not _secili_gelir_dosyalari,
            help=t("dosyalari_yukle_help"),
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
        st.warning(t("once_hesapla_uyari"))

    # Yuklu parametreler varsa widget varsayilan degerlerine uygula
    _params = st.session_state.get("yuklu_parametreler", {})

    # ---------------------------------------------------------------- yukleme ---
    col1, col2 = st.columns(2)

    with col1:
        st.subheader(t("gelir"))
        st.caption(tc("WH_CUSTOMER_SHIPMENT_LIST formatinda, musteriden alinan tutarlari iceren dosya."))

        if "gelir_dosyalari" not in st.session_state:
            st.session_state["gelir_dosyalari"] = []
        if "gelir_uploader_versiyon" not in st.session_state:
            st.session_state["gelir_uploader_versiyon"] = 0

        _gelir_listesi = st.session_state["gelir_dosyalari"]
        if _gelir_listesi:
            for _d in list(_gelir_listesi):
                _c1, _c2 = st.columns([6, 1])
                _c1.markdown(f"📄 {_d['ad']}")
                if _c2.button("🗑️", key=f"gelir_sil_{_d['ad']}", help=t("listeden_cikar")):
                    _dosya_listesinden_cikar("gelir_dosyalari", _d["ad"])
                    st.rerun()

        _yeni_gelir_dosyalari = st.file_uploader(
            t("gelir_dosyasi_ekle") if _gelir_listesi else t("gelir_dosyasi_sec"),
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
            t("only_paid_label"),
            value=_params.get("only_paid", True),
            help=t("only_paid_help"),
        )
        exclude_unassigned_carrier = st.checkbox(
            t("exclude_carrier_label"),
            value=_params.get("exclude_unassigned_carrier", True),
            help=t("exclude_carrier_help"),
        )

        st.markdown(t("manuel_gelir_baslik"))
        st.caption(tc(
            "Hicbir pakete baglanmayan, dogrudan net kara eklenecek gelirler "
            "(orn. depo kirasi geliri, danismanlik geliri)."
        ))
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
        st.subheader(t("gider"))
        st.caption(tc("Kargo firmasindan gelen fatura dosyalari. Birden fazla dosya secebilirsiniz."))

        if "gider_dosyalari" not in st.session_state:
            st.session_state["gider_dosyalari"] = []
        if "gider_uploader_versiyon" not in st.session_state:
            st.session_state["gider_uploader_versiyon"] = 0
        if "gider_secilen_firma" not in st.session_state:
            st.session_state["gider_secilen_firma"] = None

        _tum_firma_secenekleri = list(CARRIER_PROFILES.keys()) + [BYELABEL_GROUP_LABEL]
        _gider_listesi = st.session_state["gider_dosyalari"]

        st.caption(tc(
            "Once dosyanin hangi kargo firmasina ait oldugunu sec, sonra o "
            "firmaya ait fatura dosyasini/dosyalarini yukle."
        ))
        _secim_index = (
            _tum_firma_secenekleri.index(st.session_state["gider_secilen_firma"])
            if st.session_state["gider_secilen_firma"] in _tum_firma_secenekleri
            else 0
        )
        _secilen_firma = st.selectbox(
            t("firma_label"),
            options=_tum_firma_secenekleri,
            index=_secim_index,
            key="gider_firma_onceden_secim",
        )
        st.session_state["gider_secilen_firma"] = _secilen_firma

        _yeni_gider_dosyalari = st.file_uploader(
            t("gider_dosyasi_ekle") if _gider_listesi else t("gider_dosyasi_sec"),
            type=["xlsx"],
            accept_multiple_files=True,
            key=f"cost_uploader_{st.session_state['gider_uploader_versiyon']}",
        )
        if _yeni_gider_dosyalari:
            for _f in _yeni_gider_dosyalari:
                _dosya_listesine_ekle(
                    "gider_dosyalari", _f.name, _f.getvalue(), {"firma": _secilen_firma}
                )
            st.session_state["gider_uploader_versiyon"] += 1
            st.rerun()

        if _gider_listesi:
            st.markdown(tc("**Yuklenen dosyalar:**"))
            for _d in list(_gider_listesi):
                _c1, _c2, _c3 = st.columns([4, 3, 1])
                _c1.markdown(f"📄 {_d['ad']}")
                _mevcut_firma = _d.get("firma", BYELABEL_GROUP_LABEL)
                _yeni_firma = _c2.selectbox(
                    t("firma_label"),
                    options=_tum_firma_secenekleri,
                    index=_tum_firma_secenekleri.index(_mevcut_firma) if _mevcut_firma in _tum_firma_secenekleri else 0,
                    key=f"gider_firma_{_d['ad']}",
                    label_visibility="collapsed",
                )
                if _yeni_firma != _mevcut_firma:
                    _d["firma"] = _yeni_firma
                    st.session_state["gider_dosyalari"] = _gider_listesi
                if _c3.button("🗑️", key=f"gider_sil_{_d['ad']}", help=t("listeden_cikar")):
                    _dosya_listesinden_cikar("gider_dosyalari", _d["ad"])
                    st.rerun()

        if _gider_listesi:
            st.caption(tc(
                "Su an Asendia, UniUni, UPS ve Asendia'nin ayri Vergi/Gumruk dosyasi "
                "dogrudan destekleniyor. ByeLabel dosyasini (shipments-...xlsx) sectiginde "
                "icindeki tum firmalar (ePost Global, DHL, intelcom, APC, USPS, Evri, "
                "Purolator, FedEx, UPS) otomatik ayri ayri islenir."
            ))

        dahil_et_genel_gider = True  # Pakete baglanamayan giderler bilgi amacli gosterilir, otomatik eklenmez

        st.markdown(t("manuel_gider_baslik"))
        st.caption(tc(
            "Hicbir pakete baglanmayan, dogrudan net kardan dusulecek giderler "
            "(orn. depo kirasi, personel maasi, internet faturasi)."
        ))
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

        st.markdown(t("paket_basi_gider_baslik"))
        st.caption(tc(
            "Belirli bir kargo firmasinin, gideri ZATEN eslesmis olan HER paketine "
            "ayni tutari ekler (orn. UniUni icin paket basina $2). Tutar otomatik "
            "olarak eslesen paket sayisiyla carpilir ve her paketin kar/zarar "
            "hesabina islenir - tum tablolarda (ulke, firma, musteri) otomatik "
            "yansir. Gideri eslesmemis paketlere bu tutar uygulanmaz."
        ))
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
            t("hesapla"),
            type="primary",
            disabled=not st.session_state.get("gelir_dosyalari"),
            width="stretch",
        ):
            with st.spinner(t("yukleniyor")):
                # Dosyalari oku ve session_state'e kaydet
                try:
                    _gelir_dfs = []
                    for _d in st.session_state["gelir_dosyalari"]:
                        _gelir_dfs.append(
                            _gelir_dosyasi_oku(
                                io.BytesIO(_d["bytes"]),
                                only_paid,
                                exclude_unassigned_carrier,
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
                    _gelir_dosyasi_oku(
                        io.BytesIO(_d["bytes"]),
                        only_paid,
                        exclude_unassigned_carrier,
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
        st.subheader(t("ozet"))

        _ozet_kartlari = [
            (t("toplam_paket_sayisi"), f"{summary['toplam_gonderi']:,}", _tema["accent"], "📦"),
            ("Toplam Gelir", f"${summary['toplam_gelir']:,.2f}", "#10b981", "💵"),
            ("Kargo Gideri", f"${summary['toplam_gider_kargo']:,.2f}", "#f59e0b", "🚚"),
            ("Vergi/Gumruk Gideri", f"${summary['toplam_gider_tax']:,.2f}", "#f97316", "🛂"),
            ("Toplam Gider", f"${summary['toplam_gider_eslesen']:,.2f}", "#ef4444", "🧾"),
        ]

        gecerli_paket_basi = manual_carrier_expenses_df.dropna(subset=["Kargo Firmasi", "Paket Basi Tutar"])
        gecerli_paket_basi = gecerli_paket_basi[gecerli_paket_basi["Kargo Firmasi"].astype(str).str.strip() != ""]
        has_per_package_fee = not gecerli_paket_basi.empty

        if toplam_genel_gider or manuel_gelir_toplam:
            _ozet_kartlari.append(("Manuel Gelir", f"${summary['manuel_gelir']:,.2f}", "#14b8a6", "✍️"))
            _ozet_kartlari.append(("Genel Gider", f"${summary['genel_gider']:,.2f}", "#dc2626", "⚠️"))

        kart_izgarasi(*_ozet_kartlari)

        gecerli_manuel_gelir = manual_income_df.dropna(subset=["Aciklama", "Tutar"])
        gecerli_manuel_gelir = gecerli_manuel_gelir[gecerli_manuel_gelir["Aciklama"].astype(str).str.strip() != ""]
        gecerli_manuel_gider = manual_expenses_df.dropna(subset=["Aciklama", "Tutar"])
        gecerli_manuel_gider = gecerli_manuel_gider[gecerli_manuel_gider["Aciklama"].astype(str).str.strip() != ""]
        gecerli_manuel_gider_gosterim = gecerli_manuel_gider

        if not gecerli_manuel_gelir.empty or not gecerli_manuel_gider_gosterim.empty or has_per_package_fee:
            col_mg, col_mgid = st.columns(2)
            with col_mg:
                if not gecerli_manuel_gelir.empty:
                    st.caption(tc("Manuel gelir kalemleri:"))
                    st.dataframe(
                        gecerli_manuel_gelir.style.format({"Tutar": "${:,.2f}"}),
                        width="stretch",
                        hide_index=True,
                    )
            with col_mgid:
                if not gecerli_manuel_gider_gosterim.empty or otomatik_satirlar:
                    st.caption(tc("Manuel gider kalemleri:"))
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
        net_kar_renk = "#10b981" if summary["net_kar"] >= 0 else "#dc2626"
        net_kar_icon = "📈" if summary["net_kar"] >= 0 else "📉"
        _, _net_kar_orta, _ = st.columns([1, 2, 1])
        with _net_kar_orta:
            kart_izgarasi(
                ("Net Kar", f"${summary['net_kar']:,.2f}", net_kar_renk, net_kar_icon),
                ("Net Kar Yuzdesi (%)", f"%{summary['net_kar_yuzde']:,.1f}", net_kar_renk, net_kar_icon),
                min_genislik=160,
            )

        if not genel_gider_kategori_detay.empty:
            st.caption(tc("⚠️ Pakete baglanamayan vergi/komisyon - otomatik tespit edilen (Net Kar'a dahil):"))

            kaynaklar = genel_gider_kategori_detay[["Kargo Firmasi", "Kaynak Sutun"]].drop_duplicates()
            for _, kr in kaynaklar.iterrows():
                st.caption(t("kaynak_kolon_metni").format(firma=kr['Kargo Firmasi'], sutun=kr['Kaynak Sutun']))

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
        st.caption(t("eslesme_orani_metni").format(oran=eslesme_orani))

        st.caption(
            t("toplam_gonderi_ozet").format(
                toplam=summary["toplam_gonderi"],
                eslesen=summary["eslesen_sayisi"],
                bulunamadi=summary["gider_bulunamadi_sayisi"],
                takipsiz=summary["takip_no_yok_sayisi"],
            )
        )

        # Rapor sekmelerinden biri secili degilse (orn. hesaplama az once bitti),
        # varsayilan olarak ilk rapor sekmesini goster.
        _rapor_etiketleri = [label for _, label in REPORT_MENU_ITEMS]
        if analiz_secimi not in _rapor_etiketleri:
            analiz_secimi = REPORT_MENU_ITEMS[0][1]
            st.session_state["analiz_secimi"] = analiz_secimi

        st.divider()

        if analiz_secimi == "Kargo Firmalarina Gore":
            st.subheader(t("kargo_analiz_baslik"))
            st.caption(tc(
                "Kargo firmasi (gelir dosyasindaki Carrier Name) bazinda paket sayisi, "
                "gelir, gider ve kar/zarar dagilimi."
            ))
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
                st.markdown(t("kargo_kar_zarar_grafik"))
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
                st.caption(tc(
                    "Asagidaki tablo her dosyada hangi kategori/sutunun Kargo, hangisinin "
                    "Vergi, hangisinin (takip numarasi olmadigi icin) Genel Gider sayildigini "
                    "ve ne kadar tutar tasidigini gosterir."
                ))
                st.dataframe(
                    full_breakdown.style.format({"Tutar": "${:,.2f}"}),
                    width="stretch",
                    hide_index=True,
                )
                indirme_butonlari(full_breakdown, "kargo_vergi_siniflandirma", "full_breakdown")

        elif analiz_secimi == "Ulkelere Gore":
            st.subheader(t("ulke_analiz_baslik"))
            st.caption(tc(
                "Toplam gelir ve gonderi sayisi tum gonderileri kapsar. Kargo/Vergi/Kar "
                "sutunlari sadece gider dosyasinda eslesen gonderilerden gelir."
            ))
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
                st.markdown(t("en_cok_gelir_ulke"))
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
                st.subheader(t("avrupa_toplam_ozeti"))
                st.caption(t("avrupa_ozet_metni").format(ulkeler=" · ".join(eu["ulkeler"])))
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
                st.info(t("avrupa_gonderi_yok"))

        elif analiz_secimi == "Musterilere Gore":
            st.subheader(t("musteri_analiz_baslik"))
            st.caption(tc(
                "Gelir dosyasindaki User No / User Name'e gore musteri bazinda paket "
                "sayisi, bize odedigi tutar, firmaya odedigimiz tutar, kar/zarar ve "
                "gonderdigi ulkeler. Eslesen Sayisi/Firmaya Odenen/Kar sutunlari sadece "
                "ESLESEN gonderilerden gelir."
            ))
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
                st.markdown(t("en_cok_gelir_musteri"))
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
            st.subheader(t("musteri_ulke_analiz_baslik"))
            st.caption(tc(
                "Her musterinin HER ULKEDE ayri ayri kar mi zarar mi ettirdigini gosterir "
                "(en zararli kombinasyonlar basta). Genel toplamda kar gibi gorunen bir "
                "musteri, bazi ulkelerde zarar ettiriyor olabilir."
            ))
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
            st.subheader(t("detayli_rapor_baslik"))
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
            st.subheader(t("takip_sorgula_baslik"))
            st.caption(tc(
                "Bir veya birden fazla takip numarasi gir (her satira bir tane, "
                "veya virgulle ayirarak da yazabilirsin) - gelir ve giderini "
                "yan yana, her biri alt alta gorursun."
            ))
            _takip_girdi = st.text_area(
                t("takip_numaralari_label"),
                placeholder=t("takip_numaralari_placeholder"),
                height=140,
                key="takip_no_sorgu_girdi",
            )

            if st.button(t("sorgula_buton"), type="primary", key="takip_no_sorgula_btn"):
                _ham_liste = [
                    p.strip()
                    for parca in _takip_girdi.splitlines()
                    for p in parca.split(",")
                ]
                _takip_listesi = [t for t in _ham_liste if t]

                if not _takip_listesi:
                    st.warning(t("takip_no_gir_uyari"))
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
                    st.caption(t("takip_sorgu_ozet").format(toplam=len(_takip_listesi), bulunan=_bulunan_sayisi))

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
            st.subheader(t("tahsil_edilmeyen_baslik"))
            st.caption(tc(
                "Kargo firmasina odedigimiz vergi/gumruk (Gider_Tax) ile musteriden "
                "gelir dosyasindaki 'Customs Duty Fee' sutunundan tahsil ettigimiz "
                "tutari karsilastirir. Odedigimizden AZ tahsil ettigimiz (veya hic "
                "tahsil etmedigimiz) gonderileri listeler."
            ))

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
                st.success(t("vergi_tam_tahsil"))
            else:
                _toplam_eksik = _eksik_tahsilat["Eksik Tahsilat"].sum()
                renkli_kart(
                    "Toplam Eksik Tahsilat", f"${_toplam_eksik:,.2f}", "#dc2626", "⚠️"
                )
                st.caption(t("eksik_tahsilat_ozet").format(sayi=len(_eksik_tahsilat)))
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
            st.subheader(t("boyut_agirlik_baslik"))
            st.caption(tc(
                "Musteriye beyan ettigimiz (gelir dosyasindaki) ile kargo firmasinin "
                "faturasindaki olcumleri **hacim** (uzunluk x genislik x yukseklik) ve "
                "**agirlik** olarak karsilastirir - tek tek kenar (uzunluk/genislik/"
                "yukseklik) karsilastirilmaz, cunku firmalar hangi kenara 'uzunluk' "
                "hangisine 'genislik' dedigini bizden farkli siralayabiliyor; hacim "
                "carpimda sira onemli olmadigi icin bu sorunu ortadan kaldirir.\n\n"
                "Sadece **hem bizim hem firmanin olcusu birlikte mevcut olan** ve "
                "ZARAR ettigimiz (Kar/Zarar < 0) gonderileri gosterir.\n\n"
                "⚠️ Not 1: Su an sadece **FedEx, Asendia ve UniUni** fatura dosyalarinda "
                "boyut/agirlik bilgisi bulunuyor. UPS ve ByeLabel grubu firmalarinin "
                "fatura formatlarinda bu bilgi yok, bu yuzden o gonderiler bu listede "
                "gorunmez.\n\n"
                "⚠️ Not 2: Bizim olcum birimimiz (inc/lb) ile bazi firmalarin kendi "
                "birimi (orn. cm/kg) farkli olabilir - 'Hacim Orani' sutunu TUM "
                "satirlarda benzer, tutarli bir kat gosteriyorsa (orn. hep ~16x gibi) "
                "bu bir birim farkindan kaynaklaniyor olabilir, gercek bir uyusmazliktan "
                "degil. Soyle bir durumda bana haber ver, birim cevrimini ekleyelim."
            ))

            _gerekli_kolonlar = [
                "Musteri_Length", "Musteri_Width", "Musteri_Height", "Musteri_Weight",
                "Firma_Length", "Firma_Width", "Firma_Height", "Firma_Weight",
            ]
            _boyut_df = merged[
                (merged["Durum"] == "Eslesti")
                & (merged["Kar"] < 0)
                & (merged[_gerekli_kolonlar].notna().all(axis=1))
            ].copy()

            if _boyut_df.empty:
                st.success(
                    "Zarar eden ve hem bizim hem firmanin tam olcu bilgisi (uzunluk, "
                    "genislik, yukseklik, agirlik) birlikte mevcut oldugu bir gonderi "
                    "bulunamadi. 🎉"
                )
            else:
                _boyut_df["Bizim_Hacim"] = (
                    _boyut_df["Musteri_Length"] * _boyut_df["Musteri_Width"] * _boyut_df["Musteri_Height"]
                )
                _boyut_df["Firma_Hacim"] = (
                    _boyut_df["Firma_Length"] * _boyut_df["Firma_Width"] * _boyut_df["Firma_Height"]
                )
                _boyut_df["Hacim_Orani"] = _boyut_df["Firma_Hacim"] / _boyut_df["Bizim_Hacim"].replace(0, pd.NA)
                _boyut_df["Agirlik_Farki"] = _boyut_df["Firma_Weight"] - _boyut_df["Musteri_Weight"]

                _boyut_tablo = _boyut_df[[
                    "Track Number", "Carrier Name", "User Name",
                    "Bizim_Hacim", "Firma_Hacim", "Hacim_Orani",
                    "Musteri_Weight", "Firma_Weight", "Agirlik_Farki",
                    "Kar",
                ]].rename(columns={
                    "Track Number": "Takip No",
                    "Carrier Name": "Kargo Firmasi",
                    "User Name": "Musteri",
                    "Bizim_Hacim": "Bizim Hacim",
                    "Firma_Hacim": "Firma Hacim",
                    "Hacim_Orani": "Hacim Orani (x)",
                    "Musteri_Weight": "Bizim Agirlik",
                    "Firma_Weight": "Firma Agirlik",
                    "Agirlik_Farki": "Agirlik Farki",
                    "Kar": "Kar/Zarar",
                }).sort_values("Kar/Zarar")
                _boyut_tablo["Takip No"] = _boyut_tablo["Takip No"].astype(str)

                renkli_kart(
                    "Zarar Eden Boyut Uyusmazlikli Paket Sayisi", f"{len(_boyut_tablo)}", "#dc2626", "📦"
                )
                st.caption(
                    t("toplam_zarar_metni").format(
                        tutar=_boyut_tablo['Kar/Zarar'].sum(), sayi=len(_boyut_tablo)
                    )
                )

                st.dataframe(
                    _boyut_tablo.style.format(
                        {
                            "Bizim Hacim": "{:,.1f}",
                            "Firma Hacim": "{:,.1f}",
                            "Hacim Orani (x)": "{:,.2f}x",
                            "Bizim Agirlik": "{:,.2f}",
                            "Firma Agirlik": "{:,.2f}",
                            "Agirlik Farki": "{:,.2f}",
                            "Kar/Zarar": "${:,.2f}",
                        },
                        na_rep="-",
                    ).map(kar_zarar_stil, subset=["Kar/Zarar"]),
                    width="stretch",
                    hide_index=True,
                )
                indirme_butonlari(_boyut_tablo, "boyut_agirlik_uyusmazligi", "boyut_uyusmazlik")

        elif analiz_secimi == "Gider Bulunamayanlar":
            st.subheader(t("gider_bulunamayan_baslik"))
            not_found = merged[merged["Durum"] == "Gider bulunamadi"]
            st.caption(tc(
                "Bu gonderiler icin takip numarasi var ama yuklenen gider dosyalarinda "
                "karsiligi bulunamadi. Henuz faturalanmamis olabilir, veya ait oldugu "
                "kargo firmasinin dosyasi yuklenmemis olabilir."
            ))
            not_found_display = not_found[["Shipment No", "Track Number", "Carrier Name", "Status", "Invoice Amount"]]
            st.dataframe(not_found_display, width="stretch", hide_index=True)
            indirme_butonlari(not_found_display, "gider_bulunamayanlar", "tab2")

        elif analiz_secimi == "Eslesmeyen Gider":
            st.subheader(t("eslesmeyen_gider_baslik"))
            st.caption(tc(
                "Bu takip numaralari kargo firmasinin fatura listesinde var ama gelir "
                "dosyasinda eslesen bir gonderi bulunamadi. Farkli ay/musteri donemine "
                "ait olabilir, kontrol etmekte fayda var."
            ))
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
        st.info(t("baslamak_icin_yukle"))
