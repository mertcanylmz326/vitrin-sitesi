import functools
import hashlib
import hmac
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.errors
import psycopg2.pool
import requests
from psycopg2.extras import RealDictCursor
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from flask import (
    Flask,
    Response,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from duzgunler import duzgunler_bp, init_db as init_duzgunler_db

try:
    import segno  # yerel QR uretimi (opsiyonel)
except ImportError:  # pragma: no cover
    segno = None

# ---------------------------------------------------------------------------
# Yapilandirma
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def _require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} ortam degiskeni tanimli degil. Render > Environment kismina ekleyin.")
    return value


def _normalize_db_url(url):
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


app.secret_key = _require_env("FLASK_SECRET_KEY")
DATABASE_URL = _normalize_db_url(_require_env("DATABASE_URL"))

app.config.update(
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")) or os.environ.get("SESSION_COOKIE_SECURE") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
)

BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR = BASE_DIR / "images"
MENU_IMAGES_DIR = IMAGES_DIR / "menu"
LOGO_IMAGES_DIR = IMAGES_DIR / "logos"
LEGACY_JSON_FILE = BASE_DIR / "tickets.json"

TR_TZ = ZoneInfo("Europe/Istanbul")
ALLOWED_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
IMG_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
MAX_IMG_BYTES = 4 * 1024 * 1024
TIME_SLOTS = [
    "09:00", "10:00", "11:00", "12:00", "13:00", "14:00",
    "15:00", "16:00", "17:00", "18:00", "19:00", "20:00",
    "21:00", "22:00", "23:00",
]
TICKET_STATUSES = {"Yeni", "İnceleniyor", "Tamamlandı", "İptal"}
VALID_RES_STATUSES = {"pending", "confirmed", "checked_in", "no_show", "cancelled"}
VALID_B2B_TIERS = {"standard", "silver", "gold", "enterprise"}
VALID_B2B_ORDER_STATUSES = {"pending", "approved", "shipped", "completed", "cancelled"}
VALID_MODULES = {
    "genel", "kafe-randevu", "berber-randevu", "masa-qr",
    "mobil-saha", "web-otomasyon", "masaustu-otomasyon", "b2b-ticaret",
}

SUPERADMIN_USERNAME = os.environ.get("SUPERADMIN_USERNAME", "").strip()
SUPERADMIN_PASSWORD = os.environ.get("SUPERADMIN_PASSWORD", "").strip()
SUPERADMIN_ENABLED = bool(SUPERADMIN_USERNAME and SUPERADMIN_PASSWORD)
VITRIN_PASSWORD = os.environ.get("VITRIN_PASSWORD", "").strip()
CRON_SECRET = os.environ.get("CRON_SECRET", "").strip()
WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "905418007395")

IBAN_HOLDER = os.environ.get("IBAN_HOLDER", "Mertcan Yılmaz / KOLAY Otomasyon")
IBAN_BANK = os.environ.get("IBAN_BANK", "Türkiye İş Bankası / Kuveyt Türk")
IBAN_NUMBER = os.environ.get("IBAN_NUMBER", "TR00 0000 0000 0000 0000 0000 00")
PLAN_PRICE_STARTER = os.environ.get("PLAN_PRICE_STARTER", os.environ.get("PLAN_PRICE_FREE", "499 TL / Ay"))
PLAN_PRICE_PRO = os.environ.get("PLAN_PRICE_PRO", "999 TL / Ay")
QR_ADDON_PRICE = os.environ.get("QR_ADDON_PRICE", "250 TL")

MODULE_LABELS = {
    "kafe-randevu": "Kafe & Restoran Masa Randevu + Masa QR",
    "berber-randevu": "Berber & Kuaför Saat Randevu",
    "masa-qr": "Masa QR Menü, Sipariş & Garson Çağır",
    "mobil-saha": "Mobil Uygulama & Saha Akışları",
    "web-otomasyon": "Web Panelleri, Formlar & Botlar",
    "masaustu-otomasyon": "Masaüstü Kasa, Barkod & Stok Otomasyonu",
    "b2b-ticaret": "B2B Kurumsal Üyelik, Toptan Sipariş & Cari",
    "genel": "Genel Talep Formu",
}

SERVICES_DATA = [
    {
        "id": "b2b-kurumsal-uyelik",
        "module_key": "b2b-ticaret",
        "tag": "B2B Kurumsal",
        "title": "B2B Üyelik, Cari Limit & Toptan Sipariş",
        "image": "webotom.jpg",
        "short": "Vergi/VKN doğrulamalı kurumsal üyelik, kademeli bayi iskontosu, cari bakiye ve toptan sipariş yönetimi.",
        "details": "Kurumsal müşterilerin VKN/vergi dairesi ve cari limitleriyle sisteme tanımlandığı, toptan siparişlerin onaylanıp cari ekstresine işlendiği B2B altyapısı.",
        "features": [
            "Kurumsal ünvan, Vergi Dairesi / VKN ve vade/limit tanımlama",
            "Standard, Silver, Gold ve Enterprise bayi segmentleri",
            "Toptan sipariş oluşturma, onaylama ve otomatik cari borç/tahsilat kaydı",
            "Panel ve JSON API üzerinden anlık cari limit kontrolü",
        ],
    },
    {
        "id": "mobil-otomasyon",
        "module_key": "mobil-saha",
        "tag": "Mobil Otomasyon",
        "title": "Mobil Uygulama & Saha Akışları",
        "image": "mobilsaha.jpg",
        "short": "Saha elemanı canlı konum, şarj durumu, aktif paket ve müşteri teslimat akışlarını takip eden mobil saha sistemi.",
        "details": "Saha personeline özel link üzerinden GPS konum, batarya/şarj yüzdesi, üzerindeki paket ve gittiği müşteri bilgisini işletme paneline canlı aktaran sistem.",
        "features": [
            "Saha elemanı linki ile tek tuşla konum & batarya izni ve canlı takip",
            "Hangi paket üzerinde, hangi müşteriye gidiyor anlık görüntüleme",
            "Harita üzerinde tek tıkla canlı konum açma ve teslimat durumu",
            "İşletme panelinden tüm saha ekibini tek ekrandan izleme",
        ],
    },
    {
        "id": "web-otomasyon",
        "module_key": "web-otomasyon",
        "tag": "Web Otomasyon",
        "title": "Web Panelleri, Formlar & Botlar",
        "image": "webotom.jpg",
        "short": "WhatsApp API, Telegram Bot Token, otomatik veri çekme (scraper/webhook) ve günlük raporlama entegrasyonları.",
        "details": "İşletmenin WhatsApp API, Telegram Bot, harici Webhook ve otomatik veri çekme bağlantılarını tek panelden yönetip otomatik bildirim gönderen altyapı.",
        "features": [
            "WhatsApp Cloud/Business API & otomatik müşteri mesaj entegrasyonu",
            "Telegram Bot Token & Chat ID ile anlık talep/sipariş bildirimi",
            "Otomatik veri çekme URL (API/Webhook) ve zamanlanmış raporlama",
            "Tek tıkla bağlantı testi ve canlı log takibi",
        ],
    },
    {
        "id": "masaustu-otomasyon",
        "module_key": "masaustu-otomasyon",
        "tag": "Masaüstü Otomasyon",
        "title": "Kasa, Barkod & Yerel Programlar",
        "image": "masaustuoto.jpg",
        "short": "USB barkod okuyucu uyumlu hızlı ürün satışı, anlık stok düşümü ve günlük kasa ciro takip sistemi.",
        "details": "Barkod okuyucu veya klavye ile saniyeler içinde satış düşen, kritik stokları uyaran ve günlük kasa raporunu otomatik tutan pratik otomasyon paneli.",
        "features": [
            "USB barkod okuyucu ile barkod okutulduğu anda otomatik satış",
            "Anlık stok takibi, ürün tanımlama ve fiyat yönetimi",
            "Günlük kasa cirosu ve satılan ürün özeti",
            "Karmaşık menülerden arındırılmış hızlı kasa ekranı",
        ],
    },
    {
        "id": "kafe-restoran-randevu",
        "module_key": "kafe-randevu",
        "tag": "Kafe & Restoran",
        "title": "Masa Randevu & Masa QR Sistemi",
        "image": "kaferesrandevu.jpg",
        "short": "Tarih/saat/masa bazlı rezervasyon ve her masaya özel QR kod etiketiyle hızlı masa yönetimi.",
        "details": "Kafe ve restoranlarda hem önceden masa randevusu almanı hem de her masaya özel QR kod etiketi basıp ayrı menü/sipariş ekranı sunmanı sağlayan sistem.",
        "features": [
            "Tarih, saat, boş masa ve kişi sayısına göre rezervasyon",
            "Pro pakette veya +250 TL eklentiyle her masa için ayrı QR sipariş ekranı",
            "Fotoğraflı dijital menü, Garson Çağır ve Hesap İste butonları",
            "İşletme panelinden tek tıkla onay ve WhatsApp dönüşü",
        ],
    },
    {
        "id": "berber-kuafor-randevu",
        "module_key": "berber-randevu",
        "tag": "Berber & Kuaför",
        "title": "Salon Randevu & Saat Yönetimi",
        "image": "berberrandevu.jpg",
        "short": "Müşterilerin tarih ve müsait saatleri ayrı ayrı seçebildiği, dolu saatleri kapatan randevu sistemi.",
        "details": "Telefon trafiğini azaltan, müşterinin önce tarihi seçip o tarihteki boş saatleri görerek randevu aldığı modern salon randevu altyapısı.",
        "features": [
            "Tarih ve saat ayrı seçim; dolu saatleri otomatik kilitleme",
            "Saç, sakal, bakım gibi hizmet türüne göre planlama",
            "Usta/personel tercihi ve müşteri notu",
            "Mobil ekrandan hızlı onay, iptal ve WhatsApp dönüşü",
        ],
    },
    {
        "id": "masa-qr-garson",
        "module_key": "masa-qr",
        "tag": "Masa QR & Garson",
        "title": "QR Menü, Sipariş & Garson Çağır Sistemi",
        "image": "kaferestoqr.jpg",
        "short": "Masadaki QR kod üzerinden menüyü görüp sepetle sipariş verme ve tek dokunuşla garson/hesap çağırma sistemi.",
        "details": "Masaya oturan müşterilerin QR kodu okutarak fotoğraflı menüyü incelemesini, adetli sipariş vermesini ve tek tuşla garson/hesap çağırmasını sağlayan masa yönetim sistemi.",
        "features": [
            "Her masaya özel tanımlı QR kod etiketi ve A4 yazdırma sayfası",
            "Tek dokunuşla 'Garson Çağır' ve 'Hesap İste' bildirimi",
            "Fotoğraflı QR menüden sepete ürün ekleyip sipariş verme",
            "Uygulama indirmeden doğrudan tarayıcıdan çalışma",
        ],
    },
]


# ---------------------------------------------------------------------------
# Yardimcilar
# ---------------------------------------------------------------------------
def now_tr():
    """Turkiye saatiyle (naive) simdi."""
    return datetime.now(TR_TZ).replace(tzinfo=None)


def today_tr():
    return now_tr().date()


def slugify(text):
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    cleaned = (text or "").translate(tr_map).lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")[:60]
    return cleaned or f"isletme-{uuid.uuid4().hex[:6]}"


def normalize_phone(raw_phone):
    digits = re.sub(r"\D+", "", raw_phone or "")
    if not digits:
        return ""
    if digits.startswith("0") and len(digits) == 11:
        return "90" + digits[1:]
    if len(digits) == 10 and digits.startswith("5"):
        return "90" + digits
    return digits


def parse_price_number(price_str):
    """'1.250,50 TL' -> 1250.5 | '1.250' -> 1250 | '12,5' -> 12.5 | '90' -> 90"""
    s = re.sub(r"[^0-9.,]", "", str(price_str or ""))
    if not s:
        return 0.0
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if re.fullmatch(r"\d+,\d{1,2}", s) else s.replace(",", "")
    elif "." in s and re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_date(value):
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def safe_next(url, fallback):
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url and "\n" not in url and "\r" not in url:
        return url
    return fallback


def clean_text(value, limit):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", (value or "").strip())[:limit]


def hash_pin(pin_code: str) -> str:
    return hashlib.sha256(str(pin_code or "").strip().encode("utf-8")).hexdigest()


