import hmac
import os
import random
from functools import wraps
from urllib.parse import urlparse
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, request, redirect, url_for, session, flash, jsonify, get_flashed_messages
from jinja2 import Environment, FileSystemLoader, select_autoescape
from werkzeug.security import generate_password_hash, check_password_hash

duzgunler_bp = Blueprint(
    "duzgunler",
    __name__,
    url_prefix="/duzgunler",
    template_folder="templates",
    static_folder="static",
    static_url_path="/duzgunler/static"
)

DZG_ADMIN_USER = os.environ.get("DZG_ADMIN_USER", "").strip()
DZG_ADMIN_PASS = os.environ.get("DZG_ADMIN_PASS", "").strip()
DZG_ADMIN_ENABLED = bool(DZG_ADMIN_USER and DZG_ADMIN_PASS)

_DZG_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
_dzg_env = Environment(
    loader=FileSystemLoader(_DZG_TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)
_dzg_env.globals.update({
    "url_for": url_for,
    "session": session,
    "request": request,
    "get_flashed_messages": get_flashed_messages,
})


def dzg_render(template_name, **context):
    context.setdefault("get_flashed_messages", get_flashed_messages)
    tmpl = _dzg_env.get_template(template_name)
    return tmpl.render(**context)


def _normalize_db_url(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


DATABASE_URL = _normalize_db_url(
    os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres.wpthfxzdhwinkamyrpyo:KOLAYV%C4%B0TR%C4%B0NSAAS@aws-1-eu-west-1.pooler.supabase.com:6543/postgres"
    )
)


def get_db_connection():
    host = urlparse(DATABASE_URL).hostname or ""
    sslmode = "require" if ("supabase" in host or "pooler" in host) else "prefer"
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        sslmode=sslmode,
        connect_timeout=10,
    )


def hesapla_cari_ozet(siparisler, odemeler):
    toplam_siparis = sum(
        float(s["toplam_tutar"] or 0)
        for s in siparisler
        if (s.get("durum") or "") != "İptal"
    )
    onaylanan_odeme = sum(
        float(o["tutar"] or 0)
        for o in odemeler
        if (o.get("durum") or "") == "Onaylandı"
    )
    bekleyen_odeme = sum(
        float(o["tutar"] or 0)
        for o in odemeler
        if (o.get("durum") or "") == "Onay Bekliyor"
    )
    net_bakiye = toplam_siparis - onaylanan_odeme

    hareketler = []
    for s in siparisler:
        if (s.get("durum") or "") != "İptal":
            hareketler.append({
                "tarih": s.get("olusturma_tarihi"),
                "tur": "Sipariş",
                "aciklama": f"Sipariş No: {s.get('siparis_no')} ({s.get('durum')})",
                "borc": float(s["toplam_tutar"] or 0),
                "alacak": 0.0,
            })

    for o in odemeler:
        if (o.get("durum") or "") == "Onaylandı":
            hareketler.append({
                "tarih": o.get("olusturma_tarihi"),
                "tur": "Ödeme (Onaylı)",
                "aciklama": f"{o.get('odeme_yontemi')} - {o.get('aciklama') or 'Onaylanan Ödeme'}",
                "borc": 0.0,
                "alacak": float(o["tutar"] or 0),
            })

    hareketler.sort(key=lambda x: str(x["tarih"] or ""))
    kosu = 0.0
    for h in hareketler:
        kosu += (h["borc"] - h["alacak"])
        h["bakiye"] = kosu
    hareketler.reverse()

    return {
        "toplam_siparis": toplam_siparis,
        "toplam_odenen": onaylanan_odeme,
        "bekleyen_odeme": bekleyen_odeme,
        "acik_bakiye": net_bakiye,
        "ekstre_hareketleri": hareketler,
    }


