"""
Depo gelir-gider karsilastirma araci.

Calistirmak icin:
    streamlit run app.py
"""

import io

import pandas as pd
import streamlit as st

from processing import CARRIER_PROFILES, build_report, load_cost_file, load_income_file, summarize

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
            options=list(CARRIER_PROFILES.keys()),
            key=f"carrier_{f.name}",
        )
    st.caption(
        "Su an Asendia, UniUni, UPS, ePost Global, DHL, intelcom, APC, USPS, "
        "Evri, Purolator ve FedEx destekleniyor."
    )

run = st.button("Hesapla", type="primary", disabled=income_file is None)

# ---------------------------------------------------------------- hesapla ---
if run and income_file is not None:
    try:
        income_df = load_income_file(income_file)
    except ValueError as e:
        st.error(f"Gelir dosyasi okunamadi: {e}")
        st.stop()

    cost_dfs = []
    warnings = []
    for f in cost_files or []:
        try:
            cost_df, warning = load_cost_file(f, carrier_for_file[f.name])
            cost_dfs.append(cost_df)
            if warning:
                warnings.append(warning)
        except ValueError as e:
            st.error(f"{f.name} okunamadi: {e}")
            st.stop()

    for w in warnings:
        st.warning(w)

    merged, unmatched_cost = build_report(income_df, cost_dfs)
    summary = summarize(merged)

    st.divider()
    st.subheader("Ozet")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Toplam gelir", f"${summary['toplam_gelir']:,.2f}")
    m2.metric("Kargo gideri", f"${summary['toplam_gider_kargo']:,.2f}")
    m3.metric("Vergi/gumruk gideri", f"${summary['toplam_gider_tax']:,.2f}")
    m4.metric("Toplam gider", f"${summary['toplam_gider_eslesen']:,.2f}")
    m5.metric("Toplam kar", f"${summary['toplam_kar']:,.2f}")

    eslesme_orani = summary["eslesen_sayisi"] / summary["toplam_gonderi"] * 100 if summary["toplam_gonderi"] else 0
    st.caption(f"Eslesme orani: %{eslesme_orani:.1f}")

    st.caption(
        f"Toplam {summary['toplam_gonderi']} gonderi  |  "
        f"{summary['eslesen_sayisi']} eslesti  |  "
        f"{summary['gider_bulunamadi_sayisi']} gider bulunamadi  |  "
        f"{summary['takip_no_yok_sayisi']} takip no yok"
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

    st.download_button(
        "Raporu Excel olarak indir",
        data=buffer.getvalue(),
        file_name="gelir_gider_raporu.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

elif not income_file:
    st.info("Baslamak icin once gelir dosyasini yukleyin.")