def _money(val) -> Decimal:
    return Decimal(str(val or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


_rl_store = {}
_rl_lock = threading.Lock()


def rate_limited(key, limit, window_sec):
    """True donerse limit asildi. (Surec ici bellek; worker basina.)"""
    now = time.time()
    with _rl_lock:
        if len(_rl_store) > 5000:
            for k in [k for k, v in _rl_store.items() if not v or now - v[-1] > window_sec]:
                _rl_store.pop(k, None)
        hits = [t for t in _rl_store.get(key, []) if now - t < window_sec]
        if len(hits) >= limit:
            _rl_store[key] = hits
            return True
        hits.append(now)
        _rl_store[key] = hits
        return False


# ---------------------------------------------------------------------------
# Veritabani (baglanti havuzu)
# ---------------------------------------------------------------------------
_pool = None
_pool_lock = threading.Lock()
_last_used = {}


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                host = urlparse(DATABASE_URL).hostname or ""
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    1,
                    int(os.environ.get("DB_POOL_MAX", "8")),
                    dsn=DATABASE_URL,
                    cursor_factory=RealDictCursor,
                    sslmode="require" if "supabase" in host else "prefer",
                    connect_timeout=10,
                )
    return _pool


def _acquire():
    pool = _get_pool()
    for _ in range(3):
        conn = pool.getconn()
        try:
            if conn.closed:
                raise psycopg2.OperationalError("closed")
            if time.time() - _last_used.get(id(conn), 0) > 30:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                conn.rollback()
            return conn
        except psycopg2.Error:
            pool.putconn(conn, close=True)
    raise psycopg2.OperationalError("Veritabani baglantisi kurulamadi")


class get_db:
    """`with get_db() as conn:` -> commit/rollback + baglantiyi havuza iade."""

    def __enter__(self):
        self.conn = _acquire()
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        broken = False
        try:
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()
        except Exception:
            broken = True
        _last_used[id(self.conn)] = time.time()
        try:
            _get_pool().putconn(self.conn, close=broken or bool(self.conn.closed))
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# Gorsel yukleme
# ---------------------------------------------------------------------------
def _sniff_ok(ext, raw):
    if ext in (".jpg", ".jpeg"):
        return raw[:3] == b"\xff\xd8\xff"
    if ext == ".png":
        return raw[:8] == b"\x89PNG\r\n\x1a\n"
    if ext == ".webp":
        return raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    return False


def save_uploaded_image(subdir, tenant_id, file_storage):
    if not file_storage or not file_storage.filename:
        return ""
    ext = Path(secure_filename(file_storage.filename)).suffix.lower()
    if ext not in ALLOWED_IMG_EXTS:
        return ""
    raw_bytes = file_storage.read(MAX_IMG_BYTES + 1)
    if not raw_bytes or len(raw_bytes) > MAX_IMG_BYTES or not _sniff_ok(ext, raw_bytes):
        return ""

    fname = f"{uuid.uuid4().hex[:12]}{ext}"
    category = subdir.name
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO stored_images (tenant_id, category, filename, content_type, data)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, category, filename)
                    DO UPDATE SET content_type = EXCLUDED.content_type, data = EXCLUDED.data
                    """,
                    (tenant_id, category, fname, IMG_MIME[ext], psycopg2.Binary(raw_bytes)),
                )
    except Exception as exc:
        app.logger.error("Veritabani gorsel kayit hatasi: %s", exc)
        return ""
    return fname


def get_stored_image_from_db(tenant_id, category, filename):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content_type, data FROM stored_images WHERE tenant_id = %s AND category = %s AND filename = %s",
                (tenant_id, category, filename),
            )
            return cur.fetchone()


# ---------------------------------------------------------------------------
# Sema
# ---------------------------------------------------------------------------
def init_db():
    MENU_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    LOGO_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(7272741)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    id SERIAL PRIMARY KEY,
                    slug TEXT UNIQUE NOT NULL,
                    business_name TEXT NOT NULL,
                    owner_email TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    plan TEXT NOT NULL DEFAULT 'starter',
                    module_type TEXT NOT NULL DEFAULT 'b2b-ticaret',
                    table_count INTEGER NOT NULL DEFAULT 8,
                    logo_filename TEXT DEFAULT '',
                    whatsapp_number TEXT DEFAULT '',
                    payment_note TEXT DEFAULT '',
                    payment_requested BOOLEAN NOT NULL DEFAULT FALSE,
                    qr_addon_active BOOLEAN NOT NULL DEFAULT FALSE,
                    qr_addon_requested BOOLEAN NOT NULL DEFAULT FALSE,
                    qr_addon_note TEXT DEFAULT '',
                    bot_config_json TEXT DEFAULT '{}',
                    company_legal_name TEXT DEFAULT '',
                    tax_office TEXT DEFAULT '',
                    tax_number TEXT DEFAULT '',
                    b2b_tier TEXT NOT NULL DEFAULT 'standard',
                    credit_limit NUMERIC(12,2) NOT NULL DEFAULT 50000.00,
                    payment_term_days INTEGER NOT NULL DEFAULT 30,
                    is_active BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    activated_at TIMESTAMP
                );
                """
            )
            for ddl in (
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS module_type TEXT NOT NULL DEFAULT 'b2b-ticaret'",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS table_count INTEGER NOT NULL DEFAULT 8",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS logo_filename TEXT DEFAULT ''",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS payment_note TEXT DEFAULT ''",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS payment_requested BOOLEAN NOT NULL DEFAULT FALSE",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS qr_addon_active BOOLEAN NOT NULL DEFAULT FALSE",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS qr_addon_requested BOOLEAN NOT NULL DEFAULT FALSE",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS qr_addon_note TEXT DEFAULT ''",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS bot_config_json TEXT DEFAULT '{}'",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS company_legal_name TEXT DEFAULT ''",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS tax_office TEXT DEFAULT ''",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS tax_number TEXT DEFAULT ''",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS b2b_tier TEXT NOT NULL DEFAULT 'standard'",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS credit_limit NUMERIC(12,2) NOT NULL DEFAULT 50000.00",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS payment_term_days INTEGER NOT NULL DEFAULT 30",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS activated_at TIMESTAMP",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP",
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS access_token TEXT",
                "UPDATE tenants SET plan = 'starter' WHERE plan = 'free'",
                """UPDATE tenants SET expires_at = activated_at + INTERVAL '30 days'
                   WHERE is_active = TRUE AND activated_at IS NOT NULL AND expires_at IS NULL""",
            ):
                cur.execute(ddl)

            cur.execute("SELECT id FROM tenants WHERE access_token IS NULL OR access_token = ''")
            for row in cur.fetchall():
                cur.execute("UPDATE tenants SET access_token = %s WHERE id = %s", (secrets.token_urlsafe(24), row["id"]))

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS b2b_orders (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    order_code VARCHAR(32) UNIQUE NOT NULL,
                    item_summary TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    unit_price NUMERIC(12,2) NOT NULL DEFAULT 0.00,
                    discount_rate NUMERIC(5,2) NOT NULL DEFAULT 0.00,
                    total_amount NUMERIC(12,2) NOT NULL DEFAULT 0.00,
                    status VARCHAR(24) NOT NULL DEFAULT 'pending',
                    note TEXT DEFAULT '',
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_b2b_orders_tenant ON b2b_orders(tenant_id, id DESC)")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS b2b_ledger (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    entry_type VARCHAR(24) NOT NULL,
                    amount NUMERIC(12,2) NOT NULL DEFAULT 0.00,
                    description TEXT NOT NULL DEFAULT '',
                    ref_order_code VARCHAR(32) DEFAULT '',
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_b2b_ledger_tenant ON b2b_ledger(tenant_id, id DESC)")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS stored_images (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    category TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL DEFAULT 'image/jpeg',
                    data BYTEA NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE(tenant_id, category, filename)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant_menu_items (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    price TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    image_filename TEXT DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_menu_tenant_id ON tenant_menu_items(tenant_id)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS field_agents (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    agent_name TEXT NOT NULL,
                    active_package TEXT DEFAULT '',
                    target_customer TEXT DEFAULT '',
                    battery_level INTEGER DEFAULT -1,
                    is_charging BOOLEAN DEFAULT FALSE,
                    latitude TEXT DEFAULT '',
                    longitude TEXT DEFAULT '',
                    status_text TEXT DEFAULT 'Sahada Aktif',
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_field_agents_tenant ON field_agents(tenant_id)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pos_products (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    barcode TEXT NOT NULL,
                    name TEXT NOT NULL,
                    price NUMERIC(12,2) NOT NULL DEFAULT 0,
                    stock INTEGER NOT NULL DEFAULT 0,
                    sold_today INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE(tenant_id, barcode)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pos_products_tenant ON pos_products(tenant_id)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pos_sales (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    product_id INTEGER REFERENCES pos_products(id) ON DELETE SET NULL,
                    barcode TEXT,
                    name TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    unit_price NUMERIC(12,2) NOT NULL,
                    total NUMERIC(12,2) NOT NULL,
                    sold_at TIMESTAMP NOT NULL,
                    voided BOOLEAN NOT NULL DEFAULT FALSE
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pos_sales_tenant_time ON pos_sales(tenant_id, sold_at)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY,
                    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    phone TEXT,
                    service TEXT,
                    message TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Yeni',
                    created_at TEXT NOT NULL
                )
                """
            )
            cur.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS created_ts TIMESTAMP")
            cur.execute(
                r"""UPDATE tickets SET created_ts = to_timestamp(created_at, 'DD.MM.YYYY HH24:MI')::timestamp
                    WHERE created_ts IS NULL AND created_at ~ '^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}'"""
            )
            cur.execute("UPDATE tickets SET created_ts = NOW() WHERE created_ts IS NULL")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_tenant_id ON tickets(tenant_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_tenant_ts ON tickets(tenant_id, created_ts DESC)")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS reservations (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    ticket_id TEXT REFERENCES tickets(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    res_date DATE NOT NULL,
                    slot TEXT NOT NULL,
                    table_no INTEGER,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS res_status VARCHAR(24) NOT NULL DEFAULT 'confirmed'")
            cur.execute("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS duration_minutes INTEGER NOT NULL DEFAULT 90")
            cur.execute("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS party_size INTEGER NOT NULL DEFAULT 2")
            cur.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS uq_res_table
                   ON reservations(tenant_id, res_date, slot, table_no) WHERE is_active AND kind = 'table'"""
            )
            cur.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS uq_res_barber
                   ON reservations(tenant_id, res_date, slot) WHERE is_active AND kind = 'barber'"""
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_res_lookup ON reservations(tenant_id, res_date)")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS dining_tables (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    table_name VARCHAR(80) NOT NULL,
                    capacity INTEGER NOT NULL DEFAULT 4,
                    status VARCHAR(32) NOT NULL DEFAULT 'empty',
                    active_order_code VARCHAR(64) NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (tenant_id, table_name)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant_staff (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    staff_name VARCHAR(120) NOT NULL,
                    role VARCHAR(32) NOT NULL DEFAULT 'cashier',
                    pin_hash VARCHAR(128) NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS webhook_logs (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    event_name VARCHAR(80) NOT NULL,
                    target_url TEXT NOT NULL,
                    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    status_code INTEGER NOT NULL DEFAULT 0,
                    success BOOLEAN NOT NULL DEFAULT FALSE,
                    response_snippet TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_dining_tables_tenant ON dining_tables(tenant_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tenant_staff_tenant ON tenant_staff(tenant_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_webhook_logs_tenant ON webhook_logs(tenant_id, created_at DESC)")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_logs (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    created_at TIMESTAMP NOT NULL,
                    level TEXT NOT NULL DEFAULT 'info',
                    message TEXT NOT NULL
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_bot_logs_tenant ON bot_logs(tenant_id, id DESC)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_report_state (
                    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
                    last_report_date DATE NOT NULL
                )
                """
            )

            cur.execute("SELECT id, password_hash FROM tenants WHERE slug = %s", ("kolay-vitrin",))
            vit = cur.fetchone()
            if not vit:
                pw = VITRIN_PASSWORD or secrets.token_urlsafe(12)
                cur.execute(
                    """
                    INSERT INTO tenants (slug, business_name, owner_email, password_hash, plan, module_type,
                        table_count, whatsapp_number, payment_note, payment_requested, is_active, activated_at,
                        expires_at, access_token)
                    VALUES (%s,%s,%s,%s,'pro','b2b-ticaret',8,%s,%s,FALSE,TRUE,NOW(), NOW() + INTERVAL '3650 days', %s)
                    """,
                    (
                        "kolay-vitrin", "KOLAY B2B Ana Vitrin", "iletisim@kolayotomasyon.local",
                        generate_password_hash(pw), WHATSAPP_NUMBER, "Varsayilan aktif B2B vitrin hesabi",
                        secrets.token_urlsafe(24),
                    ),
                )
                if not VITRIN_PASSWORD:
                    app.logger.warning("kolay-vitrin icin rastgele sifre olusturuldu: Super Admin > Duzenle ile degistirin.")
            elif check_password_hash(vit["password_hash"], "kolay1234"):
                pw = VITRIN_PASSWORD or secrets.token_urlsafe(12)
                cur.execute("UPDATE tenants SET password_hash = %s WHERE id = %s", (generate_password_hash(pw), vit["id"]))
                app.logger.warning("kolay-vitrin eski varsayilan sifresi degistirildi (VITRIN_PASSWORD veya rastgele).")

            _migrate_legacy(cur)
            _backfill_reservations(cur)


def _migrate_legacy(cur):
    cur.execute("SELECT COUNT(*) AS cnt FROM tickets")
    if cur.fetchone()["cnt"] != 0 or not LEGACY_JSON_FILE.exists():
        return
    cur.execute("SELECT id FROM tenants WHERE slug = %s", ("kolay-vitrin",))
    tid = cur.fetchone()["id"]
    try:
        raw = json.loads(LEGACY_JSON_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(raw, list):
        return
    for item in reversed(raw):
        if isinstance(item, dict) and item.get("name") and item.get("message"):
            created = str(item.get("created_at") or now_tr().strftime("%d.%m.%Y %H:%M")).strip()
            cur.execute(
                """INSERT INTO tickets (id, tenant_id, name, phone, service, message, status, created_at, created_ts)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
                (
                    str(item.get("id") or uuid.uuid4().hex[:8]), tid, str(item.get("name", "")).strip(),
                    str(item.get("phone", "")).strip(), str(item.get("service", "")).strip(),
                    str(item.get("message", "")).strip(), str(item.get("status") or "Yeni").strip(),
                    created, now_tr(),
                ),
            )


def _backfill_reservations(cur):
    """Eski serbest metin randevulari, tablo bos ise bir kerelik yeni tabloya aktar."""
    cur.execute("SELECT COUNT(*) AS cnt FROM reservations")
    if cur.fetchone()["cnt"] != 0:
        return
    cur.execute(
        """SELECT t.id, t.tenant_id, t.service, t.status, tn.module_type
           FROM tickets t JOIN tenants tn ON tn.id = t.tenant_id
           WHERE tn.module_type IN ('kafe-randevu','berber-randevu')"""
    )
    for r in cur.fetchall():
        svc = r["service"] or ""
        active = r["status"] != "İptal"
        if r["module_type"] == "kafe-randevu":
            m = re.search(r"Randevu (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) — Masa (\d+)", svc)
            if m:
                cur.execute(
                    """INSERT INTO reservations (tenant_id, ticket_id, kind, res_date, slot, table_no, is_active)
                       VALUES (%s,%s,'table',%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (r["tenant_id"], r["id"], m.group(1), m.group(2), int(m.group(3)), active),
                )
        else:
            m = re.search(r"\((\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})\)", svc)
            if m:
                cur.execute(
                    """INSERT INTO reservations (tenant_id, ticket_id, kind, res_date, slot, is_active)
                       VALUES (%s,%s,'barber',%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (r["tenant_id"], r["id"], m.group(1), m.group(2), active),
                )


# ---------------------------------------------------------------------------
# B2B & Tenant verisi
# ---------------------------------------------------------------------------
_TENANT_SELECT = """
    SELECT t.*, (t.is_active AND t.expires_at IS NOT NULL AND t.expires_at < NOW()) AS is_expired
    FROM tenants t
"""


def tenant_usable(tenant):
    return bool(tenant["is_active"]) and not tenant.get("is_expired")


def tenant_has_qr_access(tenant):
    mod = tenant.get("module_type") or "b2b-ticaret"
    if mod == "masa-qr":
        return True
    if mod == "kafe-randevu":
        return (tenant.get("plan") == "pro") or bool(tenant.get("qr_addon_active"))
    return False


def get_tenant_by_slug(slug):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(_TENANT_SELECT + " WHERE t.slug = %s", (slug,))
            return cur.fetchone()


def get_tenant_by_id(tenant_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(_TENANT_SELECT + " WHERE t.id = %s", (tenant_id,))
            return cur.fetchone()


def get_all_tenants():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.*, COUNT(tk.id) AS ticket_count,
                       (t.is_active AND t.expires_at IS NOT NULL AND t.expires_at < NOW()) AS is_expired,
                       CASE WHEN t.expires_at IS NULL THEN NULL ELSE (t.expires_at::date - CURRENT_DATE) END AS days_left
                FROM tenants t
                LEFT JOIN tickets tk ON tk.tenant_id = t.id
                GROUP BY t.id
                ORDER BY t.is_active ASC, t.payment_requested DESC, t.qr_addon_requested DESC, t.id DESC
                """
            )
            rows = [dict(r) for r in cur.fetchall()]
    for d in rows:
        exp = d.get("expires_at")
        d["expires_str"] = exp.strftime("%d.%m.%Y") if exp else "-"
        d["is_expired"] = bool(d.get("is_expired"))
    return rows


def create_tenant(
    business_name,
    owner_email,
    password,
    raw_slug="",
    plan="starter",
    module_type="b2b-ticaret",
    whatsapp_number="",
    company_legal_name="",
    tax_office="",
    tax_number="",
    b2b_tier="standard",
    credit_limit=50000.0,
    payment_term_days=30,
):
    base_slug = slugify(raw_slug or business_name)
    mod = module_type if module_type in VALID_MODULES else "b2b-ticaret"
    chosen_plan = plan if plan in {"starter", "pro"} else "starter"
    tier = b2b_tier if b2b_tier in VALID_B2B_TIERS else "standard"
    limit_val = _money(max(0.0, float(credit_limit or 50000.0)))
    term_days = max(0, min(365, int(payment_term_days or 30)))
    default_tables = 8 if mod in {"kafe-randevu", "masa-qr"} else 4
    with get_db() as conn:
        with conn.cursor() as cur:
            candidate, suffix = base_slug, 1
            while True:
                cur.execute("SELECT id FROM tenants WHERE slug = %s", (candidate,))
                if not cur.fetchone():
                    break
                suffix += 1
                candidate = f"{base_slug}-{suffix}"
            cur.execute(
                """
                INSERT INTO tenants (slug, business_name, owner_email, password_hash, plan, module_type,
                    table_count, whatsapp_number, company_legal_name, tax_office, tax_number,
                    b2b_tier, credit_limit, payment_term_days,
                    is_active, payment_requested, qr_addon_active, access_token)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE,FALSE,%s,%s)
                RETURNING *
                """,
                (
                    candidate, business_name.strip()[:120], owner_email.strip().lower()[:160],
                    generate_password_hash(password), chosen_plan, mod, default_tables,
                    whatsapp_number.strip()[:30],
                    (company_legal_name or business_name).strip()[:160],
                    tax_office.strip()[:100], tax_number.strip()[:40],
                    tier, limit_val, term_days,
                    chosen_plan == "pro", secrets.token_urlsafe(24),
                ),
            )
            return cur.fetchone()


def tier_default_discount(tier: str) -> Decimal:
    mapping = {
        "standard": Decimal("0.00"),
        "silver": Decimal("5.00"),
        "gold": Decimal("10.00"),
        "enterprise": Decimal("15.00"),
    }
    return mapping.get((tier or "standard").lower(), Decimal("0.00"))


def get_b2b_summary(tenant):
    tid = tenant["id"]
    credit_limit = _money(tenant.get("credit_limit") or 50000)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN entry_type = 'debit' THEN amount ELSE 0 END), 0) AS total_debit,
                    COALESCE(SUM(CASE WHEN entry_type = 'credit' THEN amount ELSE 0 END), 0) AS total_credit
                FROM b2b_ledger
                WHERE tenant_id = %s;
                """,
                (tid,),
            )
            bal_row = cur.fetchone() or {}
            total_debit = _money(bal_row.get("total_debit") or 0)
            total_credit = _money(bal_row.get("total_credit") or 0)
            current_balance = _money(total_debit - total_credit)
            available_credit = _money(credit_limit - current_balance)

            cur.execute(
                """
                SELECT id, order_code, item_summary, quantity, unit_price, discount_rate, total_amount, status, note, created_at
                  FROM b2b_orders
                 WHERE tenant_id = %s
                 ORDER BY id DESC
                 LIMIT 40;
                """,
                (tid,),
            )
            orders = []
            for r in cur.fetchall():
                d = dict(r)
                d["unit_price"] = float(d.get("unit_price") or 0)
                d["discount_rate"] = float(d.get("discount_rate") or 0)
                d["total_amount"] = float(d.get("total_amount") or 0)
                d["created_str"] = d["created_at"].strftime("%d.%m.%Y %H:%M") if d.get("created_at") else "-"
                orders.append(d)

            cur.execute(
                """
                SELECT id, entry_type, amount, description, ref_order_code, created_at
                  FROM b2b_ledger
                 WHERE tenant_id = %s
                 ORDER BY id DESC
                 LIMIT 30;
                """,
                (tid,),
            )
            ledger = []
            for r in cur.fetchall():
                d = dict(r)
                d["amount"] = float(d.get("amount") or 0)
                d["created_str"] = d["created_at"].strftime("%d.%m.%Y %H:%M") if d.get("created_at") else "-"
                ledger.append(d)

    return {
        "company_legal_name": tenant.get("company_legal_name") or tenant.get("business_name") or "",
        "tax_office": tenant.get("tax_office") or "",
        "tax_number": tenant.get("tax_number") or "",
        "b2b_tier": tenant.get("b2b_tier") or "standard",
        "credit_limit": float(credit_limit),
        "payment_term_days": int(tenant.get("payment_term_days") or 30),
        "total_debit": float(total_debit),
        "total_credit": float(total_credit),
        "current_balance": float(current_balance),
        "available_credit": float(available_credit),
        "orders": orders,
        "ledger": ledger,
    }


def get_menu_items(tenant_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, tenant_id, name, price, description, image_filename, sort_order
                   FROM tenant_menu_items WHERE tenant_id = %s ORDER BY sort_order ASC, id ASC""",
                (tenant_id,),
            )
            items = []
            for r in cur.fetchall():
                d = dict(r)
                d["numeric_price"] = parse_price_number(d.get("price"))
                items.append(d)
            return items


# ---------------------------------------------------------------------------
# Saha elemanlari
# ---------------------------------------------------------------------------
def get_field_agents(tenant_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM field_agents WHERE tenant_id = %s ORDER BY updated_at DESC, id DESC",
                (tenant_id,),
            )
            rows = cur.fetchall()
    now = now_tr()
    out = []
    for r in rows:
        upd = r.get("updated_at")
        age = max(0, int((now - upd).total_seconds())) if upd else 10**9
        out.append({
            "id": r["id"],
            "agent_name": r["agent_name"],
            "status_text": r["status_text"] or "",
            "battery_level": r["battery_level"] if r["battery_level"] is not None else -1,
            "is_charging": bool(r["is_charging"]),
            "active_package": r["active_package"] or "",
            "target_customer": r["target_customer"] or "",
            "latitude": r["latitude"] or "",
            "longitude": r["longitude"] or "",
            "updated_str": upd.strftime("%d.%m.%Y %H:%M:%S") if upd else "-",
            "age_sec": age,
            "online": age < 150,
        })
    return out


# ---------------------------------------------------------------------------
# Kasa / barkod
# ---------------------------------------------------------------------------
def pos_day_start():
    return now_tr().replace(hour=0, minute=0, second=0, microsecond=0)


def get_pos_overview(tenant_id):
    start = pos_day_start()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.*, COALESCE(s.q, 0) AS sold_today
                FROM pos_products p
                LEFT JOIN (
                    SELECT product_id, SUM(qty) AS q FROM pos_sales
                    WHERE tenant_id = %s AND sold_at >= %s AND NOT voided GROUP BY product_id
                ) s ON s.product_id = p.id
                WHERE p.tenant_id = %s ORDER BY p.id DESC
                """,
                (tenant_id, start, tenant_id),
            )
            products = []
            for r in cur.fetchall():
                d = dict(r)
                d["price_num"] = float(d.get("price") or 0)
                d["sold_today"] = int(d.get("sold_today") or 0)
                products.append(d)
            cur.execute(
                """SELECT COALESCE(SUM(qty),0) AS q, COALESCE(SUM(total),0) AS rev
                   FROM pos_sales WHERE tenant_id = %s AND sold_at >= %s AND NOT voided""",
                (tenant_id, start),
            )
            tot = cur.fetchone()
            cur.execute(
                """SELECT id, name, qty, total, sold_at, voided FROM pos_sales
                   WHERE tenant_id = %s ORDER BY id DESC LIMIT 15""",
                (tenant_id,),
            )
            sales = [
                dict(r, total=float(r["total"]), time_str=r["sold_at"].strftime("%d.%m %H:%M"))
                for r in cur.fetchall()
            ]
    return products, int(tot["q"]), float(tot["rev"]), sales


# ---------------------------------------------------------------------------
# Talepler & randevular
# ---------------------------------------------------------------------------
class SlotTaken(Exception):
    pass


def _urgency(minutes):
    if minutes >= 15:
        return "urgent"
    if minutes >= 8:
        return "warn"
    return "ok"


def load_tickets(tenant_id, limit=300, statuses=None):
    sql = """SELECT id, tenant_id, name, phone, service, message, status, created_at, created_ts
             FROM tickets WHERE tenant_id = %s"""
    params = [tenant_id]
    if statuses:
        sql += " AND status = ANY(%s)"
        params.append(list(statuses))
    sql += " ORDER BY created_ts DESC NULLS LAST, id DESC LIMIT %s"
    params.append(limit)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    now = now_tr()
    result = []
    for r in rows:
        d = dict(r)
        clean_p = normalize_phone(d.get("phone"))
        txt = f"Merhaba {d['name']}, talebinizle ilgili dönüş yapıyorum."
        d["wa_link"] = f"https://wa.me/{clean_p}?text={quote(txt)}" if clean_p else ""
        ts = d.get("created_ts")
        mins = max(0, int((now - ts).total_seconds() // 60)) if ts else 0
        d["elapsed_mins"] = mins
        d["urgency_level"] = _urgency(mins)
        result.append(d)
    return result


def ticket_stats(tenant_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) AS total,
                          COUNT(*) FILTER (WHERE status = 'Yeni') AS yeni,
                          COUNT(*) FILTER (WHERE status = 'Tamamlandı') AS tamam,
                          COUNT(*) FILTER (WHERE status IN ('Yeni','İnceleniyor')) AS active
                   FROM tickets WHERE tenant_id = %s""",
                (tenant_id,),
            )
            row = cur.fetchone()
            cur.execute(
                """SELECT id, name, service, message FROM tickets WHERE tenant_id = %s
                   ORDER BY created_ts DESC NULLS LAST, id DESC LIMIT 1""",
                (tenant_id,),
            )
            latest = cur.fetchone()
            cur.execute(
                """SELECT id FROM tickets WHERE tenant_id = %s AND status IN ('Yeni','İnceleniyor')
                   ORDER BY created_ts DESC NULLS LAST, id DESC LIMIT 1""",
                (tenant_id,),
            )
            latest_active = cur.fetchone()
    return {
        "total": int(row["total"]), "yeni": int(row["yeni"]), "tamam": int(row["tamam"]),
        "active": int(row["active"]),
        "latest": latest, "latest_active_id": latest_active["id"] if latest_active else "",
    }