def init_db():
    """Supabase PostgreSQL üzerinde Düzgünler Elektrik B2B tablolarını ve varsayılan verileri oluşturur."""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS b2b_bayiler (
                id SERIAL PRIMARY KEY,
                firma_unvani VARCHAR(255) NOT NULL,
                yetkili_ad_soyad VARCHAR(150) NOT NULL,
                vergi_dairesi VARCHAR(120) NOT NULL,
                vergi_no VARCHAR(50) UNIQUE NOT NULL,
                telefon VARCHAR(30) NOT NULL,
                email VARCHAR(150) UNIQUE NOT NULL,
                sehir VARCHAR(80) NOT NULL,
                adres TEXT,
                sifre_hash TEXT NOT NULL,
                iskonto_orani NUMERIC(5,2) DEFAULT 15.00,
                durum VARCHAR(30) DEFAULT 'aktif',
                olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS b2b_plasiyerler (
                id SERIAL PRIMARY KEY,
                plasiyer_kodu VARCHAR(50) UNIQUE NOT NULL,
                ad_soyad VARCHAR(150) NOT NULL,
                bolge VARCHAR(100) NOT NULL,
                telefon VARCHAR(30),
                email VARCHAR(150) UNIQUE NOT NULL,
                sifre_hash TEXT NOT NULL,
                aktif BOOLEAN DEFAULT TRUE,
                olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS b2b_urunler (
                id SERIAL PRIMARY KEY,
                stok_kodu VARCHAR(60) UNIQUE NOT NULL,
                urun_adi VARCHAR(255) NOT NULL,
                kategori VARCHAR(100) NOT NULL,
                seri VARCHAR(100),
                liste_fiyati NUMERIC(10,2) NOT NULL,
                stok_adedi INTEGER DEFAULT 100,
                birim VARCHAR(20) DEFAULT 'Adet',
                gorsel_ikon VARCHAR(50) DEFAULT 'bolt',
                aciklama TEXT
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS b2b_siparisler (
                id SERIAL PRIMARY KEY,
                siparis_no VARCHAR(50) UNIQUE NOT NULL,
                bayi_id INTEGER REFERENCES b2b_bayiler(id) ON DELETE CASCADE,
                plasiyer_id INTEGER REFERENCES b2b_plasiyerler(id) ON DELETE SET NULL,
                toplam_tutar NUMERIC(12,2) NOT NULL,
                durum VARCHAR(50) DEFAULT 'Onay Bekliyor',
                notlar TEXT,
                olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS b2b_odemeler (
                id SERIAL PRIMARY KEY,
                bayi_id INTEGER REFERENCES b2b_bayiler(id) ON DELETE CASCADE,
                tutar NUMERIC(12,2) NOT NULL,
                odeme_yontemi VARCHAR(80) NOT NULL,
                aciklama TEXT,
                durum VARCHAR(40) DEFAULT 'Onay Bekliyor',
                olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS b2b_odeme_yontemleri (
                id SERIAL PRIMARY KEY,
                kod VARCHAR(50) UNIQUE NOT NULL,
                baslik VARCHAR(150) NOT NULL,
                aciklama TEXT,
                iban_veya_detay TEXT,
                aktif BOOLEAN DEFAULT TRUE,
                sira_no INTEGER DEFAULT 1
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS b2b_icerikler (
                id SERIAL PRIMARY KEY,
                bolum VARCHAR(50) NOT NULL,
                slug VARCHAR(120) UNIQUE NOT NULL,
                baslik VARCHAR(200) NOT NULL,
                icerik TEXT,
                guncelleme_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS b2b_iletisim_formlari (
                id SERIAL PRIMARY KEY,
                form_turu VARCHAR(80) DEFAULT 'İletişim Formu',
                ad_soyad VARCHAR(150) NOT NULL,
                firma VARCHAR(200),
                telefon VARCHAR(40),
                email VARCHAR(150),
                mesaj TEXT NOT NULL,
                durum VARCHAR(30) DEFAULT 'yeni',
                olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS b2b_yoneticiler (
                id SERIAL PRIMARY KEY,
                kullanici_adi VARCHAR(100) UNIQUE NOT NULL,
                ad_soyad VARCHAR(150) NOT NULL,
                rol VARCHAR(40) DEFAULT 'admin',
                sifre_hash TEXT NOT NULL,
                aktif BOOLEAN DEFAULT TRUE,
                olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("SELECT id FROM b2b_plasiyerler WHERE plasiyer_kodu = %s", ("PLS-001",))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO b2b_plasiyerler (plasiyer_kodu, ad_soyad, bolge, telefon, email, sifre_hash)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                "PLS-001",
                "Ahmet Düzgün (Bölge Müdürü)",
                "Marmara & İstanbul Anadolu",
                "0532 000 00 01",
                "plasiyer@duzgunlerelektrik.com",
                generate_password_hash("123456")
            ))

        cur.execute("SELECT id FROM b2b_bayiler WHERE vergi_no = %s", ("1234567890",))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO b2b_bayiler (firma_unvani, yetkili_ad_soyad, vergi_dairesi, vergi_no, telefon, email, sehir, adres, sifre_hash, iskonto_orani, durum)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                "Örnek Aydınlatma & Elektrik Ltd. Şti.",
                "Mehmet Yılmaz",
                "Çekmeköy VD",
                "1234567890",
                "0216 555 44 33",
                "bayi@ornek.com",
                "İstanbul",
                "Alemdağ Cad. No:142 Çekmeköy / İstanbul",
                generate_password_hash("123456"),
                22.50,
                "aktif"
            ))

        cur.execute("SELECT COUNT(*) AS cnt FROM b2b_urunler")
        if cur.fetchone()["cnt"] == 0:
            sample_products = [
                ("DZG-ANA-101", "Viko Karre Beyaz Topraklı Priz", "Anahtar & Priz", "Karre Serisi", 84.50, 1250, "Adet", "plug", "Çocuk korumalı, sıva altı modüler topraklı priz."),
                ("DZG-LED-204", "Düzgünler 36W Sıva Üstü LED Panel (6500K)", "LED Aydınlatma", "ProLine LED", 345.00, 480, "Adet", "lightbulb", "Yüksek lümen verimliliği, alüminyum kasa, 2 yıl garantili."),
                ("DZG-SIG-309", "Siemens 1x16A B Tipi Otomatik Sigorta", "Şalt & Pano", "Sentron", 168.00, 820, "Adet", "shield-halved", "6kA kesme kapasiteli, DIN ray montajına uygun."),
                ("DZG-KAB-412", "Öznur 3x2.5 NYM Antigron Kablo (100m Top)", "Kablo Grupları", "TSE Belgeli", 3890.00, 145, "Top", "bolt", "Tam bakır iletken, PVC izolasyonlu tesisat kablosu."),
                ("DZG-END-505", "3x32A IP67 Kauçuk Makine Fişi (Eğik)", "Endüstriyel Ürünler", "HeavyDuty", 295.00, 310, "Adet", "industry", "Suya ve toza tam dayanıklı ağır hizmet tipi sanayi fişi."),
                ("DZG-DIA-602", "Audio 7 İnç Renkli Görüntülü Diafon Seti", "Zayıf Akım & Diafon", "SmartHome", 4650.00, 95, "Set", "video", "Handsfree konuşma, kapı otomatiği kontrolü ve şık cam panel.")
            ]
            cur.executemany("""
                INSERT INTO b2b_urunler (stok_kodu, urun_adi, kategori, seri, liste_fiyati, stok_adedi, birim, gorsel_ikon, aciklama)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, sample_products)

        default_payments = [
            ("HAVALE_EFT", "Havale / EFT", "Banka transferi ile sipariş onayı.", "TR00 0000 0000 0000 0000 0000 00 — Düzgünler Elektrik", True, 1),
            ("CARI_VADE", "Vadeli Cari / B2B Mutabakat", "Anlaşmalı bayilere tanımlı vade ve iskonto üzerinden.", "Onaylı bayilik hesabına işlenir.", True, 2),
            ("KAPIDA_ODEME", "Kapıda Ödeme", "Seçili bölge ve tutarlarda teslimatta ödeme.", "Teslimat bölgesine göre aktif edilir.", False, 3),
        ]
        for kod, baslik, aciklama, detay, aktif, sira in default_payments:
            cur.execute("""
                INSERT INTO b2b_odeme_yontemleri (kod, baslik, aciklama, iban_veya_detay, aktif, sira_no)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (kod) DO NOTHING
            """, (kod, baslik, aciklama, detay, aktif, sira))

        default_contents = [
            ("hakkimizda", "hakkimizda", "Hakkımızda", "Düzgünler Elektrik; anahtar-priz, LED aydınlatma, şalt-pano, kablo grupları ve endüstriyel elektrik ürünlerinde bayi ve saha satış ağına hizmet verir."),
            ("iletisim", "iletisim-bilgileri", "İletişim Bilgileri", "Merkez: İstanbul | E-posta: info@duzgunlerelektrik.com | Telefon: 0216 000 00 00"),
            ("sayfa", "bayilik-kosullari", "Bayilik Koşulları Sayfası", "Yetkili bayilerimize özel iskonto tanımları, stok önceliği ve plasiyer destek hattı sunulmaktadır."),
            ("sayfa", "sss", "Sıkça Sorulan Sorular", "Bayilik başvurusu onaylandıktan sonra B2B panelden iskonto oranınızla sipariş oluşturabilirsiniz."),
            ("sozlesme", "bayilik-sozlesmesi", "B2B Bayilik Sözleşmesi", "İşbu sözleşme, Düzgünler Elektrik ile yetkili bayi arasındaki ticari şartları, ödeme vadelerini ve teslimat esaslarını düzenler."),
            ("sozlesme", "kvkk-aydinlatma", "KVKK Aydınlatma Metni", "6698 sayılı Kişisel Verilerin Korunması Kanunu kapsamında bayi ve iletişim verileri yalnızca hizmet süreçleri için işlenir."),
        ]
        for bolum, slug, baslik, icerik in default_contents:
            cur.execute("""
                INSERT INTO b2b_icerikler (bolum, slug, baslik, icerik)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (slug) DO NOTHING
            """, (bolum, slug, baslik, icerik))

        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        print("Düzgünler DB başlatma hatası:", e)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "dzg_user_id" not in session:
                flash("Bu alanı görüntülemek için giriş yapmalısınız.", "warning")
                return redirect(url_for("duzgunler.index"))
            if role and session.get("dzg_role") != role:
                flash("Bu panele erişim yetkiniz bulunmamaktadır.", "danger")
                return redirect(url_for("duzgunler.index"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def dzg_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("dzg_admin_auth"):
            return redirect(url_for("duzgunler.admin_login"))
        return f(*args, **kwargs)
    return decorated


def _admin_redirect(sekme="gosterge"):
    return redirect(url_for("duzgunler.admin_panel", sekme=sekme))


@duzgunler_bp.route("/")
def index():
    urunler = []
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM b2b_urunler ORDER BY id ASC LIMIT 6")
        urunler = cur.fetchall()
    except Exception as e:
        print("Ürün çekme hatası:", e)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return dzg_render("index.html", urunler=urunler)


@duzgunler_bp.route("/b2b-giris", methods=["POST"])
def b2b_giris():
    email_or_vkn = request.form.get("kullanici", "").strip()
    sifre = request.form.get("sifre", "")

    if not email_or_vkn or not sifre:
        flash("Lütfen E-posta / Vergi No ve şifrenizi giriniz.", "danger")
        return redirect(url_for("duzgunler.index", modal="b2b-login"))

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM b2b_bayiler WHERE email = %s OR vergi_no = %s",
            (email_or_vkn, email_or_vkn)
        )
        bayi = cur.fetchone()

        if bayi and check_password_hash(bayi["sifre_hash"], sifre):
            if bayi["durum"] != "aktif":
                flash("Bayilik başvurunuz henüz onay aşamasındadır.", "warning")
                return redirect(url_for("duzgunler.index"))

            session["dzg_user_id"] = bayi["id"]
            session["dzg_role"] = "bayi"
            session["dzg_firma_unvani"] = bayi["firma_unvani"]
            session["dzg_yetkili"] = bayi["yetkili_ad_soyad"]
            session["dzg_iskonto"] = float(bayi["iskonto_orani"])
            flash(f"Hoş geldiniz, {bayi['firma_unvani']}!", "success")
            return redirect(url_for("duzgunler.b2b_panel"))
        else:
            flash("Hatalı E-posta/Vergi No veya şifre girdiniz.", "danger")
            return redirect(url_for("duzgunler.index", modal="b2b-login"))
    except Exception as e:
        flash(f"Veritabanı bağlantı hatası: {str(e)}", "danger")
        return redirect(url_for("duzgunler.index"))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@duzgunler_bp.route("/plasiyer-giris", methods=["POST"])
def plasiyer_giris():
    kod_or_email = request.form.get("plasiyer_kodu", "").strip()
    sifre = request.form.get("sifre", "")

    if not kod_or_email or not sifre:
        flash("Lütfen Plasiyer Kodu / E-posta ve şifrenizi giriniz.", "danger")
        return redirect(url_for("duzgunler.index", modal="plasiyer-login"))

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM b2b_plasiyerler WHERE plasiyer_kodu = %s OR email = %s",
            (kod_or_email.upper(), kod_or_email)
        )
        plasiyer = cur.fetchone()

        if plasiyer and check_password_hash(plasiyer["sifre_hash"], sifre):
            if not plasiyer["aktif"]:
                flash("Plasiyer hesabınız pasif durumdadır.", "danger")
                return redirect(url_for("duzgunler.index"))

            session["dzg_user_id"] = plasiyer["id"]
            session["dzg_role"] = "plasiyer"
            session["dzg_ad_soyad"] = plasiyer["ad_soyad"]
            session["dzg_plasiyer_kodu"] = plasiyer["plasiyer_kodu"]
            session["dzg_bolge"] = plasiyer["bolge"]
            flash(f"Saha Satış Paneline Hoş Geldiniz, {plasiyer['ad_soyad']}.", "success")
            return redirect(url_for("duzgunler.plasiyer_panel"))
        else:
            flash("Geçersiz Plasiyer Kodu veya şifre.", "danger")
            return redirect(url_for("duzgunler.index", modal="plasiyer-login"))
    except Exception as e:
        flash(f"Veritabanı bağlantı hatası: {str(e)}", "danger")
        return redirect(url_for("duzgunler.index"))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@duzgunler_bp.route("/b2b-kayit", methods=["POST"])
def b2b_kayit():
    firma_unvani = request.form.get("firma_unvani", "").strip()
    yetkili_ad_soyad = request.form.get("yetkili_ad_soyad", "").strip()
    vergi_dairesi = request.form.get("vergi_dairesi", "").strip()
    vergi_no = request.form.get("vergi_no", "").strip()
    telefon = request.form.get("telefon", "").strip()
    email = request.form.get("email", "").strip().lower()
    sehir = request.form.get("sehir", "").strip()
    adres = request.form.get("adres", "").strip()
    sifre = request.form.get("sifre", "")

    if not all([firma_unvani, yetkili_ad_soyad, vergi_dairesi, vergi_no, telefon, email, sehir, sifre]):
        flash("Lütfen tüm zorunlu bayilik başvuru alanlarını doldurunuz.", "danger")
        return redirect(url_for("duzgunler.index", modal="b2b-register"))

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT id FROM b2b_bayiler WHERE email = %s OR vergi_no = %s", (email, vergi_no))
        if cur.fetchone():
            flash("Bu E-posta veya Vergi Numarası ile daha önce kayıt oluşturulmuş.", "warning")
            return redirect(url_for("duzgunler.index", modal="b2b-login"))

        sifre_hash = generate_password_hash(sifre)
        cur.execute("""
            INSERT INTO b2b_bayiler
            (firma_unvani, yetkili_ad_soyad, vergi_dairesi, vergi_no, telefon, email, sehir, adres, sifre_hash, iskonto_orani, durum)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (firma_unvani, yetkili_ad_soyad, vergi_dairesi, vergi_no, telefon, email, sehir, adres, sifre_hash, 15.00, "aktif"))

        new_id = cur.fetchone()["id"]
        conn.commit()

        session["dzg_user_id"] = new_id
        session["dzg_role"] = "bayi"
        session["dzg_firma_unvani"] = firma_unvani
        session["dzg_yetkili"] = yetkili_ad_soyad
        session["dzg_iskonto"] = 15.00

        flash("B2B Bayilik kaydınız Supabase veritabanına başarıyla işlendi!", "success")
        return redirect(url_for("duzgunler.b2b_panel"))
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Kayıt sırasında hata oluştu: {str(e)}", "danger")
        return redirect(url_for("duzgunler.index", modal="b2b-register"))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@duzgunler_bp.route("/b2b-panel")
@login_required(role="bayi")
def b2b_panel():
    sekme = request.args.get("sekme", "ozet").strip()
    bayi_id = session["dzg_user_id"]

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM b2b_bayiler WHERE id = %s", (bayi_id,))
    bayi = cur.fetchone() or {}

    cur.execute("SELECT * FROM b2b_urunler ORDER BY kategori, id ASC")
    urunler = cur.fetchall()

    cur.execute("SELECT * FROM b2b_siparisler WHERE bayi_id = %s ORDER BY olusturma_tarihi DESC", (bayi_id,))
    siparisler = cur.fetchall()

    cur.execute("SELECT * FROM b2b_odemeler WHERE bayi_id = %s ORDER BY olusturma_tarihi DESC", (bayi_id,))
    odemeler = cur.fetchall()

    cur.execute("SELECT * FROM b2b_odeme_yontemleri WHERE aktif = TRUE ORDER BY sira_no ASC, id ASC")
    odeme_yontemleri = cur.fetchall()

    cur.close()
    conn.close()

    cari = hesapla_cari_ozet(siparisler, odemeler)

    return dzg_render(
        "b2b_panel.html",
        sekme=sekme,
        bayi=bayi,
        urunler=urunler,
        siparisler=siparisler,
        odemeler=odemeler,
        odeme_yontemleri=odeme_yontemleri,
        ekstre_hareketleri=cari["ekstre_hareketleri"],
        toplam_siparis=cari["toplam_siparis"],
        toplam_odenen=cari["toplam_odenen"],
        bekleyen_odeme=cari["bekleyen_odeme"],
        acik_bakiye=cari["acik_bakiye"],
    )


@duzgunler_bp.route("/b2b-panel/odeme-yap", methods=["POST"])
@login_required(role="bayi")
def b2b_odeme_yap():
    tutar_raw = request.form.get("tutar", "0").strip().replace(",", ".")
    odeme_yontemi = request.form.get("odeme_yontemi", "Havale / EFT").strip()
    aciklama = request.form.get("aciklama", "").strip()

    try:
        tutar = float(tutar_raw)
    except ValueError:
        tutar = 0.0

    if tutar <= 0:
        flash("Lütfen geçerli bir ödeme tutarı giriniz.", "danger")
        return redirect(url_for("duzgunler.b2b_panel", sekme="odeme-yap"))

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO b2b_odemeler (bayi_id, tutar, odeme_yontemi, aciklama, durum)
            VALUES (%s, %s, %s, %s, 'Onay Bekliyor')
        """, (session["dzg_user_id"], tutar, odeme_yontemi, aciklama))
        conn.commit()
        flash(f"{tutar:.2f} ₺ tutarındaki ödeme bildiriminiz kaydedildi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Ödeme kaydı sırasında hata oluştu: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    return redirect(url_for("duzgunler.b2b_panel", sekme="gecmis-odemelerim"))


@duzgunler_bp.route("/plasiyer-panel")
@login_required(role="plasiyer")
def plasiyer_panel():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM b2b_bayiler ORDER BY olusturma_tarihi DESC")
    bayiler = cur.fetchall()
    cur.execute("SELECT * FROM b2b_urunler ORDER BY kategori, id ASC")
    urunler = cur.fetchall()
    cur.execute("""
        SELECT s.*, b.firma_unvani
        FROM b2b_siparisler s
        LEFT JOIN b2b_bayiler b ON s.bayi_id = b.id
        ORDER BY s.olusturma_tarihi DESC
    """)
    siparisler = cur.fetchall()
    cur.close()
    conn.close()
    return dzg_render("plasiyer_panel.html", bayiler=bayiler, urunler=urunler, siparisler=siparisler)


@duzgunler_bp.route("/api/siparis-ver", methods=["POST"])
@login_required()
def siparis_ver():
    data = request.get_json(silent=True) or {}
    toplam_tutar = data.get("toplam_tutar", 0)
    notlar = data.get("notlar", "")
    bayi_id = session["dzg_user_id"] if session.get("dzg_role") == "bayi" else data.get("bayi_id")
    plasiyer_id = session["dzg_user_id"] if session.get("dzg_role") == "plasiyer" else None

    if not bayi_id or float(toplam_tutar) <= 0:
        return jsonify({"ok": False, "mesaj": "Geçerli bir bayi ve sepet tutarı gereklidir."}), 400

    siparis_no = f"DZG-{random.randint(100000, 999999)}"

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO b2b_siparisler (siparis_no, bayi_id, plasiyer_id, toplam_tutar, durum, notlar)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (siparis_no, bayi_id, plasiyer_id, toplam_tutar, "Onaylandı - Hazırlanıyor", notlar))
        conn.commit()
        return jsonify({"ok": True, "siparis_no": siparis_no, "mesaj": f"{siparis_no} numaralı siparişiniz oluşturuldu."})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"ok": False, "mesaj": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@duzgunler_bp.route("/plasiyer/bayi-guncelle/<int:bayi_id>", methods=["POST"])
@login_required(role="plasiyer")
def bayi_guncelle(bayi_id):
    iskonto = request.form.get("iskonto_orani", 15)
    durum = request.form.get("durum", "aktif")
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE b2b_bayiler SET iskonto_orani = %s, durum = %s WHERE id = %s",
            (iskonto, durum, bayi_id)
        )
        conn.commit()
        flash("Bayi iskonto ve hesap durumu güncellendi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Güncelleme hatası: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return redirect(url_for("duzgunler.plasiyer_panel"))


@duzgunler_bp.route("/cikis")
def cikis():
    for k in [
        "dzg_user_id", "dzg_role", "dzg_firma_unvani", "dzg_yetkili",
        "dzg_iskonto", "dzg_ad_soyad", "dzg_plasiyer_kodu", "dzg_bolge"
    ]:
        session.pop(k, None)
    flash("Düzgünler B2B oturumunuz sonlandırıldı.", "info")
    return redirect(url_for("duzgunler.index"))


# ---------------------------------------------------------------------------
# Düzgünler B2B Yönetim (Admin) Paneli — 16 Modüllü Tam Yapı
# ---------------------------------------------------------------------------
@duzgunler_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if session.get("dzg_admin_auth"):
        return redirect(url_for("duzgunler.admin_panel"))

    if request.method == "POST":
        u_raw = request.form.get("username", "").strip()
        p_raw = request.form.get("password", "").strip()

        if DZG_ADMIN_ENABLED:
            ok_u = hmac.compare_digest(u_raw.encode("utf-8"), DZG_ADMIN_USER.encode("utf-8"))
            ok_p = hmac.compare_digest(p_raw.encode("utf-8"), DZG_ADMIN_PASS.encode("utf-8"))
            if ok_u and ok_p:
                session["dzg_admin_auth"] = True
                session["dzg_admin_name"] = u_raw
                return redirect(url_for("duzgunler.admin_panel"))

        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM b2b_yoneticiler WHERE kullanici_adi = %s AND aktif = TRUE", (u_raw,))
            yonetici = cur.fetchone()
            if yonetici and check_password_hash(yonetici["sifre_hash"], p_raw):
                session["dzg_admin_auth"] = True
                session["dzg_admin_name"] = yonetici["ad_soyad"]
                return redirect(url_for("duzgunler.admin_panel"))
        except Exception:
            pass
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

        if not DZG_ADMIN_ENABLED:
            error = "Yönetici girişi kapalı: Render'da DZG_ADMIN_USER ve DZG_ADMIN_PASS tanımlayın veya veritabanına yönetici ekleyin."
        else:
            error = "Yönetici kullanıcı adı veya şifresi hatalı."

    return dzg_render("admin_login.html", error=error)


@duzgunler_bp.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("dzg_admin_auth", None)
    session.pop("dzg_admin_name", None)
    return redirect(url_for("duzgunler.admin_login"))


@duzgunler_bp.route("/admin")
@dzg_admin_required
def admin_panel():
    sekme = request.args.get("sekme", "gosterge").strip()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM b2b_bayiler ORDER BY olusturma_tarihi DESC")
    bayiler = cur.fetchall()

    cur.execute("SELECT * FROM b2b_plasiyerler ORDER BY id DESC")
    plasiyerler = cur.fetchall()

    cur.execute("SELECT * FROM b2b_urunler ORDER BY kategori, id DESC")
    urunler = cur.fetchall()

    cur.execute("""
        SELECT s.*, b.firma_unvani, p.ad_soyad AS plasiyer_adi
        FROM b2b_siparisler s
        LEFT JOIN b2b_bayiler b ON s.bayi_id = b.id
        LEFT JOIN b2b_plasiyerler p ON s.plasiyer_id = p.id
        ORDER BY s.olusturma_tarihi DESC
    """)
    siparisler = cur.fetchall()

    cur.execute("""
        SELECT o.*, b.firma_unvani, b.vergi_no
        FROM b2b_odemeler o
        LEFT JOIN b2b_bayiler b ON o.bayi_id = b.id
        ORDER BY o.olusturma_tarihi DESC
    """)
    bayi_odemeleri = cur.fetchall()

    cur.execute("SELECT * FROM b2b_odeme_yontemleri ORDER BY sira_no ASC, id ASC")
    odeme_yontemleri = cur.fetchall()

    cur.execute("SELECT * FROM b2b_icerikler ORDER BY bolum ASC, id ASC")
    icerikler = cur.fetchall()

    cur.execute("SELECT * FROM b2b_iletisim_formlari ORDER BY olusturma_tarihi DESC")
    formlar = cur.fetchall()

    cur.execute("SELECT id, kullanici_adi, ad_soyad, rol, aktif, olusturma_tarihi FROM b2b_yoneticiler ORDER BY id ASC")
    yoneticiler = cur.fetchall()

    cur.close()
    conn.close()

    toplam_ciro = sum(float(s["toplam_tutar"] or 0) for s in siparisler if s["durum"] != "İptal")
    bekleyen_basvurular = [b for b in bayiler if b["durum"] == "beklemede"]
    yeni_formlar = [f for f in formlar if f["durum"] == "yeni"]

    cari_mutabakat = []
    for b in bayiler:
        b_sip = [s for s in siparisler if s["bayi_id"] == b["id"]]
        b_odm = [o for o in bayi_odemeleri if o["bayi_id"] == b["id"]]
        ozet = hesapla_cari_ozet(b_sip, b_odm)
        cari_mutabakat.append({
            "bayi_id": b["id"],
            "firma_unvani": b["firma_unvani"],
            "vergi_no": b["vergi_no"],
            "toplam_siparis": ozet["toplam_siparis"],
            "onaylanan_odeme": ozet["toplam_odenen"],
            "bekleyen_odeme": ozet["bekleyen_odeme"],
            "net_bakiye": ozet["acik_bakiye"],
        })

    return dzg_render(
        "admin_panel.html",
        sekme=sekme,
        bayiler=bayiler,
        bekleyen_basvurular=bekleyen_basvurular,
        plasiyerler=plasiyerler,
        urunler=urunler,
        siparisler=siparisler,
        bayi_odemeleri=bayi_odemeleri,
        cari_mutabakat=cari_mutabakat,
        odeme_yontemleri=odeme_yontemleri,
        icerikler=icerikler,
        formlar=formlar,
        yeni_formlar=yeni_formlar,
        yoneticiler=yoneticiler,
        toplam_ciro=toplam_ciro,
        env_admin_aktif=DZG_ADMIN_ENABLED,
    )


@duzgunler_bp.route("/admin/bayi-odeme/<int:odeme_id>/durum", methods=["POST"])
@dzg_admin_required
def admin_bayi_odeme_durum(odeme_id):
    durum = request.form.get("durum", "Onaylandı").strip()
    if durum not in ["Onay Bekliyor", "Onaylandı", "İptal"]:
        durum = "Onay Bekliyor"

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE b2b_odemeler SET durum = %s WHERE id = %s", (durum, odeme_id))
        conn.commit()
        flash(f"Bayi ödemesi '{durum}' olarak güncellendi ve cari bakiye yenilendi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Ödeme durumu güncellenemedi: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect("odemeler")


@duzgunler_bp.route("/admin/bayi/<int:bayi_id>/guncelle", methods=["POST"])
@dzg_admin_required
def admin_bayi_guncelle(bayi_id):
    iskonto = request.form.get("iskonto_orani", 15)
    durum = request.form.get("durum", "aktif")
    yeni_sifre = request.form.get("yeni_sifre", "").strip()
    sekme = request.form.get("sekme", "musteriler")
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if len(yeni_sifre) >= 6:
            cur.execute(
                "UPDATE b2b_bayiler SET iskonto_orani = %s, durum = %s, sifre_hash = %s WHERE id = %s",
                (iskonto, durum, generate_password_hash(yeni_sifre), bayi_id),
            )
        else:
            cur.execute(
                "UPDATE b2b_bayiler SET iskonto_orani = %s, durum = %s WHERE id = %s",
                (iskonto, durum, bayi_id),
            )
        conn.commit()
        flash("Bayi bilgileri güncellendi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Bayi güncelleme hatası: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect(sekme)


@duzgunler_bp.route("/admin/bayi/<int:bayi_id>/sil", methods=["POST"])
@dzg_admin_required
def admin_bayi_sil(bayi_id):
    sekme = request.form.get("sekme", "musteriler")
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM b2b_bayiler WHERE id = %s", (bayi_id,))
        conn.commit()
        flash("Bayi kaydı silindi.", "info")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Silme hatası: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect(sekme)


@duzgunler_bp.route("/admin/urun/ekle", methods=["POST"])
@dzg_admin_required
def admin_urun_ekle():
    stok_kodu = request.form.get("stok_kodu", "").strip().upper()
    urun_adi = request.form.get("urun_adi", "").strip()
    kategori = request.form.get("kategori", "Genel").strip()
    seri = request.form.get("seri", "").strip()
    liste_fiyati = request.form.get("liste_fiyati", "0").strip()
    stok_adedi = request.form.get("stok_adedi", "0").strip()
    birim = request.form.get("birim", "Adet").strip()
    gorsel_ikon = request.form.get("gorsel_ikon", "bolt").strip() or "bolt"
    aciklama = request.form.get("aciklama", "").strip()

    if not stok_kodu or not urun_adi:
        flash("Stok kodu ve ürün adı zorunludur.", "danger")
        return _admin_redirect("katalog")

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO b2b_urunler (stok_kodu, urun_adi, kategori, seri, liste_fiyati, stok_adedi, birim, gorsel_ikon, aciklama)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (stok_kodu, urun_adi, kategori, seri, float(liste_fiyati), int(stok_adedi), birim, gorsel_ikon, aciklama))
        conn.commit()
        flash(f"{urun_adi} ({stok_kodu}) kataloğa eklendi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Ürün ekleme hatası: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect("katalog")


@duzgunler_bp.route("/admin/urun/<int:urun_id>/guncelle", methods=["POST"])
@dzg_admin_required
def admin_urun_guncelle(urun_id):
    liste_fiyati = request.form.get("liste_fiyati", "0").strip()
    stok_adedi = request.form.get("stok_adedi", "0").strip()
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE b2b_urunler SET liste_fiyati = %s, stok_adedi = %s WHERE id = %s",
            (float(liste_fiyati), int(stok_adedi), urun_id),
        )
        conn.commit()
        flash("Ürün fiyat ve stok bilgisi güncellendi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Güncelleme hatası: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect("katalog")


@duzgunler_bp.route("/admin/urun/<int:urun_id>/sil", methods=["POST"])
@dzg_admin_required
def admin_urun_sil(urun_id):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM b2b_urunler WHERE id = %s", (urun_id,))
        conn.commit()
        flash("Ürün katalogdan silindi.", "info")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Silme hatası: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect("katalog")


@duzgunler_bp.route("/admin/siparis/<int:siparis_id>/durum", methods=["POST"])
@dzg_admin_required
def admin_siparis_durum(siparis_id):
    durum = request.form.get("durum", "Onaylandı - Hazırlanıyor").strip()
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE b2b_siparisler SET durum = %s WHERE id = %s", (durum, siparis_id))
        conn.commit()
        flash("Sipariş durumu güncellendi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Sipariş güncelleme hatası: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect("siparisler")


@duzgunler_bp.route("/admin/odeme/ekle", methods=["POST"])
@dzg_admin_required
def admin_odeme_ekle():
    kod = request.form.get("kod", "").strip().upper()
    baslik = request.form.get("baslik", "").strip()
    aciklama = request.form.get("aciklama", "").strip()
    detay = request.form.get("iban_veya_detay", "").strip()
    sira_no = int(request.form.get("sira_no", "1") or "1")
    if not kod or not baslik:
        flash("Ödeme kodu ve başlığı zorunludur.", "danger")
        return _admin_redirect("odemeler")
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO b2b_odeme_yontemleri (kod, baslik, aciklama, iban_veya_detay, aktif, sira_no)
            VALUES (%s, %s, %s, %s, TRUE, %s)
        """, (kod, baslik, aciklama, detay, sira_no))
        conn.commit()
        flash("Yeni ödeme yöntemi eklendi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Ödeme yöntemi hatası: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect("odemeler")


@duzgunler_bp.route("/admin/odeme/<int:odeme_id>/guncelle", methods=["POST"])
@dzg_admin_required
def admin_odeme_guncelle(odeme_id):
    baslik = request.form.get("baslik", "").strip()
    aciklama = request.form.get("aciklama", "").strip()
    detay = request.form.get("iban_veya_detay", "").strip()
    aktif = request.form.get("aktif") == "1"
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE b2b_odeme_yontemleri
            SET baslik = %s, aciklama = %s, iban_veya_detay = %s, aktif = %s
            WHERE id = %s
        """, (baslik, aciklama, detay, aktif, odeme_id))
        conn.commit()
        flash("Ödeme yöntemi güncellendi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Güncelleme hatası: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect("odemeler")


@duzgunler_bp.route("/admin/icerik/kaydet", methods=["POST"])
@dzg_admin_required
def admin_icerik_kaydet():
    bolum = request.form.get("bolum", "sayfa").strip()
    slug = request.form.get("slug", "").strip().lower()
    baslik = request.form.get("baslik", "").strip()
    icerik = request.form.get("icerik", "").strip()
    sekme = request.form.get("sekme", "icerik").strip()

    if not slug or not baslik:
        flash("İçerik slug ve başlığı zorunludur.", "danger")
        return _admin_redirect(sekme)

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO b2b_icerikler (bolum, slug, baslik, icerik, guncelleme_tarihi)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (slug) DO UPDATE
            SET bolum = EXCLUDED.bolum,
                baslik = EXCLUDED.baslik,
                icerik = EXCLUDED.icerik,
                guncelleme_tarihi = CURRENT_TIMESTAMP
        """, (bolum, slug, baslik, icerik))
        conn.commit()
        flash("İçerik başarıyla kaydedildi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"İçerik kayıt hatası: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect(sekme)


@duzgunler_bp.route("/admin/form/ekle", methods=["POST"])
@dzg_admin_required
def admin_form_ekle():
    form_turu = request.form.get("form_turu", "İletişim Formu").strip()
    ad_soyad = request.form.get("ad_soyad", "").strip()
    firma = request.form.get("firma", "").strip()
    telefon = request.form.get("telefon", "").strip()
    email = request.form.get("email", "").strip()
    mesaj = request.form.get("mesaj", "").strip()
    sekme = request.form.get("sekme", "iletisim-formlari").strip()

    if not ad_soyad or not mesaj:
        flash("Ad soyad ve mesaj zorunludur.", "danger")
        return _admin_redirect(sekme)

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO b2b_iletisim_formlari (form_turu, ad_soyad, firma, telefon, email, mesaj, durum)
            VALUES (%s, %s, %s, %s, %s, %s, 'yeni')
        """, (form_turu, ad_soyad, firma, telefon, email, mesaj))
        conn.commit()
        flash("Form kaydı eklendi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Kayıt hatası: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect(sekme)


@duzgunler_bp.route("/admin/form/<int:form_id>/durum", methods=["POST"])
@dzg_admin_required
def admin_form_durum(form_id):
    durum = request.form.get("durum", "incelendi").strip()
    sekme = request.form.get("sekme", "iletisim-formlari").strip()
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE b2b_iletisim_formlari SET durum = %s WHERE id = %s", (durum, form_id))
        conn.commit()
        flash("Form durumu güncellendi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Güncelleme hatası: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect(sekme)


@duzgunler_bp.route("/admin/plasiyer/ekle", methods=["POST"])
@dzg_admin_required
def admin_plasiyer_ekle():
    kod = request.form.get("plasiyer_kodu", "").strip().upper()
    ad_soyad = request.form.get("ad_soyad", "").strip()
    bolge = request.form.get("bolge", "").strip()
    telefon = request.form.get("telefon", "").strip()
    email = request.form.get("email", "").strip().lower()
    sifre = request.form.get("sifre", "").strip()

    if not all([kod, ad_soyad, bolge, email, sifre]):
        flash("Satış temsilcisi eklemek için tüm zorunlu alanları doldurun.", "danger")
        return _admin_redirect("satis-temsilcileri")

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO b2b_plasiyerler (plasiyer_kodu, ad_soyad, bolge, telefon, email, sifre_hash, aktif)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
        """, (kod, ad_soyad, bolge, telefon, email, generate_password_hash(sifre)))
        conn.commit()
        flash(f"{ad_soyad} ({kod}) satış temsilcisi olarak eklendi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Ekleme hatası: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect("satis-temsilcileri")


@duzgunler_bp.route("/admin/plasiyer/<int:plasiyer_id>/durum", methods=["POST"])
@dzg_admin_required
def admin_plasiyer_durum(plasiyer_id):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE b2b_plasiyerler SET aktif = NOT aktif WHERE id = %s", (plasiyer_id,))
        conn.commit()
        flash("Satış temsilcisi durumu değiştirildi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Hata: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect("satis-temsilcileri")


@duzgunler_bp.route("/admin/yonetici/ekle", methods=["POST"])
@dzg_admin_required
def admin_yonetici_ekle():
    kullanici_adi = request.form.get("kullanici_adi", "").strip()
    ad_soyad = request.form.get("ad_soyad", "").strip()
    rol = request.form.get("rol", "admin").strip()
    sifre = request.form.get("sifre", "").strip()

    if not all([kullanici_adi, ad_soyad, sifre]):
        flash("Yönetici kullanıcı adı, ad soyad ve şifre zorunludur.", "danger")
        return _admin_redirect("yoneticiler")

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO b2b_yoneticiler (kullanici_adi, ad_soyad, rol, sifre_hash, aktif)
            VALUES (%s, %s, %s, %s, TRUE)
        """, (kullanici_adi, ad_soyad, rol, generate_password_hash(sifre)))
        conn.commit()
        flash(f"{ad_soyad} yönetici olarak eklendi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Yönetici ekleme hatası: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect("yoneticiler")


@duzgunler_bp.route("/admin/yonetici/<int:yonetici_id>/durum", methods=["POST"])
@dzg_admin_required
def admin_yonetici_durum(yonetici_id):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE b2b_yoneticiler SET aktif = NOT aktif WHERE id = %s", (yonetici_id,))
        conn.commit()
        flash("Yönetici aktiflik durumu güncellendi.", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Hata: {e}", "danger")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    return _admin_redirect("yoneticiler")


@duzgunler_bp.route("/admin/araclar/db-yenile", methods=["POST"])
@dzg_admin_required
def admin_araclar_db_yenile():
    init_db()
    flash("Veritabanı tabloları ve varsayılan kayıtlar kontrol edildi / güncellendi.", "success")
    return _admin_redirect("araclar")
