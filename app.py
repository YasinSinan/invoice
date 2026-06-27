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
    load_byelabel_group,
    load_cost_file,
    load_income_file,
    manual_expense_total,
    summarize,
)
from github_storage import GithubStorageError, delete_report, list_saved_reports, load_report, save_report

st.set_page_config(page_title="Gelir-Gider Karsilastirma", layout="wide")


def _hex_to_rgba(hex_renk, alpha):
    hex_renk = hex_renk.lstrip("#")
    r, g, b = int(hex_renk[0:2], 16), int(hex_renk[2:4], 16), int(hex_renk[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def renkli_kart(etiket, deger, renk, icon=""):
    """Varsayilan st.metric yerine renkli, ikonlu bir kart gosterir."""
    arka_plan = _hex_to_rgba(renk, 0.12)
    st.markdown(
        f"""
        <div style="
            background: {arka_plan};
            border-left: 5px solid {renk};
            border-radius: 10px;
            padding: 16px 20px;
            margin-bottom: 10px;
        ">
            <div style="font-size: 13px; font-weight: 600; opacity: 0.75; letter-spacing: 0.02em;">{icon} {etiket}</div>
            <div style="font-size: 28px; font-weight: 800; color: {renk}; margin-top: 2px;">{deger}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kar_zarar_stil(val):
    """Kar/zarar hucresini pozitifse yesil, negatifse kirmizi vurgular."""
    if pd.isna(val):
        return ""
    if val < 0:
        return "background-color: rgba(239, 68, 68, 0.16); color: #dc2626; font-weight: 700;"
    if val > 0:
        return "background-color: rgba(16, 185, 129, 0.16); color: #059669; font-weight: 700;"
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


st.title("Depo Gelir-Gider Karsilastirma Araci")
st.caption(
    "Musteri faturasi (gelir) ve kargo firmasi faturasi (gider) dosyalarini "
    "yukleyin, paket/takip numarasina gore otomatik eslestirip kar-zarar raporu alin."
)

# ------------------------------------------------------------ gecmis analiz ---
with st.expander("Gecmis analizler (aylik kayitlar)", expanded=False):
    try:
        saved_periods = list_saved_reports()
    except GithubStorageError as e:
        saved_periods = None
        st.info(
            "Gecmis analizleri kaydetme/goruntuleme ozelligi henuz kurulmadi. "
            f"({e})"
        )

    if saved_periods is not None:
        if not saved_periods:
            st.caption("Henuz kayitli bir analiz yok. Asagida hesaplama yaptiktan sonra kaydedebilirsin.")
        else:
            secilen_donem = st.selectbox("Bir donem secin", options=saved_periods, key="gecmis_donem_secimi")

            col_goruntule, col_sil = st.columns([1, 1])
            with col_goruntule:
                if st.button("Goruntule", key="gecmis_goruntule_buton"):
                    st.session_state["gecmis_goruntulenecek_donem"] = secilen_donem
            with col_sil:
                if st.button("Sil (geri alinamaz)", key="gecmis_sil_buton"):
                    try:
                        delete_report(secilen_donem)
                        st.success(f"'{secilen_donem}' donemi silindi.")
                        if st.session_state.get("gecmis_goruntulenecek_donem") == secilen_donem:
                            st.session_state.pop("gecmis_goruntulenecek_donem", None)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Silinemedi: {e}")

            goruntulenecek_donem = st.session_state.get("gecmis_goruntulenecek_donem")
            if goruntulenecek_donem and goruntulenecek_donem in saved_periods:
                try:
                    rapor = load_report(goruntulenecek_donem)
                    st.caption(f"Kayit tarihi: {rapor.get('saved_at', '-')}")

                    s = rapor["summary"]
                    renkli_kart("Toplam Paket Sayisi", f"{s['toplam_gonderi']:,}", "#6366f1", "📦")

                    st.markdown("")
                    g_gelir, g_gider = st.columns(2)
                    with g_gelir:
                        st.markdown("**💰 Gelir**")
                        renkli_kart("Toplam Gelir", f"${s['toplam_gelir']:,.2f}", "#10b981", "💵")
                        if s.get("manuel_gelir"):
                            renkli_kart("Manuel Gelir", f"${s['manuel_gelir']:,.2f}", "#14b8a6", "✍️")
                    with g_gider:
                        st.markdown("**💸 Gider**")
                        renkli_kart("Kargo Gideri", f"${s['toplam_gider_kargo']:,.2f}", "#f59e0b", "🚚")
                        renkli_kart("Vergi/Gumruk Gideri", f"${s['toplam_gider_tax']:,.2f}", "#f97316", "🛂")
                        renkli_kart("Toplam Gider", f"${s['toplam_gider_eslesen']:,.2f}", "#ef4444", "🧾")
                        if s.get("genel_gider"):
                            renkli_kart("Genel Gider", f"${s['genel_gider']:,.2f}", "#dc2626", "⚠️")

                    st.markdown("")
                    _, g_kar_orta, _ = st.columns([1, 1, 1])
                    with g_kar_orta:
                        g_net_kar_renk = "#10b981" if s["net_kar"] >= 0 else "#dc2626"
                        g_net_kar_icon = "📈" if s["net_kar"] >= 0 else "📉"
                        renkli_kart("Net Kar", f"${s['net_kar']:,.2f}", g_net_kar_renk, g_net_kar_icon)

                    st.markdown("**🚚 Kargo firmalarina gore analiz**")
                    gecmis_carrier_df = pd.DataFrame(rapor["carrier_table"])
                    gecmis_carrier_kar_kolonlari = [c for c in ["Kar/Zarar", "Paket Basi Kar/Zarar"] if c in gecmis_carrier_df.columns]
                    st.dataframe(
                        gecmis_carrier_df.style.map(kar_zarar_stil, subset=gecmis_carrier_kar_kolonlari)
                        if gecmis_carrier_kar_kolonlari
                        else gecmis_carrier_df,
                        use_container_width=True,
                        hide_index=True,
                    )
                    indirme_butonlari(gecmis_carrier_df, f"{goruntulenecek_donem}_kargo_firmasi", "gecmis_carrier")

                    st.markdown("**🌍 Ulkeye gore analiz**")
                    gecmis_country_df = pd.DataFrame(rapor["country_table"])
                    gecmis_country_kar_kolonlari = [c for c in ["Kar", "Paket_Basi_Kar"] if c in gecmis_country_df.columns]
                    st.dataframe(
                        gecmis_country_df.style.map(kar_zarar_stil, subset=gecmis_country_kar_kolonlari)
                        if gecmis_country_kar_kolonlari
                        else gecmis_country_df,
                        use_container_width=True,
                        hide_index=True,
                    )
                    indirme_butonlari(gecmis_country_df, f"{goruntulenecek_donem}_ulke", "gecmis_country")

                    st.markdown("**👥 Musteriye gore analiz**")
                    gecmis_customer_df = pd.DataFrame(rapor["customer_table"])
                    gecmis_customer_kar_kolonlari = [c for c in ["Kar/Zarar", "Paket Basi Kar/Zarar"] if c in gecmis_customer_df.columns]
                    st.dataframe(
                        gecmis_customer_df.style.map(kar_zarar_stil, subset=gecmis_customer_kar_kolonlari)
                        if gecmis_customer_kar_kolonlari
                        else gecmis_customer_df,
                        use_container_width=True,
                        hide_index=True,
                    )
                    indirme_butonlari(gecmis_customer_df, f"{goruntulenecek_donem}_musteri", "gecmis_customer")
                except Exception as e:
                    st.error(f"Rapor yuklenemedi: {e}")

st.divider()

# ---------------------------------------------------------------- yukleme ---
col1, col2 = st.columns(2)

with col1:
    st.subheader("Gelir")
    st.caption("WH_CUSTOMER_SHIPMENT_LIST formatinda, musteriden alinan tutarlari iceren dosya.")
    income_file = st.file_uploader("Gelir Excel dosyasini secin", type=["xlsx"], key="income")
    only_paid = st.checkbox(
        "Sadece odenmis gonderileri dahil et (Status = Paid)",
        value=True,
        help="Isaretliyse User Cancelled, New Shipment, Payment Waiting gibi durumlar disarida tutulur.",
    )
    exclude_unassigned_carrier = st.checkbox(
        "Kargo firmasi atanmamis gonderileri haric tut",
        value=True,
        help="Isaretliyse Carrier Name (kargo firmasi) bos olan gonderiler analize hic dahil edilmez.",
    )

    st.markdown("**Manuel gelir (opsiyonel)**")
    st.caption(
        "Hicbir pakete baglanmayan, dogrudan net kara eklenecek gelirler "
        "(orn. depo kirasi geliri, danismanlik geliri)."
    )
    manual_income_df = st.data_editor(
        pd.DataFrame({"Aciklama": pd.Series(dtype="str"), "Tutar": pd.Series(dtype="float")}),
        num_rows="dynamic",
        column_config={
            "Aciklama": st.column_config.TextColumn("Aciklama"),
            "Tutar": st.column_config.NumberColumn("Tutar ($)", format="$%.2f"),
        },
        use_container_width=True,
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

    st.markdown("**Manuel gider (opsiyonel)**")
    st.caption(
        "Hicbir pakete baglanmayan, dogrudan net kardan dusulecek giderler "
        "(orn. depo kirasi, personel maasi, internet faturasi)."
    )
    manual_expenses_df = st.data_editor(
        pd.DataFrame({"Aciklama": pd.Series(dtype="str"), "Tutar": pd.Series(dtype="float")}),
        num_rows="dynamic",
        column_config={
            "Aciklama": st.column_config.TextColumn("Aciklama"),
            "Tutar": st.column_config.NumberColumn("Tutar ($)", format="$%.2f"),
        },
        use_container_width=True,
        key="manual_expenses_editor",
    )

    st.markdown("**Paket basina ek gider - firma bazinda (opsiyonel)**")
    st.caption(
        "Belirli bir kargo firmasinin HER paketine ayni tutari ekler (orn. "
        "UniUni icin paket basina $2). Tutar otomatik olarak paket sayisiyla "
        "carpilir ve her paketin kar/zarar hesabina islenir - tum tablolarda "
        "(ulke, firma, musteri) otomatik yansir. Gideri eslesmemis paketler "
        "bu tutari aldiktan sonra 'eslesti' sayilir."
    )
    manual_carrier_expenses_df = st.data_editor(
        pd.DataFrame(
            {
                "Kargo Firmasi": pd.Series(dtype="str"),
                "Aciklama": pd.Series(dtype="str"),
                "Paket Basi Tutar": pd.Series(dtype="float"),
            }
        ),
        num_rows="dynamic",
        column_config={
            "Kargo Firmasi": st.column_config.SelectboxColumn("Kargo Firmasi", options=KNOWN_CARRIERS),
            "Aciklama": st.column_config.TextColumn("Aciklama"),
            "Paket Basi Tutar": st.column_config.NumberColumn("Paket Basi Tutar ($)", format="$%.2f"),
        },
        use_container_width=True,
        key="manual_carrier_expenses_editor",
    )

if st.button("Hesapla", type="primary", disabled=income_file is None):
    st.session_state["hesapla_tiklandi"] = True

# ---------------------------------------------------------------- hesapla ---
if st.session_state.get("hesapla_tiklandi") and income_file is not None:
    try:
        income_df = load_income_file(
            income_file, only_paid=only_paid, exclude_unassigned_carrier=exclude_unassigned_carrier
        )
    except ValueError as e:
        st.error(f"Gelir dosyasi okunamadi: {e}")
        st.stop()

    cost_dfs = []
    warnings = []
    toplam_genel_gider = 0.0
    breakdown_dfs = []
    for f in cost_files or []:
        try:
            secilen = carrier_for_file[f.name]
            if secilen == BYELABEL_GROUP_LABEL:
                group_cost_dfs, group_warnings, group_genel_gider, group_breakdown_dfs = load_byelabel_group(f)
                cost_dfs.extend(group_cost_dfs)
                warnings.extend(group_warnings)
                if group_genel_gider:
                    toplam_genel_gider += group_genel_gider
                for bd in group_breakdown_dfs:
                    breakdown_dfs.append(bd)
            else:
                cost_df, warning, genel_gider, breakdown_df = load_cost_file(f, secilen)
                cost_dfs.append(cost_df)
                if warning:
                    warnings.append(warning)
                if genel_gider:
                    toplam_genel_gider += genel_gider
                if not breakdown_df.empty:
                    breakdown_dfs.append(breakdown_df)
        except ValueError as e:
            st.error(f"{f.name} okunamadi: {e}")
            st.stop()

    for w in warnings:
        st.warning(w)

    manuel_gider_toplam = manual_expense_total(manual_expenses_df)
    toplam_genel_gider += manuel_gider_toplam
    manuel_gelir_toplam = manual_expense_total(manual_income_df)

    full_breakdown = pd.concat(breakdown_dfs, ignore_index=True) if breakdown_dfs else pd.DataFrame()
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

    if not gecerli_manuel_gelir.empty or not gecerli_manuel_gider.empty or has_per_package_fee:
        col_mg, col_mgid = st.columns(2)
        with col_mg:
            if not gecerli_manuel_gelir.empty:
                st.caption("Manuel gelir kalemleri:")
                st.dataframe(
                    gecerli_manuel_gelir.style.format({"Tutar": "${:,.2f}"}),
                    use_container_width=True,
                    hide_index=True,
                )
        with col_mgid:
            if not gecerli_manuel_gider.empty:
                st.caption("Manuel gider kalemleri:")
                st.dataframe(
                    gecerli_manuel_gider.style.format({"Tutar": "${:,.2f}"}),
                    use_container_width=True,
                    hide_index=True,
                )
            if has_per_package_fee:
                st.caption("Paket basina eklenen gider (firma bazinda):")
                st.dataframe(
                    gecerli_paket_basi[["Kargo Firmasi", "Aciklama", "Paket Basi Tutar"]].style.format(
                        {"Paket Basi Tutar": "${:,.2f}"}
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

    st.markdown("")
    _, kar_orta, _ = st.columns([1, 1, 1])
    with kar_orta:
        net_kar_renk = "#10b981" if summary["net_kar"] >= 0 else "#dc2626"
        net_kar_icon = "📈" if summary["net_kar"] >= 0 else "📉"
        renkli_kart("Net Kar", f"${summary['net_kar']:,.2f}", net_kar_renk, net_kar_icon)

    if not genel_gider_kategori_detay.empty:
        st.caption(
            "⚠️ Pakete baglanamayan vergi/komisyon - otomatik tespit edilen "
            "(hangi kategorinin dosyadaki hangi sutundan geldigi ile birlikte):"
        )
        st.dataframe(
            genel_gider_kategori_detay.style.format({"Genel Gider": "${:,.2f}"}),
            use_container_width=True,
            hide_index=True,
        )
        indirme_butonlari(genel_gider_kategori_detay, "genel_gider_detayi", "genel_gider_detay")

    if has_per_package_fee:
        st.caption(
            "📦 Paket basina eklenen ek gider - kac pakete uygulandigi ve toplam tutar "
            "(bu zaten yukaridaki Net Kar rakamina islenmis durumda, Genel Gider'e dahil degil):"
        )
        detay_satirlari = []
        for _, r in gecerli_paket_basi.iterrows():
            etkilenen = int(((merged["Carrier Name"] == r["Kargo Firmasi"]) & merged["Takip_Var_Mi"]).sum())
            toplam_eklenen = etkilenen * float(r["Paket Basi Tutar"])
            detay_satirlari.append(
                (r["Kargo Firmasi"], r.get("Aciklama", ""), r["Paket Basi Tutar"], etkilenen, toplam_eklenen)
            )
        detay_df = pd.DataFrame(
            detay_satirlari,
            columns=["Kargo Firmasi", "Aciklama", "Paket Basi Tutar", "Etkilenen Paket Sayisi", "Toplam Eklenen Gider"],
        )
        st.dataframe(
            detay_df.style.format({"Paket Basi Tutar": "${:,.2f}", "Toplam Eklenen Gider": "${:,.2f}"}),
            use_container_width=True,
            hide_index=True,
        )

    eslesme_orani = summary["eslesen_sayisi"] / summary["toplam_gonderi"] * 100 if summary["toplam_gonderi"] else 0
    st.caption(f"Eslesme orani: %{eslesme_orani:.1f}")

    st.caption(
        f"Toplam {summary['toplam_gonderi']} gonderi  |  "
        f"{summary['eslesen_sayisi']} eslesti  |  "
        f"{summary['gider_bulunamadi_sayisi']} gider bulunamadi  |  "
        f"{summary['takip_no_yok_sayisi']} takip no yok"
    )

    st.subheader("🚚 Kargo Firmalarina Gore Analiz")
    st.caption(
        "Kargo firmasi (gelir dosyasindaki Carrier Name) bazinda paket sayisi, "
        "gelir, gider ve kar/zarar dagilimi."
    )
    carrier_table = carrier_breakdown(merged)
    st.dataframe(
        carrier_table.style.format(
            {
                "Toplam Gelir": "${:,.2f}",
                "Kargo Gideri": "${:,.2f}",
                "Vergi Gideri": "${:,.2f}",
                "Toplam Gider": "${:,.2f}",
                "Kar/Zarar": "${:,.2f}",
                "Paket Basi Kar/Zarar": "${:,.2f}",
            }
        ).map(kar_zarar_stil, subset=["Kar/Zarar", "Paket Basi Kar/Zarar"]),
        use_container_width=True,
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
            use_container_width=True,
            hide_index=True,
        )
        indirme_butonlari(full_breakdown, "kargo_vergi_siniflandirma", "full_breakdown")

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
                "Kargo_Gideri": "${:,.2f}",
                "Vergi_Gideri": "${:,.2f}",
                "Toplam_Gider": "${:,.2f}",
                "Kar": "${:,.2f}",
                "Paket_Basi_Kar": "${:,.2f}",
            }
        ).map(kar_zarar_stil, subset=["Kar", "Paket_Basi_Kar"]),
        use_container_width=True,
        hide_index=True,
    )
    indirme_butonlari(cb, "ulkeye_gore_analiz", "country_table")

    st.divider()

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
        use_container_width=True,
        hide_index=True,
    )
    indirme_butonlari(cust_table, "musteriye_gore_analiz", "cust_table")

    st.caption(
        "Asagidaki tablo her musterinin HER ULKEDE ayri ayri kar mi zarar mi "
        "ettirdigini gosterir (en zararli kombinasyonlar basta). Genel toplamda "
        "kar gibi gorunen bir musteri, bazi ulkelerde zarar ettiriyor olabilir."
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
        use_container_width=True,
        hide_index=True,
    )
    indirme_butonlari(cust_country_table, "musteri_x_ulke_analizi", "cust_country_table")

    st.divider()

    tab1, tab2, tab3 = st.tabs(
        ["📋 Detayli rapor", "🔍 Gider bulunamayanlar", "⚖️ Eslesmeyen gider (fatura listesinde var, gelirde yok)"]
    )

    with tab1:
        detayli_rapor_df = merged.sort_values("Added Date")[
            [
                "Shipment No",
                "Track Number",
                "Carrier Name",
                "Invoice Amount",
                "Gider_Kargo",
                "Gider_Tax",
                "Gider",
                "Gider_Kalemleri",
                "Kar",
            ]
        ].rename(
            columns={
                "Gider_Kargo": "Kargo Gideri",
                "Gider_Tax": "Vergi/Gumruk",
                "Gider": "Toplam Gider",
                "Gider_Kalemleri": "Gider Kalemleri",
            }
        )
        st.dataframe(
            detayli_rapor_df.style.format(
                {"Invoice Amount": "${:,.2f}", "Kargo Gideri": "${:,.2f}", "Vergi/Gumruk": "${:,.2f}", "Toplam Gider": "${:,.2f}", "Kar": "${:,.2f}"}
            ).map(kar_zarar_stil, subset=["Kar"]),
            use_container_width=True,
            hide_index=True,
        )
        indirme_butonlari(detayli_rapor_df, "detayli_rapor", "tab1")

    with tab2:
        not_found = merged[merged["Durum"] == "Gider bulunamadi"]
        st.caption(
            "Bu gonderiler icin takip numarasi var ama yuklenen gider dosyalarinda "
            "karsiligi bulunamadi. Henuz faturalanmamis olabilir, veya ait oldugu "
            "kargo firmasinin dosyasi yuklenmemis olabilir."
        )
        not_found_display = not_found[["Shipment No", "Track Number", "Carrier Name", "Status", "Invoice Amount"]]
        st.dataframe(not_found_display, use_container_width=True, hide_index=True)
        indirme_butonlari(not_found_display, "gider_bulunamayanlar", "tab2")

    with tab3:
        st.caption(
            "Bu takip numaralari kargo firmasinin fatura listesinde var ama gelir "
            "dosyasinda eslesen bir gonderi bulunamadi. Farkli ay/musteri donemine "
            "ait olabilir, kontrol etmekte fayda var."
        )
        st.dataframe(unmatched_cost, use_container_width=True, hide_index=True)
        indirme_butonlari(unmatched_cost, "eslesmeyen_gider", "tab3")

    st.divider()

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        merged.drop(columns=["Takip_Var_Mi", "TrackingKey"]).to_excel(writer, sheet_name="Detayli Rapor", index=False)
        not_found.drop(columns=["Takip_Var_Mi", "TrackingKey"], errors="ignore").to_excel(
            writer, sheet_name="Gider Bulunamayan", index=False
        )
        unmatched_cost.to_excel(writer, sheet_name="Eslesmeyen Gider", index=False)
        if not full_breakdown.empty:
            full_breakdown.to_excel(writer, sheet_name="Kargo-Vergi Detayi", index=False)
        cb.to_excel(writer, sheet_name="Ulke Bazinda", index=False)
        carrier_table.to_excel(writer, sheet_name="Kargo Firmasi Bazinda", index=False)
        cust_table.to_excel(writer, sheet_name="Musteri Bazinda", index=False)
        cust_country_table.to_excel(writer, sheet_name="Musteri x Ulke", index=False)
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

    st.divider()
    st.subheader("Bu analizi kaydet (gecmis analizler icin)")
    st.caption(
        "Bu hesaplamayi bir donem etiketiyle (orn. 2026-06) GitHub reposuna "
        "kaydeder. Daha sonra sayfanin en ustundeki 'Gecmis analizler' "
        "bolumunden tekrar goruntuleyebilirsin."
    )
    varsayilan_donem = datetime.now().strftime("%Y-%m")
    donem_etiketi = st.text_input("Donem etiketi", value=varsayilan_donem, key="kayit_donem_etiketi")
    if st.button("GitHub'a kaydet", key="kayit_buton"):
        try:
            payload = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
                "carrier_table": carrier_table.to_dict("records"),
                "country_table": cb.to_dict("records"),
                "customer_table": cust_table.to_dict("records"),
                "customer_country_table": cust_country_table.to_dict("records"),
            }
            save_report(donem_etiketi, payload)
            st.success(f"'{donem_etiketi}' donemi olarak kaydedildi.")
        except GithubStorageError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Kaydetme sirasinda bir hata olustu: {e}")

elif not income_file:
    st.info("Baslamak icin once gelir dosyasini yukleyin.")