def recent_duplicate(tenant_id, name, service, seconds=60):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM tickets WHERE tenant_id = %s AND name = %s AND service = %s
                   AND status IN ('Yeni','İnceleniyor') AND created_ts > %s LIMIT 1""",
                (tenant_id, name, service, now_tr() - timedelta(seconds=seconds)),
            )
            return cur.fetchone() is not None


def add_ticket(tenant, name, phone, service, message, reservation=None):
    """Talebi (ve varsa rezervasyonu) tek islemde kaydeder; dolu ise SlotTaken firlatir."""
    ticket_id = uuid.uuid4().hex[:8]
    ts = now_tr()
    created_at = ts.strftime("%d.%m.%Y %H:%M")
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO tickets (id, tenant_id, name, phone, service, message, status, created_at, created_ts)
                       VALUES (%s,%s,%s,%s,%s,%s,'Yeni',%s,%s)""",
                    (ticket_id, tenant["id"], name, phone, service, message, created_at, ts),
                )
                if reservation:
                    cur.execute(
                        """INSERT INTO reservations (tenant_id, ticket_id, kind, res_date, slot, table_no, res_status, duration_minutes, party_size)
                           VALUES (%s,%s,%s,%s,%s,%s,'confirmed',%s,%s)""",
                        (
                            tenant["id"], ticket_id, reservation["kind"], reservation["res_date"],
                            reservation["slot"], reservation.get("table_no"),
                            int(reservation.get("duration_minutes") or 90),
                            int(reservation.get("party_size") or 2),
                        ),
                    )
    except psycopg2.errors.UniqueViolation:
        raise SlotTaken()
    ticket = {
        "id": ticket_id, "name": name, "phone": phone,
        "service": service, "message": message, "created_at": created_at,
    }
    run_async(notify_new_ticket, dict(tenant), ticket)
    return ticket_id


def update_ticket_status(tenant_id, ticket_id, new_status):
    """False donerse: iptal geri alinirken masa/saat baskasi tarafindan alinmis."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE tickets SET status = %s WHERE id = %s AND tenant_id = %s",
                    (new_status, ticket_id, tenant_id),
                )
                cur.execute(
                    """UPDATE reservations
                       SET is_active = %s,
                           res_status = CASE WHEN %s = 'İptal' THEN 'cancelled' ELSE res_status END
                       WHERE ticket_id = %s AND tenant_id = %s""",
                    (new_status != "İptal", new_status, ticket_id, tenant_id),
                )
        return True
    except psycopg2.errors.UniqueViolation:
        return False


def delete_ticket_by_id(tenant_id, ticket_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tickets WHERE id = %s AND tenant_id = %s", (ticket_id, tenant_id))


def get_booked_tables_by_slot(tenant_id, res_date):
    booked = {sl: set() for sl in TIME_SLOTS}
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT slot, table_no FROM reservations
                   WHERE tenant_id = %s AND res_date = %s AND kind = 'table' AND is_active
                     AND COALESCE(res_status, 'confirmed') NOT IN ('cancelled', 'no_show')""",
                (tenant_id, res_date),
            )
            for r in cur.fetchall():
                if r["slot"] in booked and r["table_no"] is not None:
                    booked[r["slot"]].add(r["table_no"])
    return booked


