# Depo Gelir-Gider Karsilastirma Araci

Musteri faturasi (gelir) ile kargo firmasi faturasi (gider) dosyalarini
yukleyip paket/takip numarasina gore otomatik kar-zarar raporu cikaran
basit bir web araci.

## Nasil calistirilir

```bash
pip install -r requirements.txt
streamlit run app.py
```

Tarayicida otomatik acilir (genelde `http://localhost:8501`).

## Nasil kullanilir

1. Sol tarafa gelir dosyasini (WH_CUSTOMER_SHIPMENT_LIST formatinda) yukleyin.
2. Sag tarafa kargo firmasi fatura dosyasini/dosyalarini yukleyin, her biri
   icin kargo firmasini secin.
3. "Hesapla" butonuna basin.
4. Ozet karti, detayli tablo ve Excel indirme secenegi gorunecek.

## Eslestirme mantigi

- Gelir dosyasindaki `Track Number` kolonu ile gider dosyasindaki takip
  numarasi kolonu karsilastirilir.
- Ayni takip numarasi gider dosyasinda birden fazla satirda geciyorsa,
  tum tutarlar toplanir (hicbir satir atilmaz).
- "Takip no yok" -> gelir kaydinda gercek bir takip numarasi yok
  (orn. "No Tracking Number", "Customer Label").
- "Gider bulunamadi" -> takip numarasi var ama yuklenen gider
  dosyalarinda karsiligi yok (henuz faturalanmamis olabilir).
- "Eslesti" -> hem gelir hem gider bulundu, kar/zarar hesaplandi.

## Yeni kargo firmasi eklemek

`processing.py` icindeki `CARRIER_PROFILES` sozlugune yeni bir girdi
eklemek yeterli:

```python
CARRIER_PROFILES = {
    "Asendia": {
        "tracking_col": "CustomerTrackingNumberOriginal",
        "charge_col": "TOTALCHARGE",
        "currency_col": "CurrencyType",
        "date_col": "JobDate",
        "invoice_col": "Invoice Number",
    },
    "UniUni": {
        "tracking_col": "...",   # UniUni dosyasindaki takip numarasi kolonu
        "charge_col": "...",     # UniUni dosyasindaki ucret kolonu
    },
}
```

Kolon adlarini ilgili firmanin ornek dosyasina bakarak doldurmak yeterli;
arayuzde otomatik secenek olarak cikar.

## Su anki kapsam

- Sadece Asendia kargo firmasi destekleniyor.
- Diger kargo firmalari (UniUni, UPS, DHL, FedEx, ePost Global vb.)
  eklenecek - her biri icin ornek bir fatura dosyasi yeterli.
- Para birimi kontrolu: gider dosyasinda USD disinda bir para birimi
  bulunursa uyari gosterilir (henuz otomatik cevrim yapilmiyor).

## Canli web sitesine cevirmek icin

Bu su an yerel bilgisayarda calisan bir araç. Eger surekli erisilebilir
bir web sitesi haline getirmek istersen iki kolay yol var:

- **Streamlit Community Cloud** (ucretsiz, basit): kodu bir GitHub
  reposuna atip share.streamlit.io uzerinden baglarsin.
- **Sirket VPS'i** (EAP projesindeki gibi): Docker container icine alip
  Nginx arkasinda calistirabilirsin.

Hangisini istersen, kurulumunu birlikte yapabiliriz.
