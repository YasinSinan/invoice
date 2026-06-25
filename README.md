# Depo Gelir-Gider Karsilastirma Araci

Musteri faturasi (gelir) ile kargo firmasi faturasi (gider) dosyalarini
yukleyip paket/takip numarasina gore otomatik kar-zarar raporu cikaran bir
web araci. Firma, ulke ve musteri bazinda analiz, manuel gelir/gider girisi
ve gecmis analizleri GitHub'da saklama ozelliklerini icerir.

**Canli adres:** https://comfyship-gelir-gider.streamlit.app/

## Nasil calistirilir

```bash
pip install -r requirements.txt
streamlit run app.py
```

Tarayicida otomatik acilir (genelde `http://localhost:8501`).

## Nasil kullanilir

1. Sol tarafa gelir dosyasini (`WH_CUSTOMER_SHIPMENT_LIST` formatinda) yukleyin.
   - "Sadece odenmis gonderileri dahil et (Status = Paid)" ve "Kargo firmasi
     atanmamis gonderileri haric tut" kutucuklarini isteginize gore
     isaretleyin/kaldirin (varsayilan: ikisi de isaretli).
   - Isterseniz pakete baglanmayan manuel gelir kalemleri (orn. depo kirasi
     geliri) ekleyebilirsiniz.
2. Sag tarafa kargo firmasi fatura dosyasini/dosyalarini yukleyin, her biri
   icin kargo firmasini secin (bkz. "Desteklenen kargo firmalari").
   - Isterseniz pakete baglanmayan manuel gider kalemleri ve firma bazinda
     paket-basi ek gider (orn. "UniUni icin paket basina $2") ekleyebilirsiniz.
3. "Hesapla" butonuna basin.
4. Asagidaki bolumler gorunur:
   - Ozet (toplam paket sayisi, gelir/gider, net kar)
   - Kargo firmalarina gore analiz (paket sayisi, gelir, kargo/vergi gideri,
     kar/zarar, paket basi kar/zarar, ve hangi kategori/sutunun kargo/vergi
     sayildigini gosteren detay tablosu)
   - Ulkeye gore analiz
   - Musteriye gore analiz + Musteri x Ulke kar/zarar analizi
   - Detayli rapor / Gider bulunamayanlar / Eslesmeyen gider sekmeleri
   - Excel olarak indirme secenegi
   - Bu analizi GitHub'a kaydetme secenegi (asagida detayi var)

## Eslestirme mantigi

- Gelir dosyasindaki `Track Number` kolonu ile gider dosyasindaki takip
  numarasi kolonu karsilastirilir.
- Ayni takip numarasi gider dosyasinda birden fazla satirda geciyorsa, tum
  tutarlar toplanir (hicbir satir atilmaz).
- Gider tutari mumkun oldugunda **Kargo** ve **Vergi/Gumruk** olarak ikiye
  ayrilir (firmaya gore: ayri kolon, kategori sutunu, veya cok-kolonlu ucret
  kalemleri uzerinden).
- Takip numarasi olmayan vergi/komisyon satirlari (orn. UPS Brokerage/
  Government Charges) belirli bir pakete baglanamadigi icin **genel gider**
  olarak ayri tutulur, pakete dagitilmaz - net kardan ayrica dusulur.
- Para birimi USD disindaysa (orn. UniUni'nin CAD faturasi), her satir kendi
  islem tarihindeki gunluk kur ile otomatik USD'ye cevrilir (Frankfurter API,
  ucretsiz, API key gerektirmez).
- Durum aciklamalari:
  - **"Takip no yok"** -> gelir kaydinda gercek bir takip numarasi yok
    (orn. "No Tracking Number", "Customer Label").
  - **"Gider bulunamadi"** -> takip numarasi var ama yuklenen gider
    dosyalarinda karsiligi yok (henuz faturalanmamis olabilir).
  - **"Eslesti"** -> hem gelir hem gider bulundu, kar/zarar hesaplandi.

## Ayni firmanin farkli yazimlarini birlestirme

Gelir dosyasinda ve gider dosyalarinda ayni firma farkli isimlerle gecebilir
(orn. "FedEx" / "FedEx BL" / "FEDEX BL", veya "UPS" / "UPS 2"). `processing.py`
icindeki `CARRIER_NAME_ALIASES` sozlugu bunlari tek bir isim altinda
birlestirir - bosluk/alt cizgi/tire/buyuk-kucuk harf farkliliklarindan
bagimsiz calisir:

```python
CARRIER_NAME_ALIASES = {
    "asendia": "Asendia",
    "epost": "ePost Global",
    "fedex": "FedEx",
    "intelcom": "Intelcom",
    "purolator": "Purolator",
    "ups": "UPS",
}
```

Yeni bir birlestirme istenirse bu sozluge bir satir eklemek yeterlidir.

## Desteklenen kargo firmalari

Yukleme ekraninda dogrudan secilebilenler:

- **Asendia** - kendi kargo fatura dosyasi (eski/yeni kolon adlandirma
  formatlarinin ikisini de otomatik tanir)
- **Asendia - Vergi/Gumruk** - Asendia'nin ayri Duty & Tax raporu (sadece
  "2026" sayfasi islenir, tum tutar Vergi sayilir)