def get_booked_barber_slots(tenant_id, res_date):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT slot FROM reservations
                   WHERE tenant_id = %s AND res_date = %s AND kind = 'barber' AND is_active
                     AND COALESCE(res_status, 'confirmed') NOT IN ('cancelled', 'no_show')""",
                (tenant_id, res_date),
            )
            return {r["slot"] for r in cur.fetchall()}


def past_slots_for(res_date):
    """Secilen gun bugunse, saati gecmis slotlar."""
    if res_date != today_tr():
        return set()
    hhmm = now_tr().strftime("%H:%M")
    return {sl for sl in TIME_SLOTS if sl <= hhmm}


# ---------------------------------------------------------------------------
# Entegrasyonlar (Telegram / Webhook / WhatsApp / veri cekme + Webhook Log)
# ---------------------------------------------------------------------------
def run_async(fn, *args, **kwargs):
    t = threading.Thread(target=_safe_call, args=(fn, args, kwargs), daemon=True)
    t.start()


def _safe_call(fn, args, kwargs):
    try:
        fn(*args, **kwargs)
    except Exception as exc:
        app.logger.error("Arka plan gorevi hatasi (%s): %s", getattr(fn, "__name__", fn), exc)


def get_bot_config(tenant):
    raw = tenant.get("bot_config_json") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception:
        data = {}
    return {
        "wa_api_url": data.get("wa_api_url", ""),
        "wa_api_token": data.get("wa_api_token", ""),
        "wa_template_name": data.get("wa_template_name", ""),
        "wa_auto_reply": bool(data.get("wa_auto_reply", False)),
        "tg_bot_token": data.get("tg_bot_token", ""),
        "tg_chat_id": data.get("tg_chat_id", ""),
        "tg_notify_enabled": bool(data.get("tg_notify_enabled", False)),
        "scraper_url": data.get("scraper_url", ""),
        "report_hour": data.get("report_hour", "21:00") or "21:00",
        "webhook_url": data.get("webhook_url", ""),
        "last_sync_note": data.get("last_sync_note", ""),
    }


def save_bot_config(tenant_id, cfg):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tenants SET bot_config_json = %s WHERE id = %s",
                (json.dumps(cfg, ensure_ascii=False), tenant_id),
            )


def bot_log(tenant_id, message, level="info"):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO bot_logs (tenant_id, created_at, level, message) VALUES (%s,%s,%s,%s)",
                    (tenant_id, now_tr(), level, message[:500]),
                )
                cur.execute(
                    """DELETE FROM bot_logs WHERE tenant_id = %s AND id < COALESCE(
                       (SELECT id FROM bot_logs WHERE tenant_id = %s ORDER BY id DESC OFFSET 100 LIMIT 1), 0)""",
                    (tenant_id, tenant_id),
                )
    except Exception as exc:
        app.logger.warning("bot_log hatasi: %s", exc)


def get_bot_logs(tenant_id, limit=20):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT created_at, level, message FROM bot_logs WHERE tenant_id = %s ORDER BY id DESC LIMIT %s",
                (tenant_id, limit),
            )
            return [dict(r, time_str=r["created_at"].strftime("%d.%m %H:%M:%S")) for r in cur.fetchall()]


def is_safe_public_url(url):
    """SSRF korumasi: sadece http(s) ve herkese acik IP'ler."""
    try:
        p = urlparse((url or "").strip())
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        port = p.port or (443 if p.scheme == "https" else 80)
        for _, _, _, _, sa in socket.getaddrinfo(p.hostname, port, proto=socket.IPPROTO_TCP):
            ip = ipaddress.ip_address(sa[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                return False
        return True
    except Exception:
        return False


def safe_request(method, url, **kwargs):
    if not is_safe_public_url(url):
        raise ValueError("URL güvenli değil veya erişilemiyor")
    kwargs.setdefault("timeout", 8)
    kwargs["allow_redirects"] = False
    return requests.request(method, url.strip(), **kwargs)


def log_webhook_attempt(tenant_id, event_name, target_url, payload, status_code, success, snippet, attempt_count=1):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO webhook_logs
                        (tenant_id, event_name, target_url, payload_json, status_code, success, response_snippet, attempt_count)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                    RETURNING id, event_name, target_url, status_code, success, response_snippet, attempt_count, created_at;
                    """,
                    (
                        tenant_id,
                        event_name[:80],
                        target_url,
                        json.dumps(payload, ensure_ascii=False),
                        int(status_code or 0),
                        bool(success),
                        (snippet or "")[:500],
                        int(attempt_count or 1),
                    ),
                )
                row = dict(cur.fetchone())
                row["created_at"] = row["created_at"].isoformat() if row.get("created_at") else ""
                return row
    except Exception as exc:
        app.logger.warning("webhook_logs kayit hatasi: %s", exc)
        return None


def send_telegram(cfg, text):
    token, chat = (cfg.get("tg_bot_token") or "").strip(), (cfg.get("tg_chat_id") or "").strip()
    if not token or not chat:
        return False, "Telegram token/chat ID eksik"
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text[:3500]},
            timeout=8,
        )
        return r.ok, f"Telegram HTTP {r.status_code}"
    except Exception as exc:
        return False, f"Telegram hatası: {type(exc).__name__}"


def send_webhook(cfg, payload, tenant_id=None, event_name="webhook_event", attempt_count=1):
    url = (cfg.get("webhook_url") or "").strip()
    if not url:
        return False, "Webhook URL eksik"
    try:
        r = safe_request("POST", url, json=payload)
        if tenant_id:
            log_webhook_attempt(
                tenant_id=tenant_id,
                event_name=event_name,
                target_url=url,
                payload=payload,
                status_code=r.status_code,
                success=r.ok,
                snippet=r.text or "",
                attempt_count=attempt_count,
            )
        return r.ok, f"Webhook HTTP {r.status_code}"
    except Exception as exc:
        if tenant_id:
            log_webhook_attempt(
                tenant_id=tenant_id,
                event_name=event_name,
                target_url=url,
                payload=payload,
                status_code=0,
                success=False,
                snippet=str(exc),
                attempt_count=attempt_count,
            )
        return False, f"Webhook hatası: {exc}"


def send_whatsapp(cfg, to_phone, text):
    url, token = (cfg.get("wa_api_url") or "").strip(), (cfg.get("wa_api_token") or "").strip()
    to = normalize_phone(to_phone)
    if not url or not token:
        return False, "WhatsApp API URL/token eksik"
    if not to:
        return False, "Alıcı telefon yok"
    if cfg.get("wa_template_name"):
        body = {
            "messaging_product": "whatsapp", "to": to, "type": "template",
            "template": {"name": cfg["wa_template_name"], "language": {"code": "tr"}},
        }
    else:
        body = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:1000]}}
    try:
        r = safe_request("POST", url, json=body, headers={"Authorization": f"Bearer {token}"})
        return r.ok, f"WhatsApp HTTP {r.status_code}"
    except Exception as exc:
        return False, f"WhatsApp hatası: {exc}"


def notify_new_ticket(tenant, ticket):
    cfg = get_bot_config(tenant)
    title = f"{ticket['service']} ({ticket['name']})"
    if cfg["tg_notify_enabled"] and cfg["tg_bot_token"] and cfg["tg_chat_id"]:
        ok, info = send_telegram(cfg, f"🔔 {tenant['business_name']} — {title}\n{ticket['message']}")
        bot_log(tenant["id"], f"Yeni talep → {info}", "info" if ok else "error")
    if cfg["webhook_url"]:
        wh_payload = {
            "business": tenant["business_name"], "slug": tenant["slug"], "event": "new_ticket",
            "ticket_id": ticket["id"], "name": ticket["name"], "phone": ticket["phone"],
            "service": ticket["service"], "message": ticket["message"],
            "created_at": ticket["created_at"], "timestamp": now_tr().isoformat(),
        }
        ok, info = send_webhook(cfg, wh_payload, tenant_id=tenant["id"], event_name="new_ticket")
        bot_log(tenant["id"], f"Yeni talep → {info}", "info" if ok else "error")
    if cfg["wa_auto_reply"] and cfg["wa_api_url"] and cfg["wa_api_token"] and ticket.get("phone"):
        ok, info = send_whatsapp(
            cfg, ticket["phone"],
            f"Merhaba {ticket['name']}, talebiniz {tenant['business_name']} tarafına ulaştı. En kısa sürede dönüş yapacağız.",
        )
        bot_log(tenant["id"], f"WhatsApp karşılama → {info}", "info" if ok else "error")


def fetch_scraper_summary(url):
    """Kaynak URL'den veri cek (1 MB sinir) ve kisa ozet dondur."""
    r = safe_request("GET", url, stream=True, headers={"User-Agent": "KolayBot/1.0"})
    if not r.ok:
        raise ValueError(f"Kaynak HTTP {r.status_code} döndü")
    raw = r.raw.read(1_000_001, decode_content=True)
    if len(raw) > 1_000_000:
        raise ValueError("Kaynak 1 MB sınırını aşıyor")
    text = raw.decode(r.encoding or "utf-8", errors="replace")
    try:
        data = json.loads(text)
        if isinstance(data, list):
            first = json.dumps(data[0], ensure_ascii=False)[:200] if data else "-"
            return f"JSON liste: {len(data)} kayıt. İlk kayıt: {first}"
        if isinstance(data, dict):
            return f"JSON nesne: {len(data)} alan ({', '.join(list(data)[:8])})"
        return f"JSON değer: {str(data)[:200]}"
    except ValueError:
        plain = re.sub(r"<[^>]+>", " ", text)
        plain = re.sub(r"\s+", " ", plain).strip()
        return f"Metin ({len(text)} karakter): {plain[:250]}"


def build_daily_report(tenant, cfg):
    start = now_tr().replace(hour=0, minute=0, second=0, microsecond=0)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) AS total,
                          COUNT(*) FILTER (WHERE status = 'Yeni') AS yeni,
                          COUNT(*) FILTER (WHERE status = 'Tamamlandı') AS tamam,
                          COUNT(*) FILTER (WHERE status = 'İptal') AS iptal
                   FROM tickets WHERE tenant_id = %s AND created_ts >= %s""",
                (tenant["id"], start),
            )
            c = cur.fetchone()
    lines = [
        f"📊 {tenant['business_name']} — Günlük Rapor ({now_tr().strftime('%d.%m.%Y')})",
        f"Bugünkü talep: {c['total']} (Yeni: {c['yeni']}, Tamamlanan: {c['tamam']}, İptal: {c['iptal']})",
    ]
    if cfg.get("scraper_url"):
        try:
            lines.append("Veri kaynağı: " + fetch_scraper_summary(cfg["scraper_url"]))
        except Exception as exc:
            lines.append(f"Veri kaynağı alınamadı: {exc}")
    return "\n".join(lines)


def send_report_to_channels(tenant, cfg, text):
    results = []
    if cfg["tg_bot_token"] and cfg["tg_chat_id"]:
        results.append(send_telegram(cfg, text))
    if cfg["webhook_url"]:
        results.append(send_webhook(
            cfg,
            {
                "business": tenant["business_name"], "slug": tenant["slug"],
                "event": "daily_report", "message": text, "timestamp": now_tr().isoformat(),
            },
            tenant_id=tenant["id"],
            event_name="daily_report",
        ))
    return results


def run_due_reports():
    """Rapor saati gelmis ve bugun raporu gitmemis web-otomasyon hesaplarina rapor gonder."""
    now = now_tr()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT t.*, FALSE AS is_expired FROM tenants t
                   WHERE module_type = 'web-otomasyon' AND is_active
                     AND (expires_at IS NULL OR expires_at > NOW())"""
            )
            tenants = cur.fetchall()
    sent = 0
    for tenant in tenants:
        cfg = get_bot_config(tenant)
        if not ((cfg["tg_bot_token"] and cfg["tg_chat_id"]) or cfg["webhook_url"]):
            continue
        if now.strftime("%H:%M") < cfg["report_hour"]:
            continue
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO bot_report_state (tenant_id, last_report_date) VALUES (%s,%s)
                       ON CONFLICT (tenant_id) DO UPDATE SET last_report_date = EXCLUDED.last_report_date
                       WHERE bot_report_state.last_report_date < EXCLUDED.last_report_date
                       RETURNING tenant_id""",
                    (tenant["id"], now.date()),
                )
                claimed = cur.fetchone()
        if not claimed:
            continue
        text = build_daily_report(tenant, cfg)
        for ok, info in send_report_to_channels(tenant, cfg, text):
            bot_log(tenant["id"], f"Günlük rapor → {info}", "info" if ok else "error")
        sent += 1
    return sent


_scheduler_started = False


def start_scheduler():
    global _scheduler_started
    if _scheduler_started or os.environ.get("ENABLE_SCHEDULER", "1") == "0":
        return
    _scheduler_started = True

    def loop():
        time.sleep(15)
        while True:
            try:
                run_due_reports()
            except Exception as exc:
                app.logger.error("Zamanlayici hatasi: %s", exc)
            time.sleep(60)

    threading.Thread(target=loop, daemon=True, name="kolay-scheduler").start()


# ---------------------------------------------------------------------------
# Baslatma
# ---------------------------------------------------------------------------
init_db()
with app.app_context():
    init_duzgunler_db()
app.register_blueprint(duzgunler_bp)
start_scheduler()

if not SUPERADMIN_ENABLED:
    app.logger.warning("SUPERADMIN_USERNAME / SUPERADMIN_PASSWORD tanimli degil: /admin girisi KAPALI.")


# ---------------------------------------------------------------------------
# Guvenlik katmani: CSRF, basliklar, yetki
# ---------------------------------------------------------------------------
CSRF_EXEMPT_ENDPOINTS = {"field_agent_ping"}
_FORM_POST_RE = re.compile(r"(<form\b[^>]*\bmethod\s*=\s*[\"']?post[\"']?[^>]*>)", re.IGNORECASE)


def csrf_token():
    tok = session.get("_csrf")
    if not tok:
        tok = secrets.token_urlsafe(24)
        session["_csrf"] = tok
    return tok


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": csrf_token}


@app.before_request
def csrf_protect():
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.endpoint not in CSRF_EXEMPT_ENDPOINTS:
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("_csrf", "")
        if not sent or not expected or not hmac.compare_digest(sent.encode("utf-8"), expected.encode("utf-8")):
            abort(400, "Oturum doğrulaması başarısız. Sayfayı yenileyip tekrar deneyin.")


@app.after_request
def harden_response(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if resp.mimetype == "text/html" and not resp.direct_passthrough and resp.status_code < 400:
        body = resp.get_data(as_text=True)
        if "<form" in body.lower() and 'name="csrf_token"' not in body.lower():
            hidden = f'<input type="hidden" name="csrf_token" value="{csrf_token()}">'
            resp.set_data(_FORM_POST_RE.sub(lambda m: m.group(1) + hidden, body))
        resp.headers["Cache-Control"] = "no-store"
    return resp


def _simple_page(title, text, code):
    html = (
        '<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f"<title>{title}</title></head>"
        '<body style="background:#080d0b;color:#f8fafc;font-family:system-ui,sans-serif;'
        'display:grid;place-items:center;min-height:100vh;margin:0;padding:20px;text-align:center">'
        f'<div><h1 style="font-size:1.4rem">{title}</h1><p style="color:#9ca3af;margin:10px 0 18px">{text}</p>'
        '<a href="/" style="color:#34d399">Ana sayfaya dön</a></div></body></html>'
    )
    return Response(html, status=code, mimetype="text/html")


@app.errorhandler(400)
def err_400(e):
    return _simple_page("İstek doğrulanamadı", "Oturum süreniz dolmuş olabilir. Sayfayı yenileyip tekrar deneyin.", 400)


@app.errorhandler(403)
def err_403(e):
    return _simple_page("Erişim yok", "Bu sayfaya erişim yetkiniz bulunmuyor veya bağlantı anahtarı geçersiz.", 403)


@app.errorhandler(404)
def err_404(e):
    return _simple_page("Sayfa bulunamadı", "Aradığınız sayfa mevcut değil.", 404)


@app.errorhandler(413)
def err_413(e):
    return _simple_page("Dosya çok büyük", "Görsel boyutu en fazla 4 MB olabilir.", 413)


@app.errorhandler(429)
def err_429(e):
    return _simple_page("Çok fazla deneme", "Lütfen birkaç dakika sonra tekrar deneyin.", 429)


def tenant_login_required(view_func):
    @functools.wraps(view_func)
    def wrapped(slug, *args, **kwargs):
        tenant = get_tenant_by_slug(slug)
        if not tenant:
            abort(404)
        if slug not in session.get("tenant_auth_slugs", []):
            return redirect(url_for("tenant_login", slug=slug, next=request.path))
        g.tenant = tenant
        return view_func(slug, *args, **kwargs)

    return wrapped


def tenant_panel_required(view_func):
    """Giris + aktif/suresi dolmamis hesap sart."""

    @tenant_login_required
    @functools.wraps(view_func)
    def wrapped(slug, *args, **kwargs):
        if not tenant_usable(g.tenant):
            return redirect(url_for("tenant_panel", slug=slug))
        return view_func(slug, *args, **kwargs)

    return wrapped


def superadmin_required(view_func):
    @functools.wraps(view_func)
    def wrapped(*args, **kwargs):
        if not SUPERADMIN_ENABLED or not session.get("superadmin_auth"):
            return redirect(url_for("superadmin_login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapped


def device_authorized(tenant):
    """Mutfak/saha cihazlari: panel oturumu VEYA gizli cihaz anahtari (?k=)."""
    if tenant["slug"] in session.get("tenant_auth_slugs", []):
        return True
    k = request.args.get("k", "") or request.headers.get("X-Device-Key", "")
    tok = tenant.get("access_token") or ""
    return bool(k and tok and hmac.compare_digest(k.encode("utf-8"), tok.encode("utf-8")))


def device_tenant(slug, module_check=None):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)
    if not device_authorized(tenant) or not tenant_usable(tenant):
        abort(403)
    if module_check and not module_check(tenant):
        abort(403)
    return tenant


def render_pending(tenant, notified=False):
    mod_type = tenant.get("module_type") or "b2b-ticaret"
    return render_template(
        "tenant_pending.html",
        tenant=tenant,
        mod_label=MODULE_LABELS.get(mod_type, MODULE_LABELS["b2b-ticaret"]),
        notified=notified or request.args.get("notified") == "1",
        iban_holder=IBAN_HOLDER, iban_bank=IBAN_BANK, iban_number=IBAN_NUMBER,
        price_starter=PLAN_PRICE_STARTER, price_pro=PLAN_PRICE_PRO, wa_number=WHATSAPP_NUMBER,
    )


def back_to_panel(slug, msg="", tab=""):
    kw = {}
    if msg:
        kw["bot_saved"] = msg
    if tab:
        kw["tab"] = tab
    return redirect(url_for("tenant_panel", slug=slug, **kw))


def login_session(slug):
    authed = set(session.get("tenant_auth_slugs", []))
    authed.add(slug)
    session["tenant_auth_slugs"] = list(authed)
    session.setdefault("tenant_role", "owner")
    session.permanent = True


# ---------------------------------------------------------------------------
# B2B Kurumsal Siparis & Cari Endpointleri
# ---------------------------------------------------------------------------
@app.get("/api/tenant/<slug>/b2b/summary")
@tenant_panel_required
def api_b2b_summary(slug):
    return jsonify({"ok": True, "b2b": get_b2b_summary(g.tenant)})


@app.post("/api/tenant/<slug>/b2b/profile")
@tenant_panel_required
def api_b2b_update_profile(slug):
    data = request.get_json(silent=True) or request.form
    tid = g.tenant["id"]
    legal_name = clean_text(str(data.get("company_legal_name") or ""), 160)
    tax_office = clean_text(str(data.get("tax_office") or ""), 100)
    tax_number = clean_text(str(data.get("tax_number") or ""), 40)
    b2b_tier = (data.get("b2b_tier") or g.tenant.get("b2b_tier") or "standard").strip().lower()
    if b2b_tier not in VALID_B2B_TIERS:
        b2b_tier = "standard"
    try:
        credit_limit = _money(max(0.0, float(data.get("credit_limit", g.tenant.get("credit_limit") or 50000))))
        term_days = max(0, min(365, int(data.get("payment_term_days", g.tenant.get("payment_term_days") or 30))))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Gecersiz cari limit veya vade degeri."}), 400

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tenants
                   SET company_legal_name = %s,
                       tax_office = %s,
                       tax_number = %s,
                       b2b_tier = %s,
                       credit_limit = %s,
                       payment_term_days = %s
                 WHERE id = %s;
                """,
                (legal_name, tax_office, tax_number, b2b_tier, credit_limit, term_days, tid),
            )
    updated_tenant = get_tenant_by_id(tid)
    return jsonify({"ok": True, "b2b": get_b2b_summary(updated_tenant)})


