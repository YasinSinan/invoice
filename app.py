"""
Depo gelir-gider karsilastirma araci.

Calistirmak icin:
    streamlit run app.py
"""

import io

import pandas as pd
import streamlit as st

from processing import (
    BYELABEL_GROUP_LABEL,
    CARRIER_PROFILES,
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

st.set_page_config(page_title="Gelir-Gider Karsilastirma", layout="wide")

st.title("Depo Gelir-Gider Karsilastirma Araci")
st.caption(
    "Musteri faturasi (gelir) ve kargo firmasi faturasi (gider) dosyalarini "
    "yukleyin, paket/takip numarasina gore otomatik eslestirip kar-zarar raporu alin."
)

# ---------------------------------------------------------------- yukleme ---
col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Gelir dosyasi")
    st.caption("WH_CUSTOMER_SHIPMENT_LIST formatinda, musteriden alinan tutarlari iceren dosya.")
    income_file = st.file_uploader("Gelir Excel dosyasini secin", type=["xlsx"], key="income")
    only_paid = st.checkbox(
        "Sadece odenmis gonderileri dahil et (Status = Paid)",
        value=True,
        help="Isaretliyse User Cancelled, New Shipment, Payment Waiting gibi durumlar disarida tutulur.",
    )

with col2:
    st.subheader("2. Gider dosyalari")
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

st.subheader("3. Manuel gider (opsiyonel)")
st.caption(
    "Hicbir pakete baglanmayan, dogrudan net kardan dusulecek giderler "
    "(orn. depo kirasi, personel maasi, internet faturasi). Sadece aciklama "
    "ve tutar girin; satir eklemek/silmek icin tablonun altindaki + / cop "
    "kutusu ikonlarini kullanin."
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

run = st.button("Hesapla", type="primary", disabled=income_file is None)

# ---------------------------------------------------------------- hesapla ---
if run and income_file is not None:
    try:
        income_df = load_income_file(income_file, only_paid=only_paid)
    except ValueError as e:
        st.error(f"Gelir dosyasi okunamadi: {e}")
        st.stop()

    cost_dfs = []
    warnings = []
    toplam_genel_gider = 0.0
    genel_gider_detay = []
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
                    genel_gider_detay.append((BYELABEL_GROUP_LABEL, f.name, group_genel_gider))
                for bd in group_breakdown_dfs:
                    breakdown_dfs.append(bd)
            else:
                cost_df, warning, genel_gider, breakdown_df = load_cost_file(f, secilen)
                cost_dfs.append(cost_df)
                if warning:
                    warnings.append(warning)
                if genel_gider:
                    toplam_genel_gider += genel_gider
                    genel_gider_detay.append((secilen, f.name, genel_gider))
                if not breakdown_df.empty:
                    breakdown_dfs.append(breakdown_df)
        except ValueError as e:
            st.error(f"{f.name} okunamadi: {e}")
            st.stop()

    for w in warnings:
        st.warning(w)

    manuel_gider_toplam = manual_expense_total(manual_expenses_df)
    toplam_genel_gider += manuel_gider_toplam

    merged, unmatched_cost = build_report(income_df, cost_dfs)
    summary = summarize(merged, genel_gider=toplam_genel_gider)

    st.divider()
    st.subheader("Ozet")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Toplam gelir", f"${summary['toplam_gelir']:,.2f}")
    m2.metric("Kargo gideri", f"${summary['toplam_gider_kargo']:,.2f}")
    m3.metric("Vergi/gumruk gideri", f"${summary['toplam_gider_tax']:,.2f}")
    m4.metric("Toplam gider", f"${summary['toplam_gider_eslesen']:,.2f}")
    m5.metric("Kar (pakete dagitilan)", f"${summary['toplam_kar']:,.2f}")

    if toplam_genel_gider:
        n1, n2 = st.columns(2)
        n1.metric(
            "Genel gider (pakete baglanamayan vergi/komisyon + manuel)",
            f"${summary['genel_gider']:,.2f}",
            help="Takip numarasi olmayan vergi/komisyon satirlari (orn. UPS Brokerage/Government Charges) ile manuel girilen giderlerin toplami.",
        )
        n2.metric("Net kar (genel gider dusulmus)", f"${summary['net_kar']:,.2f}")

        with st.expander("Genel gider detayi (firma/dosya + manuel girisler)"):
            if genel_gider_detay:
                st.dataframe(
                    pd.DataFrame(genel_gider_detay, columns=["Kargo Firmasi", "Dosya", "Genel Gider"]),
                    use_container_width=True,
                    hide_index=True,
                )
            if manuel_gider_toplam:
                st.write(f"Manuel giderler toplami: ${manuel_gider_toplam:,.2f}")
                st.dataframe(manual_expenses_df, use_container_width=True, hide_index=True)

    eslesme_orani = summary["eslesen_sayisi"] / summary["toplam_gonderi"] * 100 if summary["toplam_gonderi"] else 0
    st.caption(f"Eslesme orani: %{eslesme_orani:.1f}")

    st.caption(
        f"Toplam {summary['toplam_gonderi']} gonderi  |  "
        f"{summary['eslesen_sayisi']} eslesti  |  "
        f"{summary['gider_bulunamadi_sayisi']} gider bulunamadi  |  "
        f"{summary['takip_no_yok_sayisi']} takip no yok"
    )

    st.subheader("Kargo Firmalarina Gore Analiz")
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
        ),
        use_container_width=True,
        hide_index=True,
    )

    if breakdown_dfs:
        st.caption(
            "Asagidaki tablo her dosyada hangi kategori/sutunun Kargo, hangisinin "
            "Vergi, hangisinin (takip numarasi olmadigi icin) Genel Gider sayildigini "
            "ve ne kadar tutar tasidigini gosterir."
        )
        full_breakdown = pd.concat(breakdown_dfs, ignore_index=True)
        st.dataframe(
            full_breakdown.style.format({"Tutar": "${:,.2f}"}),
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Ulkeye gore analiz")
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
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    st.subheader("Musteriye gore analiz")
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
        ),
        use_container_width=True,
        hide_index=True,
    )

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
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    tab1, tab2, tab3 = st.tabs(["Detayli rapor", "Gider bulunamayanlar", "Eslesmeyen gider (fatura listesinde var, gelirde yok)"])

    with tab1:
        st.dataframe(
            merged[
                [
                    "Shipment No",
                    "Track Number",
                    "Carrier Name",
                    "Status",
                    "Invoice Amount",
                    "Gider_Kargo",
                    "Gider_Tax",
                    "Gider",
                    "Kar",
                    "Durum",
                    "Added Date",
                ]
            ]
            .rename(columns={"Gider_Kargo": "Kargo Gideri", "Gider_Tax": "Vergi/Gumruk", "Gider": "Toplam Gider"})
            .sort_values("Added Date"),
            use_container_width=True,
            hide_index=True,
        )

    with tab2:
        not_found = merged[merged["Durum"] == "Gider bulunamadi"]
        st.caption(
            "Bu gonderiler icin takip numarasi var ama yuklenen gider dosyalarinda "
            "karsiligi bulunamadi. Henuz faturalanmamis olabilir, veya ait oldugu "
            "kargo firmasinin dosyasi yuklenmemis olabilir."
        )
        st.dataframe(
            not_found[["Shipment No", "Track Number", "Carrier Name", "Status", "Invoice Amount"]],
            use_container_width=True,
            hide_index=True,
        )

    with tab3:
        st.caption(
            "Bu takip numaralari kargo firmasinin fatura listesinde var ama gelir "
            "dosyasinda eslesen bir gonderi bulunamadi. Farkli ay/musteri donemine "
            "ait olabilir, kontrol etmekte fayda var."
        )
        st.dataframe(unmatched_cost, use_container_width=True, hide_index=True)

    st.divider()

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        merged.drop(columns=["Takip_Var_Mi", "TrackingKey"]).to_excel(writer, sheet_name="Detayli Rapor", index=False)
        not_found.drop(columns=["Takip_Var_Mi", "TrackingKey"], errors="ignore").to_excel(
            writer, sheet_name="Gider Bulunamayan", index=False
        )
        unmatched_cost.to_excel(writer, sheet_name="Eslesmeyen Gider", index=False)
        if breakdown_dfs:
            pd.concat(breakdown_dfs, ignore_index=True).to_excel(
                writer, sheet_name="Kargo-Vergi Detayi", index=False
            )
        cb.to_excel(writer, sheet_name="Ulke Bazinda", index=False)
        carrier_table.to_excel(writer, sheet_name="Kargo Firmasi Bazinda", index=False)
        cust_table.to_excel(writer, sheet_name="Musteri Bazinda", index=False)
        cust_country_table.to_excel(writer, sheet_name="Musteri x Ulke", index=False)
        if manuel_gider_toplam:
            manual_expenses_df.to_excel(writer, sheet_name="Manuel Giderler", index=False)

    st.download_button(
        "Raporu Excel olarak indir",
        data=buffer.getvalue(),
        file_name="gelir_gider_raporu.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

elif not income_file:
    st.info("Baslamak icin once gelir dosyasini yukleyin.")
