import os
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "duzgunler-elektrik-2026-key")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres.wpthfxzdhwinkamyrpyo:KOLAYV%C4%B0TR%C4%B0NSAAS@aws-1-eu-west-1.pooler.supabase.com:6543/postgres"
)

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    """Supabase PostgreSQL üzerinde gerekli tabloları ve örnek verileri oluşturur."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # B2B Bayiler Tablosu
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

        # Plasiyerler Tablosu
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

        # Ürün Kataloğu Tablosu (Hira Kapı Kolları kurumsal vitrin + Düzgünler Elektrik ürün gamı)
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

        # B2B Siparişler Tablosu
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

        # Varsayılan Demo Plasiyer Hesabı Ekle
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

        # Varsayılan Demo B2B Bayi Hesabı Ekle
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

        # Örnek Ürünler Ekle (Boşsa)
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

        conn.commit()
        cur.close()
        conn.close()
        print("Supabase PostgreSQL tabloları başarıyla doğrulandı/oluşturuldu.")
    except Exception as e:
        print("Veritabanı başlatma uyarısı:", e)

# Uygulama ayağa kalkarken tabloları hazırla
with app.app_context():
    init_db()

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_id" not in session:
                flash("Bu alanı görüntülemek için giriş yapmalısınız.", "warning")
                return redirect(url_for("index"))
            if role and session.get("role") != role:
                flash("Bu panele erişim yetkiniz bulunmamaktadır.", "danger")
                return redirect(url_for("index"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route("/")
def index():
    urunler = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM b2b_urunler ORDER BY id ASC LIMIT 6")
        urunler = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print("Ürün çekme hatası:", e)
    return render_template("index.html", urunler=urunler)

# --- B2B BAYİ GİRİŞİ ---
@app.route("/b2b-giris", methods=["POST"])
def b2b_giris():
    email_or_vkn = request.form.get("kullanici", "").strip()
    sifre = request.form.get("sifre", "")

    if not email_or_vkn or not sifre:
        flash("Lütfen E-posta / Vergi No ve şifrenizi giriniz.", "danger")
        return redirect(url_for("index", modal="b2b-login"))

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM b2b_bayiler WHERE email = %s OR vergi_no = %s",
            (email_or_vkn, email_or_vkn)
        )
        bayi = cur.fetchone()
        cur.close()
        conn.close()

        if bayi and check_password_hash(bayi["sifre_hash"], sifre):
            if bayi["durum"] != "aktif":
                flash("Bayilik başvurunuz henüz onay aşamasındadır. Müşteri temsilcinizle iletişime geçebilirsiniz.", "warning")
                return redirect(url_for("index"))

            session.clear()
            session["user_id"] = bayi["id"]
            session["role"] = "bayi"
            session["firma_unvani"] = bayi["firma_unvani"]
            session["yetkili"] = bayi["yetkili_ad_soyad"]
            session["iskonto"] = float(bayi["iskonto_orani"])
            flash(f"Hoş geldiniz, {bayi['firma_unvani']}!", "success")
            return redirect(url_for("b2b_panel"))
        else:
            flash("Hatalı E-posta/Vergi No veya şifre girdiniz.", "danger")
            return redirect(url_for("index", modal="b2b-login"))
    except Exception as e:
        flash(f"Veritabanı bağlantı hatası: {str(e)}", "danger")
        return redirect(url_for("index"))

# --- PLASİYER GİRİŞİ ---
@app.route("/plasiyer-giris", methods=["POST"])
def plasiyer_giris():
    kod_or_email = request.form.get("plasiyer_kodu", "").strip()
    sifre = request.form.get("sifre", "")

    if not kod_or_email or not sifre:
        flash("Lütfen Plasiyer Kodu / E-posta ve şifrenizi giriniz.", "danger")
        return redirect(url_for("index", modal="plasiyer-login"))

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM b2b_plasiyerler WHERE plasiyer_kodu = %s OR email = %s",
            (kod_or_email.upper(), kod_or_email)
        )
        plasiyer = cur.fetchone()
        cur.close()
        conn.close()

        if plasiyer and check_password_hash(plasiyer["sifre_hash"], sifre):
            if not plasiyer["aktif"]:
                flash("Plasiyer hesabınız pasif durumdadır.", "danger")
                return redirect(url_for("index"))

            session.clear()
            session["user_id"] = plasiyer["id"]
            session["role"] = "plasiyer"
            session["ad_soyad"] = plasiyer["ad_soyad"]
            session["plasiyer_kodu"] = plasiyer["plasiyer_kodu"]
            session["bolge"] = plasiyer["bolge"]
            flash(f"Saha Satış Paneline Hoş Geldiniz, {plasiyer['ad_soyad']}.", "success")
            return redirect(url_for("plasiyer_panel"))
        else:
            flash("Geçersiz Plasiyer Kodu veya şifre.", "danger")
            return redirect(url_for("index", modal="plasiyer-login"))
    except Exception as e:
        flash(f"Veritabanı bağlantı hatası: {str(e)}", "danger")
        return redirect(url_for("index"))

# --- B2B BAYİ KAYIT ---
@app.route("/b2b-kayit", methods=["POST"])
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
        return redirect(url_for("index", modal="b2b-register"))

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT id FROM b2b_bayiler WHERE email = %s OR vergi_no = %s", (email, vergi_no))
        if cur.fetchone():
            cur.close()
            conn.close()
            flash("Bu E-posta veya Vergi Numarası ile daha önce kayıt oluşturulmuş.", "warning")
            return redirect(url_for("index", modal="b2b-login"))

        sifre_hash = generate_password_hash(sifre)
        # Hızlı test/kullanım için durumu 'aktif' olarak kaydediyoruz (isterseniz 'onay_bekliyor' yapabilirsiniz)
        cur.execute("""
            INSERT INTO b2b_bayiler
            (firma_unvani, yetkili_ad_soyad, vergi_dairesi, vergi_no, telefon, email, sehir, adres, sifre_hash, iskonto_orani, durum)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (firma_unvani, yetkili_ad_soyad, vergi_dairesi, vergi_no, telefon, email, sehir, adres, sifre_hash, 15.00, "aktif"))

        new_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        conn.close()

        session.clear()
        session["user_id"] = new_id
        session["role"] = "bayi"
        session["firma_unvani"] = firma_unvani
        session["yetkili"] = yetkili_ad_soyad
        session["iskonto"] = 15.00

        flash("B2B Bayilik kaydınız Supabase veritabanına başarıyla işlendi ve hesabınız aktif edildi!", "success")
        return redirect(url_for("b2b_panel"))
    except Exception as e:
        flash(f"Kayıt sırasında hata oluştu: {str(e)}", "danger")
        return redirect(url_for("index", modal="b2b-register"))