@app.post("/api/tenant/<slug>/b2b/orders")
@tenant_panel_required
def api_b2b_create_order(slug):
    data = request.get_json(silent=True) or request.form
    tid = g.tenant["id"]
    item_summary = clean_text(str(data.get("item_summary") or ""), 240)
    note = clean_text(str(data.get("note") or ""), 300)
    if not item_summary:
        return jsonify({"ok": False, "error": "Toptan siparis kalemi / aciklamasi zorunludur."}), 400

    try:
        qty = max(1, min(100000, int(data.get("quantity") or 1)))
        unit_price = _money(max(0.01, float(data.get("unit_price") or 0)))
        raw_disc = data.get("discount_rate")
        if raw_disc is None or str(raw_disc).strip() == "":
            disc_rate = tier_default_discount(g.tenant.get("b2b_tier") or "standard")
        else:
            disc_rate = _money(max(0.0, min(90.0, float(raw_disc))))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Adet, birim fiyat veya iskonto gecersiz."}), 400

    gross = _money(unit_price * Decimal(qty))
    discount_amt = _money(gross * (disc_rate / Decimal("100")))
    total_amount = _money(gross - discount_amt)

    summary_now = get_b2b_summary(g.tenant)
    avail = _money(summary_now["available_credit"])
    if total_amount > avail:
        return jsonify({
            "ok": False,
            "error": f"Cari limit yetersiz. Siparis tutari: {total_amount:.2f} TL, Kullanilabilir limit: {avail:.2f} TL",
        }), 400

    order_code = f"B2B-{uuid.uuid4().hex[:8].upper()}"
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO b2b_orders
                    (tenant_id, order_code, item_summary, quantity, unit_price, discount_rate, total_amount, status, note)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'approved', %s)
                RETURNING id, order_code, item_summary, quantity, unit_price, discount_rate, total_amount, status, note, created_at;
                """,
                (tid, order_code, item_summary, qty, unit_price, disc_rate, total_amount, note),
            )
            order_row = dict(cur.fetchone())
            order_row["unit_price"] = float(order_row["unit_price"])
            order_row["discount_rate"] = float(order_row["discount_rate"])
            order_row["total_amount"] = float(order_row["total_amount"])
            order_row["created_at"] = order_row["created_at"].isoformat() if order_row.get("created_at") else ""

            cur.execute(
                """
                INSERT INTO b2b_ledger (tenant_id, entry_type, amount, description, ref_order_code)
                VALUES (%s, 'debit', %s, %s, %s);
                """,
                (tid, total_amount, f"Toptan Sipariş Borcu ({qty}x {item_summary})", order_code),
            )

    updated_tenant = get_tenant_by_id(tid)
    return jsonify({"ok": True, "order": order_row, "b2b": get_b2b_summary(updated_tenant)})


@app.post("/api/tenant/<slug>/b2b/ledger/payment")
@tenant_panel_required
def api_b2b_record_payment(slug):
    data = request.get_json(silent=True) or request.form
    tid = g.tenant["id"]
    desc = clean_text(str(data.get("description") or "Cari Tahsilat / Ödeme"), 240)
    ref_code = clean_text(str(data.get("ref_order_code") or ""), 32)
    try:
        amount = _money(float(data.get("amount") or 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Gecersiz tahsilat tutari."}), 400
    if amount <= Decimal("0.00"):
        return jsonify({"ok": False, "error": "Tahsilat tutari sifirdan buyuk olmalidir."}), 400

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO b2b_ledger (tenant_id, entry_type, amount, description, ref_order_code)
                VALUES (%s, 'credit', %s, %s, %s);
                """,
                (tid, amount, desc or "Cari Tahsilat", ref_code),
            )
    updated_tenant = get_tenant_by_id(tid)
    return jsonify({"ok": True, "b2b": get_b2b_summary(updated_tenant)})


@app.post("/api/tenant/<slug>/b2b/orders/<int:order_id>/status")
@tenant_panel_required
def api_b2b_update_order_status(slug, order_id):
    data = request.get_json(silent=True) or request.form
    new_status = (data.get("status") or "").strip().lower()
    if new_status not in VALID_B2B_ORDER_STATUSES:
        return jsonify({"ok": False, "error": "Gecersiz B2B siparis durumu."}), 400

    tid = g.tenant["id"]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, order_code, total_amount, status
                  FROM b2b_orders
                 WHERE id = %s AND tenant_id = %s
                 FOR UPDATE;
                """,
                (order_id, tid),
            )
            order = cur.fetchone()
            if not order:
                return jsonify({"ok": False, "error": "B2B siparis bulunamadi."}), 404

            old_status = (order.get("status") or "").lower()
            amt = _money(order.get("total_amount") or 0)
            ocode = order["order_code"]

            cur.execute(
                "UPDATE b2b_orders SET status = %s WHERE id = %s AND tenant_id = %s;",
                (new_status, order_id, tid),
            )
            if new_status == "cancelled" and old_status != "cancelled" and amt > Decimal("0.00"):
                cur.execute(
                    """
                    INSERT INTO b2b_ledger (tenant_id, entry_type, amount, description, ref_order_code)
                    VALUES (%s, 'credit', %s, %s, %s);
                    """,
                    (tid, amt, f"İptal Sipariş İadesi ({ocode})", ocode),
                )

    updated_tenant = get_tenant_by_id(tid)
    return jsonify({"ok": True, "order_id": order_id, "status": new_status, "b2b": get_b2b_summary(updated_tenant)})


# ---------------------------------------------------------------------------
# Faz 4 Yardimcilari: Rezervasyon Saat/Kapasite Cakisma, Check-in & Webhook Log
# ---------------------------------------------------------------------------
def _parse_slot_window(date_str: str, time_str: str, duration_minutes: int = 90):
    dt_start = datetime.strptime(f"{date_str.strip()} {time_str.strip()}", "%Y-%m-%d %H:%M")
    dur = max(15, min(int(duration_minutes or 90), 480))
    return dt_start, dt_start + timedelta(minutes=dur)


def _intervals_overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and end_a > start_b


@app.post("/api/tenant/<slug>/reservations/check-availability")
@tenant_panel_required
def api_check_reservation_availability(slug):
    """Tarih, saat, süre ve kişi sayısına göre kapasitesi yeten ve çakışmayan masaları döner."""
    data = request.get_json(silent=True) or request.form
    date_str = (data.get("date") or "").strip()
    time_str = (data.get("time") or "").strip()
    party_size = max(1, int(data.get("party_size") or 2))
    duration_minutes = int(data.get("duration_minutes") or 90)

    try:
        req_start, req_end = _parse_slot_window(date_str, time_str, duration_minutes)
    except ValueError:
        return jsonify({"ok": False, "error": "Gecerli tarih (YYYY-MM-DD) ve saat (HH:MM) giriniz."}), 400

    tid = g.tenant["id"]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, capacity, status
                  FROM dining_tables
                 WHERE tenant_id = %s AND capacity >= %s
                 ORDER BY capacity ASC, id ASC;
                """,
                (tid, party_size),
            )
            candidate_tables = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT res_date, slot, table_no, duration_minutes
                  FROM reservations
                 WHERE tenant_id = %s AND kind = 'table' AND is_active
                   AND COALESCE(res_status, 'confirmed') NOT IN ('cancelled', 'no_show');
                """,
                (tid,),
            )
            busy_table_nos = set()
            for r in cur.fetchall():
                r_date = r["res_date"].isoformat() if hasattr(r["res_date"], "isoformat") else str(r["res_date"] or "")
                r_slot = str(r.get("slot") or "").strip()
                r_tno = r.get("table_no")
                r_dur = int(r.get("duration_minutes") or 90)
                if not r_date or not r_slot or r_tno is None:
                    continue
                try:
                    ex_start, ex_end = _parse_slot_window(r_date, r_slot, r_dur)
                except ValueError:
                    continue
                if _intervals_overlap(req_start, req_end, ex_start, ex_end):
                    busy_table_nos.add(int(r_tno))

            available_tables = []
            for t in candidate_tables:
                m = re.search(r"(\d+)", str(t.get("table_name") or ""))
                t_num = int(m.group(1)) if m else None
                if t_num is None or t_num not in busy_table_nos:
                    available_tables.append(t)

            return jsonify({
                "ok": True,
                "date": date_str,
                "time": time_str,
                "party_size": party_size,
                "available_tables": available_tables,
                "recommended_table": available_tables[0]["table_name"] if available_tables else None,
            })


@app.post("/api/tenant/<slug>/reservations/<int:res_id>/status")
@tenant_panel_required
def api_update_reservation_status(slug, res_id):
    """Rezervasyon durumunu ('pending', 'confirmed', 'checked_in', 'no_show', 'cancelled') günceller."""
    data = request.get_json(silent=True) or request.form
    new_status = (data.get("status") or "").strip().lower()
    if new_status not in VALID_RES_STATUSES:
        return jsonify({"ok": False, "error": "Gecersiz rezervasyon durumu."}), 400

    tid = g.tenant["id"]
    is_active = new_status not in {"cancelled", "no_show"}
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE reservations
                   SET res_status = %s, is_active = %s
                 WHERE id = %s AND tenant_id = %s
                RETURNING id, ticket_id, res_date, slot, table_no, res_status, is_active;
                """,
                (new_status, is_active, res_id, tid),
            )
            updated = cur.fetchone()
            if not updated:
                return jsonify({"ok": False, "error": "Rezervasyon bulunamadi."}), 404

            table_no = updated.get("table_no")
            if table_no is not None:
                table_name = f"Masa {int(table_no)}"
                if new_status == "checked_in":
                    cur.execute(
                        """
                        UPDATE dining_tables
                           SET status = 'occupied', updated_at = CURRENT_TIMESTAMP
                         WHERE tenant_id = %s AND table_name = %s;
                        """,
                        (tid, table_name),
                    )
                elif new_status in {"cancelled", "no_show"}:
                    cur.execute(
                        """
                        UPDATE dining_tables
                           SET status = CASE WHEN status = 'reserved' THEN 'empty' ELSE status END,
                               updated_at = CURRENT_TIMESTAMP
                         WHERE tenant_id = %s AND table_name = %s;
                        """,
                        (tid, table_name),
                    )

            row_dict = dict(updated)
            if hasattr(row_dict.get("res_date"), "isoformat"):
                row_dict["res_date"] = row_dict["res_date"].isoformat()
            return jsonify({"ok": True, "reservation": row_dict})


@app.post("/api/tenant/<slug>/staff/add")
@tenant_panel_required
def api_add_staff_member(slug):
    """PIN tabanlı personel (manager, cashier, waiter) tanımlar."""
    role_curr = (session.get("tenant_role") or "owner").lower()
    if role_curr not in {"owner", "manager"}:
        return jsonify({"ok": False, "error": "Personel ekleme yetkiniz yok."}), 403

    data = request.get_json(silent=True) or request.form
    staff_name = clean_text(str(data.get("staff_name") or ""), 120)
    role = (data.get("role") or "cashier").strip().lower()
    pin_code = (data.get("pin_code") or "").strip()

    if role not in {"manager", "cashier", "waiter"}:
        return jsonify({"ok": False, "error": "Gecersiz personel rolu."}), 400
    if not staff_name or len(pin_code) < 4:
        return jsonify({"ok": False, "error": "Personel adi ve en az 4 haneli PIN zorunludur."}), 400

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tenant_staff (tenant_id, staff_name, role, pin_hash, is_active)
                VALUES (%s, %s, %s, %s, TRUE)
                RETURNING id, staff_name, role, is_active, created_at;
                """,
                (g.tenant["id"], staff_name, role, hash_pin(pin_code)),
            )
            row = dict(cur.fetchone())
            if hasattr(row.get("created_at"), "isoformat"):
                row["created_at"] = row["created_at"].isoformat()
            return jsonify({"ok": True, "staff": row})


@app.post("/api/tenant/<slug>/staff/pin-login")
@tenant_panel_required
def api_staff_pin_login(slug):
    """PIN doğrulayarak aktif oturumun rolünü (manager/cashier/waiter) değiştirir."""
    data = request.get_json(silent=True) or request.form
    pin_code = (data.get("pin_code") or "").strip()
    if not pin_code:
        return jsonify({"ok": False, "error": "PIN kodu giriniz."}), 400

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, staff_name, role
                  FROM tenant_staff
                 WHERE tenant_id = %s AND pin_hash = %s AND is_active = TRUE
                 LIMIT 1;
                """,
                (g.tenant["id"], hash_pin(pin_code)),
            )
            staff = cur.fetchone()
            if not staff:
                return jsonify({"ok": False, "error": "Hatali PIN kodu."}), 401

            session["tenant_role"] = staff["role"]
            session["tenant_staff_name"] = staff["staff_name"]
            return jsonify({
                "ok": True,
                "staff_name": staff["staff_name"],
                "role": staff["role"],
            })