- **UniUni** - kendi kargo fatura dosyasi (CAD -> USD otomatik cevrim)
- **UPS** - UPS Billing Centre raporu (Brokerage/Government/Customs Duty
  satirlari otomatik Vergi/Genel Gider sayilir)
- **FedEx** - FedEx'in detayli fatura raporu (her gonderi tek satir, 51 ayri
  ucret kalemi otomatik Kargo/Vergi olarak siniflandirilir)
- **ByeLabel (Tum Firmalar)** - tek bir "shipments-...xlsx" dosyasi
  yuklendiginde, icindeki tum firmalar (ePost Global, DHL, intelcom, APC,
  USPS, Evri, Purolator, FedEx, UPS) otomatik ayri ayri islenir; tek tek
  secmeye gerek yoktur

## Manuel girisler

Hesaplama ekraninda, dosyalarda olmayan ama bilinen tutarlari elle eklemek
icin uc ayri alan vardir:

1. **Manuel gelir** - aciklama + tutar (pakete baglanmaz, net kara eklenir)
2. **Manuel gider** - aciklama + tutar (pakete baglanmaz, net kardan dusulur)
3. **Paket basina ek gider (firma bazinda)** - bir kargo firmasi secip
   paket-basi bir tutar girilir (orn. UniUni icin $2); bu tutar o firmanin
   takip edilebilir HER paketine tek tek islenir, paket sayisiyla otomatik
   carpilir ve tum tablolara (ulke, firma, musteri) yansir. Daha once gideri
   eslesmemis paketler bu tutari aldiktan sonra "Eslesti" sayilir.

## Yeni kargo firmasi eklemek

`processing.py` icindeki `CARRIER_PROFILES` sozlugune yeni bir girdi eklemek
yeterli. En basit profil (tek takip numarasi kolonu + tek ucret kolonu):

```python
CARRIER_PROFILES = {
    "YeniFirma": {
        "tracking_col": "...",   # dosyadaki takip numarasi kolonu
        "charge_col": "...",     # dosyadaki ucret kolonu
        "date_col": "...",       # opsiyonel, para birimi cevrimi icin
        "currency_col": "...",   # opsiyonel, USD disindaysa
        "invoice_col": "...",    # opsiyonel, sadece dokumantasyon
    },
}
```

Daha karmasik formatlar icin (kategori bazli vergi ayrimi, cok-kolonlu ucret
kalemleri, tek dosyada birden fazla firma) mevcut profillere (`UPS`, `FedEx`,
`_BYELABEL_BASE`) bakarak orneklendirebilirsiniz. Kolon adlarini ilgili
firmanin ornek dosyasina bakarak doldurmak yeterli; arayuzde otomatik secenek
olarak cikar.

## Gecmis analizleri kaydetme (GitHub uzerinden)

Hesaplama sonuclarinin altinda bir donem etiketi (orn. "2026-06") yazip
"GitHub'a kaydet" diyerek o ayin ozetini ve tablolarini GitHub reposundaki
`reports/` klasorune JSON olarak kaydedebilirsiniz. Sayfanin en ustundeki
"Gecmis analizler" bolumunden daha sonra tekrar goruntuleyebilir veya
silebilirsiniz.

**Kurulum (bir kerelik):**

1. [github.com/settings/tokens](https://github.com/settings/tokens) ->
   **Generate new token (classic)** -> sadece `repo` yetkisini isaretleyin.
2. Yerelde test icin: proje klasorunde `.streamlit/secrets.toml` dosyasi
   olusturup icine yazin:
   ```
   GITHUB_TOKEN = "ghp_..."
   ```
   (Bu dosya `.gitignore`'da oldugu icin GitHub'a hic yuklenmez.)
3. Canli (Streamlit Cloud) uygulama icin: uygulama ayarlarindan
   **Settings -> Secrets** kismina aynı satiri ekleyin.

Token olmadan da uygulama calisir; sadece "Gecmis analizler" bolumu "henuz
kurulmadi" mesaji gosterir.

`github_storage.py` icindeki `GITHUB_OWNER` / `GITHUB_REPO` degerlerini
kendi repo bilgilerinize gore guncelleyebilirsiniz.

## Para birimi cevrimi

Gider dosyasinda USD disinda bir para birimi varsa (orn. UniUni'nin CAD
faturasi), her satir kendi islem tarihindeki gunluk kur ile otomatik USD'ye
cevrilir (`fx.py`, Frankfurter API - ucretsiz, API key gerektirmez, ayni
(kur, tarih) cifti icin tekrar API cagrisi yapilmaz).

## Dosya yapisi

```
app.py              Streamlit arayuzu
processing.py        Eslestirme, hesaplama ve analiz mantigi
fx.py                 Doviz kuru cevirme
github_storage.py     Gecmis analizleri GitHub'a kaydetme/okuma
requirements.txt      Python bagimliliklari
```

## Canli web sitesi (zaten kurulu)

Uygulama Streamlit Community Cloud uzerinde calisiyor:
https://comfyship-gelir-gider.streamlit.app/

Kod GitHub'a `git push` edildiginde Streamlit Cloud otomatik olarak yeniden
deploy eder, elle bir islem gerekmez.