# --- B2B BAYİ PANELİ ---
@app.route("/b2b-panel")
@login_required(role="bayi")
def b2b_panel():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM b2b_urunler ORDER BY kategori, id ASC")
    urunler = cur.fetchall()
    cur.execute("SELECT * FROM b2b_siparisler WHERE bayi_id = %s ORDER BY olusturma_tarihi DESC", (session["user_id"],))
    siparisler = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("b2b_panel.html", urunler=urunler, siparisler=siparisler)

# --- PLASİYER PANELİ ---
@app.route("/plasiyer-panel")
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
    return render_template("plasiyer_panel.html", bayiler=bayiler, urunler=urunler, siparisler=siparisler)

# --- HIZLI B2B SİPARİŞ OLUŞTURMA API ---
@app.route("/api/siparis-ver", methods=["POST"])
@login_required()
def siparis_ver():
    data = request.get_json()
    toplam_tutar = data.get("toplam_tutar", 0)
    notlar = data.get("notlar", "")
    bayi_id = session["user_id"] if session["role"] == "bayi" else data.get("bayi_id")
    plasiyer_id = session["user_id"] if session["role"] == "plasiyer" else None

    if not bayi_id or float(toplam_tutar) <= 0:
        return jsonify({"ok": False, "mesaj": "Geçerli bir bayi ve sepet tutarı gereklidir."}), 400

    import random
    siparis_no = f"DZG-{random.randint(100000, 999999)}"

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO b2b_siparisler (siparis_no, bayi_id, plasiyer_id, toplam_tutar, durum, notlar)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (siparis_no, bayi_id, plasiyer_id, toplam_tutar, "Onaylandı - Hazırlanıyor", notlar))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"ok": True, "siparis_no": siparis_no, "mesaj": f"{siparis_no} numaralı siparişiniz oluşturuldu."})
    except Exception as e:
        return jsonify({"ok": False, "mesaj": str(e)}), 500

# --- PLASİYER BAYİ İSKONTO / DURUM GÜNCELLEME ---
@app.route("/plasiyer/bayi-guncelle/<int:bayi_id>", methods=["POST"])
@login_required(role="plasiyer")
def bayi_guncelle(bayi_id):
    iskonto = request.form.get("iskonto_orani", 15)
    durum = request.form.get("durum", "aktif")
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE b2b_bayiler SET iskonto_orani = %s, durum = %s WHERE id = %s",
            (iskonto, durum, bayi_id)
        )
        conn.commit()
        cur.close()
        conn.close()
        flash("Bayi iskonto ve hesap durumu güncellendi.", "success")
    except Exception as e:
        flash(f"Güncelleme hatası: {e}", "danger")
    return redirect(url_for("plasiyer_panel"))

@app.route("/cikis")
def cikis():
    session.clear()
    flash("Oturumunuz güvenli bir şekilde sonlandırıldı.", "info")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