@app.get("/api/tenant/<slug>/webhooks/logs")
@tenant_panel_required
def api_list_webhook_logs(slug):
    """Kiracının son webhook çağrı loglarını listeler."""
    limit = max(1, min(int(request.args.get("limit") or 30), 100))
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, event_name, target_url, status_code, success, response_snippet, attempt_count, created_at
                  FROM webhook_logs
                 WHERE tenant_id = %s
                 ORDER BY id DESC
                 LIMIT %s;
                """,
                (g.tenant["id"], limit),
            )
            logs = []
            for r in cur.fetchall():
                d = dict(r)
                if hasattr(d.get("created_at"), "isoformat"):
                    d["created_at"] = d["created_at"].isoformat()
                logs.append(d)
            return jsonify({"ok": True, "logs": logs})


@app.post("/api/tenant/<slug>/webhooks/logs/<int:log_id>/retry")
@tenant_panel_required
def api_retry_webhook_log(slug, log_id):
    """Önceki bir webhook kaydını SSRF korumalı olarak aynı payload ile yeniden tetikler."""
    tid = g.tenant["id"]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_name, target_url, payload_json, attempt_count
                  FROM webhook_logs
                 WHERE id = %s AND tenant_id = %s;
                """,
                (log_id, tid),
            )
            orig = cur.fetchone()
            if not orig:
                return jsonify({"ok": False, "error": "Webhook kaydi bulunamadi."}), 404

    payload_data = orig["payload_json"]
    if isinstance(payload_data, str):
        payload_data = json.loads(payload_data or "{}")

    next_attempt = int(orig.get("attempt_count") or 1) + 1
    cfg = {"webhook_url": orig["target_url"]}
    ok, info = send_webhook(
        cfg,
        payload_data or {},
        tenant_id=tid,
        event_name=orig["event_name"],
        attempt_count=next_attempt,
    )
    return jsonify({"ok": True, "sent_ok": ok, "info": info, "attempt_count": next_attempt})


# ---------------------------------------------------------------------------
# Genel / gorseller
# ---------------------------------------------------------------------------
@app.route("/healthz")
def healthz():
    return "ok", 200


@app.route("/cron/daily-reports")
def cron_daily_reports():
    key = request.args.get("key", "")
    if not CRON_SECRET or not hmac.compare_digest(key.encode("utf-8"), CRON_SECRET.encode("utf-8")):
        abort(404)
    return jsonify({"ok": True, "sent": run_due_reports()})


def _img_response(data, ext):
    resp = Response(data, mimetype=IMG_MIME[ext])
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/logo.png")
def serve_root_logo():
    for candidate in (IMAGES_DIR / "logo.png", BASE_DIR / "logo.png"):
        if candidate.exists() and candidate.is_file():
            return send_from_directory(candidate.parent, candidate.name)
    abort(404)


def _serve_tenant_image(tenant_id, category, folder, filename):
    safe_name = Path(filename).name
    ext = Path(safe_name).suffix.lower()
    if ext not in IMG_MIME:
        abort(404)
    stored = get_stored_image_from_db(tenant_id, category, safe_name)
    if stored:
        return _img_response(bytes(stored["data"]), ext)
    target_dir = folder / str(tenant_id)
    if (target_dir / safe_name).is_file():
        return send_from_directory(target_dir, safe_name)
    abort(404)


@app.route("/images/logos/<int:tenant_id>/<path:filename>")
def serve_tenant_logo(tenant_id, filename):
    return _serve_tenant_image(tenant_id, "logos", LOGO_IMAGES_DIR, filename)


@app.route("/images/menu/<int:tenant_id>/<path:filename>")
def serve_menu_image(tenant_id, filename):
    return _serve_tenant_image(tenant_id, "menu", MENU_IMAGES_DIR, filename)


@app.route("/images/<path:filename>")
def serve_image(filename):
    if not IMAGES_DIR.exists():
        abort(404)
    if Path(filename).suffix.lower() in ALLOWED_IMG_EXTS and (IMAGES_DIR / filename).is_file():
        return send_from_directory(IMAGES_DIR, filename)
    stem = Path(filename).stem
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = IMAGES_DIR / f"{stem}{ext}"
        if candidate.is_file():
            return send_from_directory(IMAGES_DIR, candidate.name)
    abort(404)


@app.route("/", methods=["GET"])
def index():
    created_slug = request.args.get("created", "").strip()
    created_tenant = None
    if created_slug and created_slug in session.get("tenant_auth_slugs", []):
        created_tenant = get_tenant_by_slug(created_slug)
    return render_template(
        "index.html",
        services=SERVICES_DATA, wa_number=WHATSAPP_NUMBER,
        iban_holder=IBAN_HOLDER, iban_bank=IBAN_BANK, iban_number=IBAN_NUMBER,
        price_starter=PLAN_PRICE_STARTER, price_pro=PLAN_PRICE_PRO, qr_addon_price=QR_ADDON_PRICE,
        created_tenant=created_tenant, saas_error=request.args.get("err", "").strip()[:200] or None,
    )


# ---------------------------------------------------------------------------
# Kayit / giris (B2B Kurumsal Uyelik)
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.route("/saas/register", methods=["POST"])
def register_tenant():
    if rate_limited(f"reg:{request.remote_addr}", 5, 3600):
        abort(429)
    business_name = clean_text(request.form.get("business_name"), 120)
    raw_slug = clean_text(request.form.get("slug"), 60)
    owner_email = clean_text(request.form.get("owner_email"), 160)
    whatsapp_number = clean_text(request.form.get("whatsapp_number"), 30)
    company_legal_name = clean_text(request.form.get("company_legal_name") or business_name, 160)
    tax_office = clean_text(request.form.get("tax_office"), 100)
    tax_number = clean_text(request.form.get("tax_number"), 40)
    b2b_tier = request.form.get("b2b_tier", "standard").strip().lower()
    password = request.form.get("password", "").strip()
    plan = request.form.get("plan", "starter").strip()
    module_type = request.form.get("module_type", "b2b-ticaret").strip()

    try:
        credit_limit = float(request.form.get("credit_limit") or 50000)
        payment_term_days = int(request.form.get("payment_term_days") or 30)
    except ValueError:
        credit_limit = 50000.0
        payment_term_days = 30

    if not business_name or not _EMAIL_RE.match(owner_email) or len(password) < 8:
        return redirect(url_for("index", err="Kurumsal ünvan/işletme adı, geçerli e-posta ve en az 8 karakter şifre zorunlu.") + "#saas-basla")
    try:
        tenant = create_tenant(
            business_name,
            owner_email,
            password,
            raw_slug=raw_slug,
            plan=plan,
            module_type=module_type,
            whatsapp_number=whatsapp_number,
            company_legal_name=company_legal_name,
            tax_office=tax_office,
            tax_number=tax_number,
            b2b_tier=b2b_tier,
            credit_limit=credit_limit,
            payment_term_days=payment_term_days,
        )
    except Exception as exc:
        app.logger.error("Kayit hatasi: %s", exc)
        return redirect(url_for("index", err="Kayıt sırasında bir hata oluştu, lütfen tekrar deneyin.") + "#saas-basla")
    login_session(tenant["slug"])
    return redirect(url_for("index", created=tenant["slug"]) + "#saas-basla")


@app.route("/saas/login", methods=["POST"])
def tenant_quick_login():
    slug = slugify(request.form.get("slug", "").strip())
    if rate_limited(f"ql:{request.remote_addr}", 10, 600):
        abort(429)
    password = request.form.get("password", "").strip()
    tenant = get_tenant_by_slug(slug)
    if tenant and check_password_hash(tenant["password_hash"], password):
        login_session(tenant["slug"])
        return redirect(url_for("tenant_panel", slug=tenant["slug"]))
    return redirect(url_for("index", err="Kurumsal slug veya şifre hatalı.") + "#saas-basla")


@app.route("/i/<slug>/login", methods=["GET", "POST"])
def tenant_login(slug):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)
    fallback = url_for("tenant_panel", slug=slug)
    next_url = safe_next(request.args.get("next"), fallback)
    error = None
    if request.method == "POST":
        if rate_limited(f"tl:{request.remote_addr}:{slug}", 8, 600):
            abort(429)
        if check_password_hash(tenant["password_hash"], request.form.get("password", "").strip()):
            login_session(slug)
            return redirect(safe_next(request.form.get("next"), next_url))
        error = "Şifre hatalı."
    return render_template("tenant_login.html", tenant=tenant, error=error)


@app.route("/i/<slug>/logout", methods=["POST"])
def tenant_logout(slug):
    authed = set(session.get("tenant_auth_slugs", []))
    authed.discard(slug)
    session["tenant_auth_slugs"] = list(authed)
    return redirect(url_for("tenant_login", slug=slug))


@app.route("/i/<slug>/odeme-bildir", methods=["POST"])
def notify_iban_payment(slug):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)
    if rate_limited(f"pay:{request.remote_addr}", 10, 3600):
        abort(429)
    note = clean_text(request.form.get("payment_note"), 240)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET payment_requested = TRUE, payment_note = %s WHERE id = %s", (note, tenant["id"]))
    return redirect(url_for("tenant_public", slug=slug, notified="1"))


# ---------------------------------------------------------------------------
# Mutfak ekrani (KDS)
# ---------------------------------------------------------------------------
@app.route("/i/<slug>/mutfak", methods=["GET"])
def kitchen_kds_screen(slug):
    tenant = device_tenant(slug, tenant_has_qr_access)
    active_orders = load_tickets(tenant["id"], limit=100, statuses=["Yeni", "İnceleniyor"])
    return render_template(
        "kitchen_kds.html", tenant=tenant, active_orders=active_orders,
        k=request.args.get("k", ""),
        latest_id=active_orders[0]["id"] if active_orders else "",
    )


@app.route("/i/<slug>/mutfak/poll", methods=["GET"])
def kds_poll(slug):
    tenant = device_tenant(slug, tenant_has_qr_access)
    st = ticket_stats(tenant["id"])
    return jsonify({"active_count": st["active"], "latest_id": st["latest_active_id"]})


@app.route("/i/<slug>/mutfak/update/<ticket_id>", methods=["POST"])
def kds_update_order(slug, ticket_id):
    tenant = device_tenant(slug, tenant_has_qr_access)
    new_status = request.form.get("status", "Tamamlandı").strip()
    if new_status not in TICKET_STATUSES:
        new_status = "Tamamlandı"
    update_ticket_status(tenant["id"], ticket_id, new_status)
    return redirect(url_for("kitchen_kds_screen", slug=slug, k=request.args.get("k", "")))


# ---------------------------------------------------------------------------
# Saha ekibi
# ---------------------------------------------------------------------------
def _is_saha(tenant):
    return (tenant.get("module_type") or "") == "mobil-saha"


@app.route("/i/<slug>/saha", methods=["GET"])
def field_agent_terminal(slug):
    tenant = device_tenant(slug, _is_saha)
    return render_template("field_agent.html", tenant=tenant, k=request.args.get("k", ""))


@app.route("/i/<slug>/saha/ping", methods=["POST"])
def field_agent_ping(slug):
    tenant = get_tenant_by_slug(slug)
    if not tenant or not device_authorized(tenant) or not tenant_usable(tenant) or not _is_saha(tenant):
        return jsonify({"ok": False}), 403
    if rate_limited(f"ping:{request.remote_addr}:{slug}", 60, 60):
        return jsonify({"ok": False}), 429
    data = request.get_json(silent=True) or {}
    agent_name = clean_text(str(data.get("agent_name") or ""), 80)
    if not agent_name:
        return jsonify({"ok": False, "err": "agent_name required"}), 400

    active_package = clean_text(str(data.get("active_package") or ""), 140)
    target_customer = clean_text(str(data.get("target_customer") or ""), 160)
    status_text = clean_text(str(data.get("status_text") or "Sahada Aktif"), 80)
    try:
        battery_level = max(-1, min(100, int(data.get("battery_level", -1))))
    except (TypeError, ValueError):
        battery_level = -1
    is_charging = bool(data.get("is_charging", False))

    def coord(v, lo, hi):
        try:
            f = float(v)
            return f"{f:.6f}" if lo <= f <= hi else ""
        except (TypeError, ValueError):
            return ""

    lat, lng = coord(data.get("latitude"), -90, 90), coord(data.get("longitude"), -180, 180)
    now = now_tr()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM field_agents WHERE tenant_id = %s AND LOWER(agent_name) = LOWER(%s)",
                (tenant["id"], agent_name),
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """UPDATE field_agents SET active_package=%s, target_customer=%s, battery_level=%s, is_charging=%s,
                       latitude=%s, longitude=%s, status_text=%s, updated_at=%s WHERE id=%s""",
                    (
                        active_package, target_customer, battery_level, is_charging,
                        lat, lng, status_text, now, existing["id"],
                    ),
                )
            else:
                cur.execute(
                    """INSERT INTO field_agents (tenant_id, agent_name, active_package, target_customer,
                       battery_level, is_charging, latitude, longitude, status_text, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        tenant["id"], agent_name, active_package, target_customer,
                        battery_level, is_charging, lat, lng, status_text, now,
                    ),
                )
    return jsonify({"ok": True})


@app.route("/i/<slug>/panel/saha/data")
@tenant_panel_required
def panel_saha_data(slug):
    return jsonify({"agents": get_field_agents(g.tenant["id"])})


@app.route("/i/<slug>/panel/saha/<int:agent_id>/delete", methods=["POST"])
@tenant_panel_required
def panel_saha_delete(slug, agent_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM field_agents WHERE id = %s AND tenant_id = %s", (agent_id, g.tenant["id"]))
    return back_to_panel(slug, "Saha elemanı kaydı silindi.", "pane-saha")


# ---------------------------------------------------------------------------
# Musteri tarafi: Masa QR
# ---------------------------------------------------------------------------
def sanitize_masa(raw, cap):
    m = re.fullmatch(r"Masa (\d{1,3})", (raw or "").strip())
    if m and 1 <= int(m.group(1)) <= cap:
        return f"Masa {int(m.group(1))}"
    return ""


def build_order_summary(cart_json, menu_items):
    try:
        cart = json.loads(cart_json or "{}")
        if not isinstance(cart, dict):
            return ""
    except ValueError:
        return ""
    by_id = {str(i["id"]): i for i in menu_items}
    lines, total = [], 0.0
    for key, qty in cart.items():
        try:
            qty = max(0, min(50, int(qty)))
        except (TypeError, ValueError):
            continue
        item = by_id.get(str(key))
        if item and qty:
            lines.append(f"{qty}x {item['name']}" + (f" ({item['price']})" if item["price"] else ""))
            total += qty * item["numeric_price"]
    summary = ", ".join(lines)
    if summary and total > 0:
        summary += f" | Toplam: {total:.0f} TL"
    return summary


@app.route("/i/<slug>/qr", methods=["GET", "POST"])
def tenant_qr_order_page(slug):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)
    if not tenant_usable(tenant):
        return render_pending(tenant)
    if not tenant_has_qr_access(tenant):
        abort(403)

    cap = max(1, int(tenant.get("table_count") or 8))
    preselected_masa = sanitize_masa(request.args.get("masa"), cap)
    menu_items = get_menu_items(tenant["id"])

    if request.method == "POST":
        if rate_limited(f"qr:{request.remote_addr}:{slug}", 40, 600):
            abort(429)
        action_type = request.form.get("action_type", "siparis").strip()
        masa_name = sanitize_masa(request.form.get("masa_name"), cap) or preselected_masa or "Masa 1"

        if action_type in ("garson", "hesap"):
            service = "🔔 Garson Çağır" if action_type == "garson" else "💳 Hesap İste"
            text = f"{masa_name} garson çağırıyor." if action_type == "garson" else f"{masa_name} hesap istiyor."
            if not recent_duplicate(tenant["id"], masa_name, service, 60):
                add_ticket(tenant, masa_name, "", service, text)
            return redirect(url_for("tenant_qr_order_page", slug=slug, masa=masa_name, sent="1", stype=action_type))

        parts = []
        summary = build_order_summary(request.form.get("cart_json"), menu_items)
        if summary:
            parts.append(summary)
        note = clean_text(request.form.get("message"), 400)
        if note:
            parts.append(f"Not: {note}")
        if parts:
            add_ticket(tenant, masa_name, "", "🍽️ QR Masa Siparişi", " | ".join(parts))
        return redirect(url_for("tenant_qr_order_page", slug=slug, masa=masa_name, sent="1", stype="siparis"))

    sent_msg = ""
    if request.args.get("sent") == "1":
        label = preselected_masa or "Masanız"
        stype = request.args.get("stype", "")
        if stype == "garson":
            sent_msg = f"🔔 {label} için garson çağrısı iletildi, hemen ilgileniyoruz!"
        elif stype == "hesap":
            sent_msg = f"💳 {label} için hesap isteği iletildi!"
        else:
            sent_msg = f"🍽️ {label} için siparişiniz alındı ve hazırlanmaya başlandı!"

    return render_template(
        "tenant_qr_order.html", tenant=tenant, menu_items=menu_items,
        preselected_masa=preselected_masa, sent=bool(sent_msg), sent_msg=sent_msg,
    )


# ---------------------------------------------------------------------------
# Musteri tarafi: ana sayfa (randevu / talep / B2B talep)
# ---------------------------------------------------------------------------
ERR_MESSAGES = {
    "taken": "Seçtiğiniz masa/saat az önce doldu. Lütfen başka bir seçim yapın.",
    "invalid": "Bilgiler eksik veya geçersiz. Ad, telefon, tarih ve saati kontrol edin.",
    "rate": "Çok fazla deneme yaptınız. Lütfen birkaç dakika sonra tekrar deneyin.",
}


@app.route("/i/<slug>", methods=["GET", "POST"])
def tenant_public(slug):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)
    mod_type = tenant.get("module_type") or "b2b-ticaret"
    mod_label = MODULE_LABELS.get(mod_type, MODULE_LABELS["b2b-ticaret"])

    if not tenant_usable(tenant):
        return render_pending(tenant)

    if mod_type == "masa-qr":
        masa_param = request.args.get("masa", "").strip()
        return redirect(
            url_for("tenant_qr_order_page", slug=slug, masa=masa_param)
            if masa_param else url_for("tenant_qr_order_page", slug=slug)
        )

    today = today_tr()
    max_date = today + timedelta(days=90)
    selected = parse_date(request.args.get("date")) or today
    if selected < today or selected > max_date:
        selected = today
    table_cap = max(1, int(tenant.get("table_count") or 8))

    if request.method == "POST":
        def fail(code):
            return redirect(url_for("tenant_public", slug=slug, date=selected.isoformat(), err=code))

        if rate_limited(f"pub:{request.remote_addr}:{slug}", 12, 600):
            return fail("rate")
        name = clean_text(request.form.get("name"), 80)
        phone = clean_text(request.form.get("phone"), 30)
        raw_service = clean_text(request.form.get("service"), 100)
        raw_message = clean_text(request.form.get("message"), 500)
        if not name or len(re.sub(r"\D", "", phone)) < 10:
            return fail("invalid")

        reservation, service = None, raw_service or ("B2B Kurumsal Talep" if mod_type == "b2b-ticaret" else "Genel Talep")
        if mod_type in ("kafe-randevu", "berber-randevu"):
            res_date = parse_date(request.form.get("res_date"))
            slot_time = request.form.get("slot_time", "").strip()
            if (
                not res_date or res_date < today or res_date > max_date
                or slot_time not in TIME_SLOTS or slot_time in past_slots_for(res_date)
            ):
                return fail("invalid")
            selected = res_date

            if mod_type == "kafe-randevu":
                table_label = sanitize_masa(request.form.get("table_no"), table_cap)
                if not table_label:
                    return fail("invalid")
                table_no = int(table_label.split()[1])
                guest_count = clean_text(request.form.get("guest_count"), 40)
                menu_pick = [clean_text(m, 120) for m in request.form.getlist("menu_order")[:30] if m.strip()]
                service = f"Randevu {res_date.isoformat()} {slot_time} — {table_label}"
                parts = [f"Tarih/Saat: {res_date.isoformat()} {slot_time}", f"Masa: {table_label}"]
                if guest_count:
                    parts.append(f"Kişi: {guest_count}")
                if menu_pick:
                    parts.append(f"Menü Seçimi: {', '.join(menu_pick)}")
                if raw_message:
                    parts.append(f"Not: {raw_message}")
                message = " | ".join(parts)
                reservation = {"kind": "table", "res_date": res_date, "slot": slot_time, "table_no": table_no}
            else:
                service = f"{raw_service or 'Salon Randevu'} ({res_date.isoformat()} {slot_time})"
                parts = [f"Tarih: {res_date.isoformat()}", f"Saat: {slot_time}"]
                if raw_message:
                    parts.append(f"Not: {raw_message}")
                message = " | ".join(parts)
                reservation = {"kind": "barber", "res_date": res_date, "slot": slot_time}
        else:
            message = raw_message
            if not message:
                return fail("invalid")

        try:
            add_ticket(tenant, name, phone, service, message, reservation)
        except SlotTaken:
            return fail("taken")
        return redirect(url_for("tenant_public", slug=slug, date=selected.isoformat(), sent="1"))

    menu_items = get_menu_items(tenant["id"]) if mod_type == "kafe-randevu" else []
    past = past_slots_for(selected)
    slot_options, barber_slots = [], []
    if mod_type == "kafe-randevu":
        booked = get_booked_tables_by_slot(tenant["id"], selected)
        for sl in TIME_SLOTS:
            free = [] if sl in past else [n for n in range(1, table_cap + 1) if n not in booked.get(sl, set())]
            slot_options.append({"time": sl, "free_tables": free, "available_count": len(free)})
    elif mod_type == "berber-randevu":
        taken = get_booked_barber_slots(tenant["id"], selected) | past
        barber_slots = [{"time": sl, "is_free": sl not in taken} for sl in TIME_SLOTS]

    return render_template(
        "tenant_public.html",
        tenant=tenant, services=SERVICES_DATA, mod_label=mod_label,
        selected_date=selected.isoformat(), min_date=today.isoformat(), max_date=max_date.isoformat(),
        slot_options=slot_options, barber_slots=barber_slots, menu_items=menu_items,
        sent=request.args.get("sent") == "1", err_msg=ERR_MESSAGES.get(request.args.get("err", ""), ""),
    )


# ---------------------------------------------------------------------------
# Isletme / B2B paneli
# ---------------------------------------------------------------------------
def build_tenant_qr_list(tenant):
    cap = max(1, int(tenant.get("table_count") or 8))
    base_qr_url = url_for("tenant_qr_order_page", slug=tenant["slug"], _external=True)
    out = []
    for idx in range(1, cap + 1):
        label = f"Masa {idx}"
        target_url = f"{base_qr_url}?masa={quote(label)}"
        if segno is not None:
            img = url_for("tenant_qr_image", slug=tenant["slug"], n=idx)
        else:
            img = f"https://api.qrserver.com/v1/create-qr-code/?size=280x280&margin=6&data={quote(target_url, safe='')}"
        out.append({"num": idx, "label": label, "target_url": target_url, "qr_img_url": img})
    return out


@app.route("/i/<slug>/panel/qr-img/<int:n>.svg")
@tenant_panel_required
def tenant_qr_image(slug, n):
    tenant = g.tenant
    cap = max(1, int(tenant.get("table_count") or 8))
    if segno is None or not tenant_has_qr_access(tenant) or not 1 <= n <= cap:
        abort(404)
    target = url_for("tenant_qr_order_page", slug=slug, _external=True) + f"?masa={quote(f'Masa {n}')}"
    buf = io.BytesIO()
    segno.make(target, error="m").save(buf, kind="svg", scale=8, border=2)
    resp = Response(buf.getvalue(), mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@app.route("/i/<slug>/panel/poll")
@tenant_panel_required
def tenant_panel_poll(slug):
    st = ticket_stats(g.tenant["id"])
    latest, summary = st["latest"], ""
    if latest:
        summary = f"{latest['name']} — {latest.get('service') or 'Talep'}: {latest['message'][:80]}"
    return jsonify({"total": st["total"], "latest_id": latest["id"] if latest else "", "latest_summary": summary})


@app.route("/i/<slug>/panel")
@tenant_login_required
def tenant_panel(slug):
    tenant = g.tenant
    if not tenant_usable(tenant):
        return render_pending(tenant)

    mod_type = tenant.get("module_type") or "b2b-ticaret"
    show_menu_tab = mod_type in {"kafe-randevu", "masa-qr"}
    qr_unlocked = tenant_has_qr_access(tenant)
    tid = tenant["id"]
    tickets = load_tickets(tid, limit=300)
    stats = ticket_stats(tid)
    token = tenant.get("access_token") or ""

    pos_products, pos_total_sold, pos_total_revenue, pos_sales = [], 0, 0.0, []
    if mod_type == "masaustu-otomasyon":
        pos_products, pos_total_sold, pos_total_revenue, pos_sales = get_pos_overview(tid)
    bot_cfg = get_bot_config(tenant) if mod_type == "web-otomasyon" else {}
    b2b_summary = get_b2b_summary(tenant)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, ticket_id, kind, res_date, slot, table_no, res_status, duration_minutes, party_size, is_active
                  FROM reservations
                 WHERE tenant_id = %s
                 ORDER BY res_date DESC, slot DESC, id DESC
                 LIMIT 50;
                """,
                (tid,),
            )
            reservations = [
                dict(r, res_date=r["res_date"].isoformat() if hasattr(r.get("res_date"), "isoformat") else str(r.get("res_date") or ""))
                for r in cur.fetchall()
            ]

    nav_count = 4 if show_menu_tab else (3 if mod_type in {"mobil-saha", "web-otomasyon", "masaustu-otomasyon", "b2b-ticaret"} else 2)
    return render_template(
        "tenant_panel.html",
        tenant=tenant, mod_label=MODULE_LABELS.get(mod_type, MODULE_LABELS["b2b-ticaret"]),
        show_menu_tab=show_menu_tab, qr_unlocked=qr_unlocked, qr_addon_price=QR_ADDON_PRICE,
        iban_holder=IBAN_HOLDER, iban_bank=IBAN_BANK, iban_number=IBAN_NUMBER,
        addon_notified=request.args.get("addon_notified") == "1",
        bot_saved=request.args.get("bot_saved", "")[:300], start_tab=request.args.get("tab", ""),
        selected_date=today_tr().isoformat(),
        reservations=reservations,
        b2b_summary=b2b_summary,
        menu_items=get_menu_items(tid) if show_menu_tab else [],
        qr_list=build_tenant_qr_list(tenant) if (show_menu_tab and qr_unlocked) else [],
        kds_url=url_for("kitchen_kds_screen", slug=slug, k=token, _external=True),
        saha_url=url_for("field_agent_terminal", slug=slug, k=token, _external=True),
        agents=get_field_agents(tid) if mod_type == "mobil-saha" else [],
        bot_cfg=bot_cfg, bot_logs=get_bot_logs(tid) if mod_type == "web-otomasyon" else [],
        pos_products=pos_products, pos_total_sold=pos_total_sold, pos_total_revenue=pos_total_revenue, pos_sales=pos_sales,
        nav_count=nav_count, tickets=tickets, total_count=stats["total"],
        yeni_count=stats["yeni"], tamam_count=stats["tamam"], latest_id=stats["latest"]["id"] if stats["latest"] else "",
    )


@app.route("/i/<slug>/panel/regen-token", methods=["POST"])
@tenant_panel_required
def tenant_regen_token(slug):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET access_token = %s WHERE id = %s", (secrets.token_urlsafe(24), g.tenant["id"]))
    return back_to_panel(slug, "Mutfak/saha erişim anahtarı yenilendi. Eski linkler artık çalışmaz, yeni linkleri cihazlara dağıtın.", "pane-settings")


@app.route("/i/<slug>/panel/qr-addon-request", methods=["POST"])
@tenant_panel_required
def tenant_request_qr_addon(slug):
    note = clean_text(request.form.get("qr_addon_note"), 240)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET qr_addon_requested = TRUE, qr_addon_note = %s WHERE id = %s", (note, g.tenant["id"]))
    return redirect(url_for("tenant_panel", slug=slug, addon_notified="1"))


# --- Bot / API -------------------------------------------------------------
def _require_web_module(tenant):
    if (tenant.get("module_type") or "") != "web-otomasyon":
        abort(403)


@app.route("/i/<slug>/panel/bot-config", methods=["POST"])
@tenant_panel_required
def tenant_save_bot_config(slug):
    tenant = g.tenant
    _require_web_module(tenant)
    old = get_bot_config(tenant)
    warnings = []

    def url_field(name, label):
        val = clean_text(request.form.get(name), 400)
        if val and not is_safe_public_url(val):
            warnings.append(f"{label} geçersiz/erişilemez olduğu için kaydedilmedi")
            return old.get(name, "")
        return val

    def secret_field(name):
        return clean_text(request.form.get(name), 400) or old.get(name, "")

    hour = request.form.get("report_hour", "21:00").strip()
    cfg = {
        "wa_api_url": url_field("wa_api_url", "WhatsApp API URL"),
        "wa_api_token": secret_field("wa_api_token"),
        "wa_template_name": clean_text(request.form.get("wa_template_name"), 80),
        "wa_auto_reply": bool(request.form.get("wa_auto_reply")),
        "tg_bot_token": secret_field("tg_bot_token"),
        "tg_chat_id": clean_text(request.form.get("tg_chat_id"), 60),
        "tg_notify_enabled": bool(request.form.get("tg_notify_enabled")),
        "scraper_url": url_field("scraper_url", "Veri çekme URL"),
        "webhook_url": url_field("webhook_url", "Webhook URL"),
        "report_hour": hour if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hour) else "21:00",
        "last_sync_note": old.get("last_sync_note", ""),
    }
    save_bot_config(tenant["id"], cfg)
    msg = "Bot ve API entegrasyon ayarları kaydedildi."
    if warnings:
        msg = "⚠️ " + "; ".join(warnings) + ". Diğer ayarlar kaydedildi."
    return back_to_panel(slug, msg, "pane-bots")


@app.route("/i/<slug>/panel/bot-action", methods=["POST"])
@tenant_panel_required
def tenant_run_bot_action(slug):
    tenant = g.tenant
    _require_web_module(tenant)
    if rate_limited(f"botact:{tenant['id']}", 10, 300):
        abort(429)
    cfg = get_bot_config(tenant)
    action = request.form.get("bot_action", "").strip()
    stamp = now_tr().strftime("%d.%m.%Y %H:%M:%S")

    if action == "pull_data":
        text = build_daily_report(tenant, cfg)
        bot_log(tenant["id"], "Veri çekme/rapor: " + text.splitlines()[-1][:300])
        results = send_report_to_channels(tenant, cfg, text)
        for ok, info in results:
            bot_log(tenant["id"], f"Rapor gönderimi → {info}", "info" if ok else "error")
        msg = "Rapor hazırlandı ve kanallara gönderildi." if results else "Rapor hazırlandı (bağlı Telegram/Webhook kanalı yok)."
        cfg["last_sync_note"] = f"[{stamp}] {text.splitlines()[-1][:200]}"
    else:
        text = f"✅ {tenant['business_name']} — test bildirimi ({stamp})"
        results = send_report_to_channels(tenant, cfg, text)
        if cfg["wa_api_url"] and cfg["wa_api_token"] and tenant.get("whatsapp_number"):
            results.append(send_whatsapp(cfg, tenant["whatsapp_number"], text))
        if not results:
            msg = "⚠️ Test için Telegram, Webhook veya WhatsApp bilgisi girilmemiş."
        else:
            for ok, info in results:
                bot_log(tenant["id"], f"Test → {info}", "info" if ok else "error")
            msg = "Test sonucu: " + " | ".join(("✔ " if ok else "✖ ") + info for ok, info in results)
        cfg["last_sync_note"] = f"[{stamp}] Test bildirimi gönderildi."
    save_bot_config(tenant["id"], cfg)
    return back_to_panel(slug, msg, "pane-bots")


# --- Kasa / barkod ---------------------------------------------------------
def _require_pos_module(tenant):
    if (tenant.get("module_type") or "") != "masaustu-otomasyon":
        abort(403)


@app.route("/i/<slug>/panel/pos/add", methods=["POST"])
@tenant_panel_required
def tenant_pos_add_product(slug):
    tenant = g.tenant
    _require_pos_module(tenant)
    barcode = clean_text(request.form.get("barcode"), 64)
    name = clean_text(request.form.get("name"), 120)
    try:
        price = round(max(0.0, float(request.form.get("price", 0))), 2)
        stock = max(0, int(request.form.get("stock", 0)))
    except ValueError:
        return back_to_panel(slug, "⚠️ Fiyat/stok geçersiz.", "pane-pos")
    if not barcode or not name or price > 10_000_000:
        return back_to_panel(slug, "⚠️ Barkod ve ürün adı zorunlu.", "pane-pos")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO pos_products (tenant_id, barcode, name, price, stock) VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (tenant_id, barcode)
                   DO UPDATE SET name = EXCLUDED.name, price = EXCLUDED.price, stock = EXCLUDED.stock""",
                (tenant["id"], barcode, name, price, stock),
            )
    return back_to_panel(slug, f"Ürün kaydedildi: {name} ({barcode})", "pane-pos")


@app.route("/i/<slug>/panel/pos/scan", methods=["POST"])
@tenant_panel_required
def tenant_pos_scan(slug):
    tenant = g.tenant
    _require_pos_module(tenant)
    barcode = clean_text(request.form.get("barcode"), 64)
    try:
        qty = max(1, min(500, int(request.form.get("qty", 1))))
    except ValueError:
        qty = 1
    if not barcode:
        return back_to_panel(slug, "⚠️ Barkod boş.", "pane-pos")

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, price, stock FROM pos_products WHERE tenant_id = %s AND barcode = %s FOR UPDATE",
                (tenant["id"], barcode),
            )
            prod = cur.fetchone()
            if not prod:
                msg = f"⚠️ '{barcode}' barkodlu ürün bulunamadı, önce tanımlayın."
            elif prod["stock"] < qty:
                msg = f"⚠️ Yetersiz stok: {prod['name']} (kalan {prod['stock']}, istenen {qty})."
            else:
                cur.execute("UPDATE pos_products SET stock = stock - %s WHERE id = %s", (qty, prod["id"]))
                total = round(float(prod["price"]) * qty, 2)
                cur.execute(
                    """INSERT INTO pos_sales (tenant_id, product_id, barcode, name, qty, unit_price, total, sold_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (tenant["id"], prod["id"], barcode, prod["name"], qty, prod["price"], total, now_tr()),
                )
                msg = f"Satış işlendi: {qty}x {prod['name']} = {total:.2f} TL (kalan stok: {prod['stock'] - qty})"
    return back_to_panel(slug, msg, "pane-pos")


@app.route("/i/<slug>/panel/pos/sale/<int:sale_id>/void", methods=["POST"])
@tenant_panel_required
def tenant_pos_void_sale(slug, sale_id):
    tenant = g.tenant
    _require_pos_module(tenant)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE pos_sales SET voided = TRUE WHERE id = %s AND tenant_id = %s AND NOT voided
                   RETURNING product_id, qty""",
                (sale_id, tenant["id"]),
            )
            row = cur.fetchone()
            if row and row["product_id"]:
                cur.execute("UPDATE pos_products SET stock = stock + %s WHERE id = %s", (row["qty"], row["product_id"]))
    return back_to_panel(slug, "Satış iptal edildi, stok iade edildi." if row else "⚠️ Satış bulunamadı veya zaten iptal.", "pane-pos")


@app.route("/i/<slug>/panel/pos/<int:product_id>/delete", methods=["POST"])
@tenant_panel_required
def tenant_pos_delete_product(slug, product_id):
    _require_pos_module(g.tenant)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pos_products WHERE id = %s AND tenant_id = %s", (product_id, g.tenant["id"]))
    return back_to_panel(slug, "Ürün silindi.", "pane-pos")


# --- QR yazdir / ayarlar / menu / talepler ----------------------------------
@app.route("/i/<slug>/panel/qr-print")
@tenant_panel_required
def tenant_qr_print(slug):
    if not tenant_has_qr_access(g.tenant):
        abort(403)
    return render_template("qr_print.html", tenant=g.tenant, qr_list=build_tenant_qr_list(g.tenant))


@app.route("/i/<slug>/panel/settings", methods=["POST"])
@tenant_panel_required
def tenant_update_settings(slug):
    tenant = g.tenant
    wa_num = clean_text(request.form.get("whatsapp_number"), 30)
    legal_name = clean_text(request.form.get("company_legal_name") or tenant.get("company_legal_name") or tenant.get("business_name"), 160)
    tax_office = clean_text(request.form.get("tax_office") or tenant.get("tax_office"), 100)
    tax_number = clean_text(request.form.get("tax_number") or tenant.get("tax_number"), 40)
    new_logo = save_uploaded_image(LOGO_IMAGES_DIR, tenant["id"], request.files.get("logo"))
    try:
        t_count = int(request.form.get("table_count", tenant.get("table_count") or 8))
    except ValueError:
        t_count = tenant.get("table_count") or 8
    t_count = max(1, min(200, t_count))
    with get_db() as conn:
        with conn.cursor() as cur:
            if new_logo:
                cur.execute(
                    """UPDATE tenants SET whatsapp_number=%s, table_count=%s, logo_filename=%s,
                       company_legal_name=%s, tax_office=%s, tax_number=%s WHERE id=%s""",
                    (wa_num, t_count, new_logo, legal_name, tax_office, tax_number, tenant["id"]),
                )
            else:
                cur.execute(
                    """UPDATE tenants SET whatsapp_number=%s, table_count=%s,
                       company_legal_name=%s, tax_office=%s, tax_number=%s WHERE id=%s""",
                    (wa_num, t_count, legal_name, tax_office, tax_number, tenant["id"]),
                )
    msg = "" if (new_logo or not request.files.get("logo") or not request.files["logo"].filename) else "⚠️ Logo kaydedilmedi: sadece JPG/PNG/WEBP ve en fazla 4 MB."
    return back_to_panel(slug, msg or "Kurumsal ve panel ayarları kaydedildi.", "pane-settings")


def _require_menu_module(tenant):
    if (tenant.get("module_type") or "b2b-ticaret") not in {"kafe-randevu", "masa-qr"}:
        abort(403)


@app.route("/i/<slug>/panel/menu/add", methods=["POST"])
@tenant_panel_required
def tenant_add_menu_item(slug):
    tenant = g.tenant
    _require_menu_module(tenant)
    name = clean_text(request.form.get("name"), 120)
    price = clean_text(request.form.get("price"), 40)
    desc = clean_text(request.form.get("description"), 300)
    img = save_uploaded_image(MENU_IMAGES_DIR, tenant["id"], request.files.get("image"))
    if name:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO tenant_menu_items (tenant_id, name, price, description, image_filename) VALUES (%s,%s,%s,%s,%s)",
                    (tenant["id"], name, price, desc, img),
                )
    return back_to_panel(slug, "", "pane-menu")


@app.route("/i/<slug>/panel/menu/<int:item_id>/edit", methods=["POST"])
@tenant_panel_required
def tenant_edit_menu_item(slug, item_id):
    tenant = g.tenant
    _require_menu_module(tenant)
    name = clean_text(request.form.get("name"), 120)
    price = clean_text(request.form.get("price"), 40)
    desc = clean_text(request.form.get("description"), 300)
    new_img = save_uploaded_image(MENU_IMAGES_DIR, tenant["id"], request.files.get("image"))
    if name:
        with get_db() as conn:
            with conn.cursor() as cur:
                if new_img:
                    cur.execute(
                        """UPDATE tenant_menu_items SET name=%s, price=%s, description=%s, image_filename=%s
                           WHERE id=%s AND tenant_id=%s""",
                        (name, price, desc, new_img, item_id, tenant["id"]),
                    )
                else:
                    cur.execute(
                        "UPDATE tenant_menu_items SET name=%s, price=%s, description=%s WHERE id=%s AND tenant_id=%s",
                        (name, price, desc, item_id, tenant["id"]),
                    )
    return back_to_panel(slug, "", "pane-menu")


@app.route("/i/<slug>/panel/menu/<int:item_id>/delete", methods=["POST"])
@tenant_panel_required
def tenant_delete_menu_item(slug, item_id):
    _require_menu_module(g.tenant)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenant_menu_items WHERE id = %s AND tenant_id = %s", (item_id, g.tenant["id"]))
    return back_to_panel(slug, "", "pane-menu")


@app.route("/i/<slug>/panel/update/<ticket_id>", methods=["POST"])
@tenant_panel_required
def tenant_update_ticket(slug, ticket_id):
    new_status = request.form.get("status", "Yeni").strip()
    if new_status not in TICKET_STATUSES:
        new_status = "Yeni"
    if not update_ticket_status(g.tenant["id"], ticket_id, new_status):
        return back_to_panel(slug, "⚠️ Bu randevunun masa/saati artık başka bir kayıtta, iptal geri alınamadı.")
    return back_to_panel(slug)


@app.route("/i/<slug>/panel/delete/<ticket_id>", methods=["POST"])
@tenant_panel_required
def tenant_delete_ticket(slug, ticket_id):
    delete_ticket_by_id(g.tenant["id"], ticket_id)
    return back_to_panel(slug)


# ---------------------------------------------------------------------------
# Super admin
# ---------------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def superadmin_login():
    error = None
    if not SUPERADMIN_ENABLED:
        error = "Yönetici girişi kapalı: Render'da SUPERADMIN_USERNAME ve SUPERADMIN_PASSWORD tanımlayın."
        return render_template("superadmin_login.html", error=error)
    if session.get("superadmin_auth"):
        return redirect(url_for("superadmin_panel"))
    next_url = safe_next(request.form.get("next") or request.args.get("next"), url_for("superadmin_panel"))
    if request.method == "POST":
        if rate_limited(f"adm:{request.remote_addr}", 6, 900):
            abort(429)
        u = request.form.get("username", "").strip().encode("utf-8")
        p = request.form.get("password", "").strip().encode("utf-8")
        ok_u = hmac.compare_digest(u, SUPERADMIN_USERNAME.encode("utf-8"))
        ok_p = hmac.compare_digest(p, SUPERADMIN_PASSWORD.encode("utf-8"))
        if ok_u and ok_p:
            session["superadmin_auth"] = True
            return redirect(next_url)
        error = "Kullanıcı adı veya şifre hatalı."
    return render_template("superadmin_login.html", error=error)


@app.route("/admin/logout", methods=["POST"])
def superadmin_logout():
    session.pop("superadmin_auth", None)
    return redirect(url_for("superadmin_login"))


@app.route("/admin")
@superadmin_required
def superadmin_panel():
    return render_template("superadmin.html", tenants=get_all_tenants(), iban_number=IBAN_NUMBER)


def _admin_exec(sql, params):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
    return redirect(url_for("superadmin_panel"))


@app.route("/admin/tenant/<int:tenant_id>/approve", methods=["POST"])
@superadmin_required
def superadmin_approve_tenant(tenant_id):
    return _admin_exec(
        """UPDATE tenants SET is_active = TRUE, payment_requested = FALSE, activated_at = NOW(),
           expires_at = GREATEST(COALESCE(expires_at, NOW()), NOW()) + INTERVAL '30 days' WHERE id = %s""",
        (tenant_id,),
    )


@app.route("/admin/tenant/<int:tenant_id>/unlock-qr", methods=["POST"])
@superadmin_required
def superadmin_unlock_qr_addon(tenant_id):
    return _admin_exec("UPDATE tenants SET qr_addon_active = TRUE, qr_addon_requested = FALSE WHERE id = %s", (tenant_id,))


@app.route("/admin/tenant/<int:tenant_id>/extend", methods=["POST"])
@superadmin_required
def superadmin_extend_tenant(tenant_id):
    return _admin_exec(
        """UPDATE tenants SET is_active = TRUE,
           expires_at = GREATEST(COALESCE(expires_at, NOW()), NOW()) + INTERVAL '30 days' WHERE id = %s""",
        (tenant_id,),
    )


@app.route("/admin/tenant/<int:tenant_id>/suspend", methods=["POST"])
@superadmin_required
def superadmin_suspend_tenant(tenant_id):
    return _admin_exec("UPDATE tenants SET is_active = FALSE WHERE id = %s", (tenant_id,))


@app.route("/admin/tenant/<int:tenant_id>/edit", methods=["POST"])
@superadmin_required
def superadmin_edit_tenant(tenant_id):
    business_name = clean_text(request.form.get("business_name"), 120)
    owner_email = clean_text(request.form.get("owner_email"), 160).lower()
    plan = request.form.get("plan", "starter").strip()
    module_type = request.form.get("module_type", "b2b-ticaret").strip()
    b2b_tier = request.form.get("b2b_tier", "standard").strip().lower()
    new_password = request.form.get("new_password", "").strip()
    try:
        table_count = max(1, min(200, int(request.form.get("table_count", 8))))
        credit_limit = _money(max(0.0, float(request.form.get("credit_limit") or 50000)))
    except ValueError:
        table_count = 8
        credit_limit = _money(50000)
    plan = plan if plan in {"starter", "pro"} else "starter"
    module_type = module_type if module_type in VALID_MODULES else "b2b-ticaret"
    b2b_tier = b2b_tier if b2b_tier in VALID_B2B_TIERS else "standard"

    if business_name and _EMAIL_RE.match(owner_email):
        with get_db() as conn:
            with conn.cursor() as cur:
                if len(new_password) >= 8:
                    cur.execute(
                        """UPDATE tenants SET business_name=%s, owner_email=%s, plan=%s, module_type=%s,
                           b2b_tier=%s, credit_limit=%s, table_count=%s, password_hash=%s WHERE id=%s""",
                        (
                            business_name, owner_email, plan, module_type,
                            b2b_tier, credit_limit, table_count, generate_password_hash(new_password), tenant_id,
                        ),
                    )
                else:
                    cur.execute(
                        """UPDATE tenants SET business_name=%s, owner_email=%s, plan=%s, module_type=%s,
                           b2b_tier=%s, credit_limit=%s, table_count=%s WHERE id=%s""",
                        (
                            business_name, owner_email, plan, module_type,
                            b2b_tier, credit_limit, table_count, tenant_id,
                        ),
                    )
    return redirect(url_for("superadmin_panel"))


@app.route("/admin/tenant/<int:tenant_id>/delete", methods=["POST"])
@superadmin_required
def superadmin_delete_tenant(tenant_id):
    return _admin_exec("DELETE FROM tenants WHERE id = %s AND slug != 'kolay-vitrin'", (tenant_id,))


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
