import functools
import hashlib
import hmac
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
from pathlib import Path
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.errors
import psycopg2.pool
import requests
from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from psycopg2.extras import RealDictCursor
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from duzgunler import duzgunler_bp, init_db as init_duzgunler_db

try:
    import segno
except ImportError:
    segno = None


# ---------------------------------------------------------------------------
# Yapilandirma
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(f"{name} ortam degiskeni tanimli degil. Render > Environment kismina ekleyin.")
    return val


def _normalize_db_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
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
IMG_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
MAX_IMG_BYTES = 4 * 1024 * 1024

TIME_SLOTS = [
    "09:00", "10:00", "11:00", "12:00", "13:00", "14:00",
    "15:00", "16:00", "17:00", "18:00", "19:00", "20:00",
    "21:00", "22:00", "23:00",
]
TICKET_STATUSES = {"Yeni", "İnceleniyor", "Tamamlandı", "İptal"}
VALID_MODULES = {
    "genel",
    "kafe-randevu",
    "berber-randevu",
    "masa-qr",
    "mobil-saha",
    "web-otomasyon",
    "masaustu-otomasyon",
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
    "web-otomasyon": "Web Panelleri, Formlar & Webhook",
    "masaustu-otomasyon": "Masaüstü Kasa, Barkod & Stok Otomasyonu",
    "genel": "Genel Talep & Müşteri Formu",
}

MODULE_PANEL_TITLES = {
    "kafe-randevu": "Kafe & Restoran Masa Randevu Paneli",
    "masa-qr": "Masa QR Sipariş & Garson Paneli",
    "berber-randevu": "Berber & Kuaför Randevu Paneli",
    "mobil-saha": "Mobil Saha & Canlı Takip Paneli",
    "web-otomasyon": "Webhook & Veri Otomasyon Paneli",
    "masaustu-otomasyon": "Kasa, Barkod & Stok Paneli",
    "genel": "İşletme Talep Yönetim Paneli",
}

SERVICES_DATA = [
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
        "title": "Web Panelleri, Formlar & Webhook",
        "image": "webotom.jpg",
        "short": "WhatsApp API, otomatik veri çekme (scraper/webhook) ve günlük raporlama entegrasyonları.",
        "details": "İşletmenin WhatsApp API, harici Webhook ve otomatik veri çekme bağlantılarını tek panelden yönetip günlük rapor üreten altyapı.",
        "features": [
            "WhatsApp Cloud/Business API & otomatik müşteri mesaj entegrasyonu",
            "Otomatik veri çekme URL (API/Webhook) ve zamanlanmış raporlama",
            "Webhook gönderim logları ve tek tıkla yeniden deneme",
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
]


# ---------------------------------------------------------------------------
# Yardimcilar
# ---------------------------------------------------------------------------
def now_tr() -> datetime:
    return datetime.now(TR_TZ).replace(tzinfo=None)


def today_tr():
    return now_tr().date()


def slugify(text: str) -> str:
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    cleaned = (text or "").translate(tr_map).lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")[:60]
    return cleaned or f"isletme-{uuid.uuid4().hex[:6]}"


def normalize_phone(raw_phone: str) -> str:
    digits = re.sub(r"\D+", "", raw_phone or "")
    if not digits:
        return ""
    if digits.startswith("0") and len(digits) == 11:
        return "90" + digits[1:]
    if len(digits) == 10 and digits.startswith("5"):
        return "90" + digits
    return digits


def parse_price_number(price_str) -> float:
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


def parse_date(value: str):
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def safe_next(url: str, fallback: str) -> str:
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url and "\n" not in url and "\r" not in url:
        return url
    return fallback


def clean_text(value: str, limit: int) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", (value or "").strip())[:limit]


_rl_store: dict = {}
_rl_lock = threading.Lock()


def rate_limited(key: str, limit: int, window_sec: int) -> bool:
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
_last_used: dict = {}


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
def _sniff_ok(ext: str, raw: bytes) -> bool:
    if ext in (".jpg", ".jpeg"):
        return raw[:3] == b"\xff\xd8\xff"
    if ext == ".png":
        return raw[:8] == b"\x89PNG\r\n\x1a\n"
    if ext == ".webp":
        return raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    return False


def save_uploaded_image(subdir: Path, tenant_id: int, file_storage) -> str:
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


def get_stored_image_from_db(tenant_id: int, category: str, filename: str):
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
                    module_type TEXT NOT NULL DEFAULT 'genel',
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
                    is_active BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    activated_at TIMESTAMP
                );
                """
            )
            for ddl in (
                "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS module_type TEXT NOT NULL DEFAULT 'genel'",
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
                    VALUES (%s,%s,%s,%s,'pro','kafe-randevu',8,%s,%s,FALSE,TRUE,NOW(), NOW() + INTERVAL '3650 days', %s)
                    """,
                    (
                        "kolay-vitrin",
                        "KOLAY Ana Vitrin",
                        "iletisim@kolayotomasyon.local",
                        generate_password_hash(pw),
                        WHATSAPP_NUMBER,
                        "Varsayilan aktif vitrin hesabi",
                        secrets.token_urlsafe(24),
                    ),
                )
                if not VITRIN_PASSWORD:
                    app.logger.warning("kolay-vitrin icin rastgele sifre olusturuldu: Super Admin > Duzenle ile degistirin.")
            elif check_password_hash(vit["password_hash"], "kolay1234"):
                pw = VITRIN_PASSWORD or secrets.token_urlsafe(12)
                cur.execute("UPDATE tenants SET password_hash = %s WHERE id = %s", (generate_password_hash(pw), vit["id"]))

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
                    str(item.get("id") or uuid.uuid4().hex[:8]),
                    tid,
                    str(item.get("name", "")).strip(),
                    str(item.get("phone", "")).strip(),
                    str(item.get("service", "")).strip(),
                    str(item.get("message", "")).strip(),
                    str(item.get("status") or "Yeni").strip(),
                    created,
                    now_tr(),
                ),
            )


def _backfill_reservations(cur):
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
# Tenant & panel baglami
# ---------------------------------------------------------------------------
_TENANT_SELECT = """
    SELECT t.*, (t.is_active AND t.expires_at IS NOT NULL AND t.expires_at < NOW()) AS is_expired
    FROM tenants t
"""


def tenant_usable(tenant) -> bool:
    return bool(tenant["is_active"]) and not tenant.get("is_expired")


def tenant_has_qr_access(tenant) -> bool:
    mod = tenant.get("module_type") or "genel"
    if mod == "masa-qr":
        return True
    if mod == "kafe-randevu":
        return (tenant.get("plan") == "pro") or bool(tenant.get("qr_addon_active"))
    return False


def resolve_panel_context(tenant) -> dict:
    mod = (tenant.get("module_type") or "genel").strip()
    if mod not in VALID_MODULES:
        mod = "genel"
    return {
        "mod_key": mod,
        "mod_label": MODULE_LABELS.get(mod, MODULE_LABELS["genel"]),
        "panel_title": MODULE_PANEL_TITLES.get(mod, MODULE_PANEL_TITLES["genel"]),
        "show_menu_tab": mod in {"kafe-randevu", "masa-qr"},
        "qr_unlocked": tenant_has_qr_access(tenant),
    }


def get_tenant_by_slug(slug: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(_TENANT_SELECT + " WHERE t.slug = %s", (slug,))
            return cur.fetchone()


def get_all_tenants() -> list[dict]:
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
        d["mod_label"] = MODULE_LABELS.get(d.get("module_type") or "genel", MODULE_LABELS["genel"])
    return rows


def create_tenant(
    business_name: str,
    owner_email: str,
    password: str,
    raw_slug: str = "",
    plan: str = "starter",
    module_type: str = "genel",
    whatsapp_number: str = "",
    company_legal_name: str = "",
    tax_office: str = "",
    tax_number: str = "",
):
    base_slug = slugify(raw_slug or business_name)
    mod = module_type if module_type in VALID_MODULES else "genel"
    chosen_plan = plan if plan in {"starter", "pro"} else "starter"
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
                    is_active, payment_requested, qr_addon_active, access_token)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE,FALSE,%s,%s)
                RETURNING *
                """,
                (
                    candidate,
                    business_name.strip()[:120],
                    owner_email.strip().lower()[:160],
                    generate_password_hash(password),
                    chosen_plan,
                    mod,
                    default_tables,
                    whatsapp_number.strip()[:30],
                    (company_legal_name or business_name).strip()[:160],
                    tax_office.strip()[:100],
                    tax_number.strip()[:40],
                    chosen_plan == "pro",
                    secrets.token_urlsafe(24),
                ),
            )
            return cur.fetchone()


def get_menu_items(tenant_id: int) -> list[dict]:
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
def get_field_agents(tenant_id: int) -> list[dict]:
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
        out.append(
            {
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
            }
        )
    return out


# ---------------------------------------------------------------------------
# Kasa / barkod
# ---------------------------------------------------------------------------
def pos_day_start() -> datetime:
    return now_tr().replace(hour=0, minute=0, second=0, microsecond=0)


def get_pos_overview(tenant_id: int):
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


def _urgency(minutes: int) -> str:
    if minutes >= 15:
        return "urgent"
    if minutes >= 8:
        return "warn"
    return "ok"


def load_tickets(tenant_id: int, limit: int = 300, statuses=None) -> list[dict]:
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


def ticket_stats(tenant_id: int) -> dict:
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
        "total": int(row["total"]),
        "yeni": int(row["yeni"]),
        "tamam": int(row["tamam"]),
        "active": int(row["active"]),
        "latest": latest,
        "latest_active_id": latest_active["id"] if latest_active else "",
    }


def recent_duplicate(tenant_id: int, name: str, service: str, seconds: int = 60) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM tickets WHERE tenant_id = %s AND name = %s AND service = %s
                   AND status IN ('Yeni','İnceleniyor') AND created_ts > %s LIMIT 1""",
                (tenant_id, name, service, now_tr() - timedelta(seconds=seconds)),
            )
            return cur.fetchone() is not None


def add_ticket(tenant, name: str, phone: str, service: str, message: str, reservation=None) -> str:
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
                        """INSERT INTO reservations (tenant_id, ticket_id, kind, res_date, slot, table_no)
                           VALUES (%s,%s,%s,%s,%s,%s)""",
                        (
                            tenant["id"],
                            ticket_id,
                            reservation["kind"],
                            reservation["res_date"],
                            reservation["slot"],
                            reservation.get("table_no"),
                        ),
                    )
    except psycopg2.errors.UniqueViolation:
        raise SlotTaken()
    ticket = {
        "id": ticket_id,
        "name": name,
        "phone": phone,
        "service": service,
        "message": message,
        "created_at": created_at,
    }
    run_async(notify_new_ticket, dict(tenant), ticket)
    return ticket_id


def update_ticket_status(tenant_id: int, ticket_id: str, new_status: str) -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE tickets SET status = %s WHERE id = %s AND tenant_id = %s",
                    (new_status, ticket_id, tenant_id),
                )
                cur.execute(
                    "UPDATE reservations SET is_active = %s WHERE ticket_id = %s AND tenant_id = %s",
                    (new_status != "İptal", ticket_id, tenant_id),
                )
        return True
    except psycopg2.errors.UniqueViolation:
        return False


def delete_ticket_by_id(tenant_id: int, ticket_id: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tickets WHERE id = %s AND tenant_id = %s", (ticket_id, tenant_id))


def get_booked_tables_by_slot(tenant_id: int, res_date) -> dict:
    booked = {sl: set() for sl in TIME_SLOTS}
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT slot, table_no FROM reservations
                   WHERE tenant_id = %s AND res_date = %s AND kind = 'table' AND is_active""",
                (tenant_id, res_date),
            )
            for r in cur.fetchall():
                if r["slot"] in booked and r["table_no"] is not None:
                    booked[r["slot"]].add(r["table_no"])
    return booked


def get_booked_barber_slots(tenant_id: int, res_date) -> set:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT slot FROM reservations
                   WHERE tenant_id = %s AND res_date = %s AND kind = 'barber' AND is_active""",
                (tenant_id, res_date),
            )
            return {r["slot"] for r in cur.fetchall()}


def past_slots_for(res_date) -> set:
    if res_date != today_tr():
        return set()
    hhmm = now_tr().strftime("%H:%M")
    return {sl for sl in TIME_SLOTS if sl <= hhmm}


# ---------------------------------------------------------------------------
# Entegrasyonlar (Webhook / WhatsApp / Veri Cekme - Telegram Yok)
# ---------------------------------------------------------------------------
def run_async(fn, *args, **kwargs):
    t = threading.Thread(target=_safe_call, args=(fn, args, kwargs), daemon=True)
    t.start()


def _safe_call(fn, args, kwargs):
    try:
        fn(*args, **kwargs)
    except Exception as exc:
        app.logger.error("Arka plan gorevi hatasi (%s): %s", getattr(fn, "__name__", fn), exc)


def get_bot_config(tenant) -> dict:
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
        "scraper_url": data.get("scraper_url", ""),
        "report_hour": data.get("report_hour", "21:00") or "21:00",
        "webhook_url": data.get("webhook_url", ""),
    }


def save_bot_config(tenant_id: int, cfg: dict):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tenants SET bot_config_json = %s WHERE id = %s",
                (json.dumps(cfg, ensure_ascii=False), tenant_id),
            )


def bot_log(tenant_id: int, message: str, level: str = "info"):
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


def get_bot_logs(tenant_id: int, limit: int = 20) -> list[dict]:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT created_at, level, message FROM bot_logs WHERE tenant_id = %s ORDER BY id DESC LIMIT %s",
                (tenant_id, limit),
            )
            return [dict(r, time_str=r["created_at"].strftime("%d.%m %H:%M:%S")) for r in cur.fetchall()]


def is_safe_public_url(url: str) -> bool:
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


def safe_request(method: str, url: str, **kwargs):
    if not is_safe_public_url(url):
        raise ValueError("URL güvenli değil veya erişilemiyor")
    kwargs.setdefault("timeout", 8)
    kwargs["allow_redirects"] = False
    return requests.request(method, url.strip(), **kwargs)


def send_webhook(cfg: dict, payload: dict):
    url = (cfg.get("webhook_url") or "").strip()
    if not url:
        return False, "Webhook URL eksik"
    try:
        r = safe_request("POST", url, json=payload)
        return r.ok, f"Webhook HTTP {r.status_code}"
    except Exception as exc:
        return False, f"Webhook hatası: {exc}"


def send_whatsapp(cfg: dict, to_phone: str, text: str):
    url, token = (cfg.get("wa_api_url") or "").strip(), (cfg.get("wa_api_token") or "").strip()
    to = normalize_phone(to_phone)
    if not url or not token:
        return False, "WhatsApp API URL/token eksik"
    if not to:
        return False, "Alıcı telefon yok"
    if cfg.get("wa_template_name"):
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {"name": cfg["wa_template_name"], "language": {"code": "tr"}},
        }
    else:
        body = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:1000]}}
    try:
        r = safe_request("POST", url, json=body, headers={"Authorization": f"Bearer {token}"})
        return r.ok, f"WhatsApp HTTP {r.status_code}"
    except Exception as exc:
        return False, f"WhatsApp hatası: {exc}"


def notify_new_ticket(tenant, ticket: dict):
    cfg = get_bot_config(tenant)
    if cfg["webhook_url"]:
        ok, info = send_webhook(
            cfg,
            {
                "business": tenant["business_name"],
                "slug": tenant["slug"],
                "event": "new_ticket",
                "ticket_id": ticket["id"],
                "name": ticket["name"],
                "phone": ticket["phone"],
                "service": ticket["service"],
                "message": ticket["message"],
                "created_at": ticket["created_at"],
                "timestamp": now_tr().isoformat(),
            },
        )
        bot_log(tenant["id"], f"Yeni talep → {info}", "info" if ok else "error")
    if cfg["wa_auto_reply"] and cfg["wa_api_url"] and cfg["wa_api_token"] and ticket.get("phone"):
        ok, info = send_whatsapp(
            cfg,
            ticket["phone"],
            f"Merhaba {ticket['name']}, talebiniz {tenant['business_name']} tarafına ulaştı. En kısa sürede dönüş yapacağız.",
        )
        bot_log(tenant["id"], f"WhatsApp karşılama → {info}", "info" if ok else "error")


def fetch_scraper_summary(url: str) -> str:
    r = safe_request("GET", url, stream=True, headers={"User-Agent": "KolayWeb/1.0"})
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


def build_daily_report(tenant, cfg: dict) -> str:
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
        f"Günlük Rapor — {tenant['business_name']} ({now_tr().strftime('%d.%m.%Y')})",
        f"Bugünkü talep: {c['total']} (Yeni: {c['yeni']}, Tamamlanan: {c['tamam']}, İptal: {c['iptal']})",
    ]
    if cfg.get("scraper_url"):
        try:
            lines.append("Veri kaynağı: " + fetch_scraper_summary(cfg["scraper_url"]))
        except Exception as exc:
            lines.append(f"Veri kaynağı alınamadı: {exc}")
    return "\n".join(lines)


def send_report_to_channels(tenant, cfg: dict, text: str) -> list:
    results = []
    if cfg["webhook_url"]:
        results.append(
            send_webhook(
                cfg,
                {
                    "business": tenant["business_name"],
                    "slug": tenant["slug"],
                    "event": "daily_report",
                    "message": text,
                    "timestamp": now_tr().isoformat(),
                },
            )
        )
    return results


def run_due_reports() -> int:
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
        if not cfg["webhook_url"]:
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


def csrf_token() -> str:
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
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


def is_superadmin() -> bool:
    return SUPERADMIN_ENABLED and session.get("superadmin") is True


def has_tenant_access(tenant) -> bool:
    return is_superadmin() or session.get("tenant_id") == tenant["id"]


def login_required_for_tenant(fn):
    @functools.wraps(fn)
    def wrapper(slug: str, *args, **kwargs):
        tenant = get_tenant_by_slug(slug)
        if not tenant:
            abort(404)
        if not has_tenant_access(tenant):
            return redirect(url_for("tenant_login", slug=slug, next=request.full_path.rstrip("?")))
        if not tenant_usable(tenant) and not is_superadmin():
            return redirect(url_for("tenant_pending", slug=slug))
        return fn(tenant, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Ana vitrin ve hizmetler
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template(
        "index.html",
        services=SERVICES_DATA,
        wa_number=WHATSAPP_NUMBER,
        price_starter=PLAN_PRICE_STARTER,
        price_pro=PLAN_PRICE_PRO,
        qr_addon_price=QR_ADDON_PRICE,
    )


@app.route("/hizmet/<service_id>")
def service_detail(service_id: str):
    service = next((s for s in SERVICES_DATA if s["id"] == service_id), None)
    if not service:
        abort(404)
    return render_template("service_detail.html", service=service, wa_number=WHATSAPP_NUMBER)


@app.route("/isletme-kayit", methods=["GET", "POST"])
def business_register():
    error = None
    form_data = {
        "business_name": "",
        "company_legal_name": "",
        "tax_office": "",
        "tax_number": "",
        "owner_email": "",
        "whatsapp_number": "",
        "slug": "",
        "module_type": "kafe-randevu",
        "plan": "starter",
    }
    if request.method == "POST":
        ip = request.remote_addr or "0.0.0.0"
        if rate_limited(f"reg:{ip}", 10, 3600):
            error = "Çok fazla kayıt denemesi yapıldı. Lütfen daha sonra tekrar deneyin."
        else:
            for k in form_data:
                form_data[k] = clean_text(request.form.get(k, ""), 160)
            password = request.form.get("password", "")
            if form_data["module_type"] not in VALID_MODULES:
                form_data["module_type"] = "genel"
            if form_data["plan"] not in {"starter", "pro"}:
                form_data["plan"] = "starter"

            if not form_data["business_name"] or not form_data["owner_email"] or len(password) < 4:
                error = "İşletme adı, e-posta ve en az 4 karakterli panel şifresi zorunludur."
            else:
                tenant = create_tenant(
                    business_name=form_data["business_name"],
                    owner_email=form_data["owner_email"],
                    password=password,
                    raw_slug=form_data["slug"],
                    plan=form_data["plan"],
                    module_type=form_data["module_type"],
                    whatsapp_number=form_data["whatsapp_number"],
                    company_legal_name=form_data["company_legal_name"],
                    tax_office=form_data["tax_office"],
                    tax_number=form_data["tax_number"],
                )
                session["tenant_id"] = tenant["id"]
                return redirect(url_for("tenant_pending", slug=tenant["slug"]))

    return render_template(
        "business_register.html",
        error=error,
        form_data=form_data,
        module_labels=MODULE_LABELS,
        price_starter=PLAN_PRICE_STARTER,
        price_pro=PLAN_PRICE_PRO,
        qr_addon_price=QR_ADDON_PRICE,
    )


# ---------------------------------------------------------------------------
# Isletme giris, bekleme / odeme ve panel
# ---------------------------------------------------------------------------
@app.route("/i/<slug>/giris", methods=["GET", "POST"])
def tenant_login(slug: str):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)
    next_url = safe_next(request.args.get("next") or request.form.get("next") or "", url_for("tenant_panel", slug=slug))
    error = None

    if request.method == "POST":
        ip = request.remote_addr or "0.0.0.0"
        if rate_limited(f"tlogin:{slug}:{ip}", 12, 300):
            error = "Çok fazla giriş denemesi. Lütfen birkaç dakika bekleyin."
        else:
            password = request.form.get("password", "")
            if check_password_hash(tenant["password_hash"], password):
                session["tenant_id"] = tenant["id"]
                if not tenant_usable(tenant):
                    return redirect(url_for("tenant_pending", slug=slug))
                return redirect(next_url)
            error = "Panel şifresi hatalı."

    return render_template("tenant_login.html", tenant=tenant, error=error, next_url=next_url)


@app.route("/i/<slug>/cikis", methods=["POST"])
def tenant_logout(slug: str):
    session.pop("tenant_id", None)
    return redirect(url_for("index"))


@app.route("/i/<slug>/beklemede")
def tenant_pending(slug: str):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)
    if tenant_usable(tenant) and has_tenant_access(tenant):
        return redirect(url_for("tenant_panel", slug=slug))

    mod = tenant.get("module_type") or "genel"
    return render_template(
        "tenant_pending.html",
        tenant=tenant,
        is_logged_in=has_tenant_access(tenant),
        module_labels=MODULE_LABELS,
        mod_label=MODULE_LABELS.get(mod, MODULE_LABELS["genel"]),
        iban_holder=IBAN_HOLDER,
        iban_bank=IBAN_BANK,
        iban_number=IBAN_NUMBER,
        price_starter=PLAN_PRICE_STARTER,
        price_pro=PLAN_PRICE_PRO,
        qr_addon_price=QR_ADDON_PRICE,
        wa_number=WHATSAPP_NUMBER,
        notified=request.args.get("notified") == "1",
        saved_mod=request.args.get("saved_mod") == "1",
    )


@app.route("/i/<slug>/odeme-bildir", methods=["POST"])
def notify_iban_payment(slug: str):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)
    if not has_tenant_access(tenant):
        return redirect(url_for("tenant_login", slug=slug, next=url_for("tenant_pending", slug=slug)))

    action_mode = (request.form.get("action_mode") or "payment").strip()
    chosen_mod = (request.form.get("module_type") or tenant.get("module_type") or "genel").strip()
    chosen_plan = (request.form.get("plan") or tenant.get("plan") or "starter").strip()
    if chosen_mod not in VALID_MODULES:
        chosen_mod = "genel"
    if chosen_plan not in {"starter", "pro"}:
        chosen_plan = "starter"

    note = clean_text(request.form.get("payment_note", ""), 250)
    default_tables = 8 if chosen_mod in {"kafe-randevu", "masa-qr"} else (tenant.get("table_count") or 4)
    qr_included = chosen_plan == "pro"

    with get_db() as conn:
        with conn.cursor() as cur:
            if action_mode == "save_module_only":
                cur.execute(
                    """UPDATE tenants SET module_type = %s, plan = %s, table_count = %s,
                       qr_addon_active = CASE WHEN %s THEN TRUE ELSE qr_addon_active END
                       WHERE id = %s""",
                    (chosen_mod, chosen_plan, default_tables, qr_included, tenant["id"]),
                )
                return redirect(url_for("tenant_pending", slug=slug, saved_mod="1"))

            cur.execute(
                """UPDATE tenants SET module_type = %s, plan = %s, table_count = %s,
                   payment_note = %s, payment_requested = TRUE,
                   qr_addon_active = CASE WHEN %s THEN TRUE ELSE qr_addon_active END
                   WHERE id = %s""",
                (
                    chosen_mod,
                    chosen_plan,
                    default_tables,
                    note or f"{MODULE_LABELS.get(chosen_mod, chosen_mod)} ({chosen_plan.upper()}) IBAN ödemesi bildirildi.",
                    qr_included,
                    tenant["id"],
                ),
            )
    return redirect(url_for("tenant_pending", slug=slug, notified="1"))


def _build_qr_list(tenant, request_root: str) -> list[dict]:
    count = max(1, min(int(tenant.get("table_count") or 8), 60))
    base = request_root.rstrip("/")
    items = []
    for n in range(1, count + 1):
        target = f"{base}/i/{tenant['slug']}?masa={n}"
        qr_img = f"https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={quote(target, safe='')}"
        items.append({"table_no": n, "label": f"Masa {n}", "target_url": target, "qr_img_url": qr_img})
    return items


@app.route("/i/<slug>/panel")
@login_required_for_tenant
def tenant_panel(tenant):
    ctx = resolve_panel_context(tenant)
    mod = ctx["mod_key"]
    tickets = load_tickets(tenant["id"])
    stats = ticket_stats(tenant["id"])
    menu_items = get_menu_items(tenant["id"]) if ctx["show_menu_tab"] else []
    qr_list = _build_qr_list(tenant, request.host_url) if ctx["qr_unlocked"] else []

    token = tenant.get("access_token") or ""
    base = request.host_url.rstrip("/")
    kds_url = f"{base}/i/{tenant['slug']}/mutfak?t={token}"
    saha_url = f"{base}/i/{tenant['slug']}/saha?t={token}"

    agents = get_field_agents(tenant["id"]) if mod == "mobil-saha" else []
    bot_cfg = get_bot_config(tenant) if mod == "web-otomasyon" else {}
    bot_logs = get_bot_logs(tenant["id"], 20) if mod == "web-otomasyon" else []
    pos_products, pos_sold, pos_rev, pos_sales = get_pos_overview(tenant["id"]) if mod == "masaustu-otomasyon" else ([], 0, 0.0, [])

    return render_template(
        "tenant_panel.html",
        tenant=tenant,
        tickets=tickets,
        total_count=stats["total"],
        yeni_count=stats["yeni"],
        tamam_count=stats["tamam"],
        mod_label=ctx["mod_label"],
        panel_title=ctx["panel_title"],
        show_menu_tab=ctx["show_menu_tab"],
        qr_unlocked=ctx["qr_unlocked"],
        qr_addon_price=QR_ADDON_PRICE,
        iban_holder=IBAN_HOLDER,
        iban_number=IBAN_NUMBER,
        addon_notified=request.args.get("addon_notified") == "1",
        bot_saved=request.args.get("bot_saved") or "",
        menu_items=menu_items,
        qr_list=qr_list,
        kds_url=kds_url,
        saha_url=saha_url,
        agents=agents,
        bot_cfg=bot_cfg,
        bot_logs=bot_logs,
        pos_products=pos_products,
        pos_total_sold=pos_sold,
        pos_total_revenue=pos_rev,
        pos_sales=pos_sales,
        start_tab=request.args.get("tab") or "",
    )


@app.route("/i/<slug>/panel/poll")
@login_required_for_tenant
def tenant_panel_poll(tenant):
    stats = ticket_stats(tenant["id"])
    latest = stats["latest"]
    return jsonify(
        {
            "total": stats["total"],
            "yeni": stats["yeni"],
            "tamam": stats["tamam"],
            "latest_id": latest["id"] if latest else "",
            "latest_name": latest["name"] if latest else "",
            "latest_service": latest["service"] if latest else "",
        }
    )


@app.route("/i/<slug>/panel/ayarlar", methods=["POST"])
@login_required_for_tenant
def tenant_update_settings(tenant):
    company_legal_name = clean_text(request.form.get("company_legal_name", ""), 160)
    tax_office = clean_text(request.form.get("tax_office", ""), 100)
    tax_number = clean_text(request.form.get("tax_number", ""), 40)
    wa_num = clean_text(request.form.get("whatsapp_number", ""), 30)
    try:
        table_count = max(1, min(int(request.form.get("table_count") or 8), 200))
    except ValueError:
        table_count = 8

    logo_file = request.files.get("logo")
    new_logo = save_uploaded_image(LOGO_IMAGES_DIR, tenant["id"], logo_file) if logo_file and logo_file.filename else ""

    with get_db() as conn:
        with conn.cursor() as cur:
            if new_logo:
                cur.execute(
                    """UPDATE tenants SET company_legal_name = %s, tax_office = %s, tax_number = %s,
                       whatsapp_number = %s, table_count = %s, logo_filename = %s WHERE id = %s""",
                    (company_legal_name, tax_office, tax_number, wa_num, table_count, new_logo, tenant["id"]),
                )
            else:
                cur.execute(
                    """UPDATE tenants SET company_legal_name = %s, tax_office = %s, tax_number = %s,
                       whatsapp_number = %s, table_count = %s WHERE id = %s""",
                    (company_legal_name, tax_office, tax_number, wa_num, table_count, tenant["id"]),
                )
    return redirect(url_for("tenant_panel", slug=tenant["slug"], tab="pane-settings"))


@app.route("/i/<slug>/panel/qr-eklenti-talep", methods=["POST"])
@login_required_for_tenant
def tenant_request_qr_addon(tenant):
    note = clean_text(request.form.get("qr_addon_note", ""), 200) or "Masa QR eklenti ödemesi bildirildi."
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tenants SET qr_addon_requested = TRUE, qr_addon_note = %s WHERE id = %s",
                (note, tenant["id"]),
            )
    return redirect(url_for("tenant_panel", slug=tenant["slug"], tab="pane-settings", addon_notified="1"))


@app.route("/i/<slug>/panel/token-yenile", methods=["POST"])
@login_required_for_tenant
def tenant_regen_token(tenant):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET access_token = %s WHERE id = %s", (secrets.token_urlsafe(24), tenant["id"]))
    return redirect(url_for("tenant_panel", slug=tenant["slug"], tab="pane-settings"))


# ---------------------------------------------------------------------------
# Menu, QR yazdirma ve mutfak ekrani (KDS)
# ---------------------------------------------------------------------------
@app.route("/i/<slug>/panel/menu/ekle", methods=["POST"])
@login_required_for_tenant
def tenant_add_menu_item(tenant):
    name = clean_text(request.form.get("name", ""), 120)
    price = clean_text(request.form.get("price", ""), 40)
    description = clean_text(request.form.get("description", ""), 240)
    img_file = request.files.get("image")
    img_name = save_uploaded_image(MENU_IMAGES_DIR, tenant["id"], img_file) if img_file and img_file.filename else ""
    if name:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO tenant_menu_items (tenant_id, name, price, description, image_filename)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (tenant["id"], name, price, description, img_name),
                )
    return redirect(url_for("tenant_panel", slug=tenant["slug"], tab="pane-menu"))


@app.route("/i/<slug>/panel/menu/<int:item_id>/sil", methods=["POST"])
@login_required_for_tenant
def tenant_delete_menu_item(tenant, item_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenant_menu_items WHERE id = %s AND tenant_id = %s", (item_id, tenant["id"]))
    return redirect(url_for("tenant_panel", slug=tenant["slug"], tab="pane-menu"))


@app.route("/i/<slug>/qr-yazdir")
@login_required_for_tenant
def tenant_qr_print(tenant):
    if not tenant_has_qr_access(tenant):
        abort(403)
    return render_template("qr_print.html", tenant=tenant, qr_list=_build_qr_list(tenant, request.host_url))


def _token_ok(tenant) -> bool:
    if has_tenant_access(tenant):
        return True
    tok = (request.args.get("t") or request.form.get("t") or request.headers.get("X-Access-Token") or "").strip()
    saved = tenant.get("access_token") or ""
    return bool(tok and saved and hmac.compare_digest(tok.encode("utf-8"), saved.encode("utf-8")))


@app.route("/i/<slug>/mutfak")
def kitchen_display(slug: str):
    tenant = get_tenant_by_slug(slug)
    if not tenant or not tenant_usable(tenant) or not tenant_has_qr_access(tenant):
        abort(404)
    if not _token_ok(tenant):
        return redirect(url_for("tenant_login", slug=slug, next=request.full_path.rstrip("?")))
    tok = (request.args.get("t") or tenant.get("access_token") or "").strip()
    return render_template(
        "kds.html",
        tenant=tenant,
        token=tok,
        tickets=load_tickets(tenant["id"], limit=100, statuses=("Yeni", "İnceleniyor")),
    )


@app.route("/i/<slug>/mutfak/veri")
def kitchen_data(slug: str):
    tenant = get_tenant_by_slug(slug)
    if not tenant or not tenant_usable(tenant) or not tenant_has_qr_access(tenant):
        abort(404)
    if not _token_ok(tenant):
        abort(403)
    rows = load_tickets(tenant["id"], limit=100, statuses=("Yeni", "İnceleniyor"))
    stats = ticket_stats(tenant["id"])
    return jsonify(
        {
            "active_count": stats["active"],
            "latest_active_id": stats["latest_active_id"],
            "tickets": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "phone": r["phone"] or "",
                    "service": r["service"] or "",
                    "message": r["message"] or "",
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "elapsed_mins": r["elapsed_mins"],
                    "urgency_level": r["urgency_level"],
                }
                for r in rows
            ],
        }
    )


@app.route("/i/<slug>/mutfak/durum/<ticket_id>", methods=["POST"])
def kitchen_set_status(slug: str, ticket_id: str):
    tenant = get_tenant_by_slug(slug)
    if not tenant or not tenant_usable(tenant) or not tenant_has_qr_access(tenant):
        abort(404)
    if not _token_ok(tenant):
        abort(403)
    new_status = (request.form.get("status") or "").strip()
    if new_status in TICKET_STATUSES:
        update_ticket_status(tenant["id"], ticket_id, new_status)
    tok = (request.form.get("t") or request.args.get("t") or "").strip()
    return redirect(url_for("kitchen_display", slug=slug, t=tok) if tok else url_for("kitchen_display", slug=slug))


# ---------------------------------------------------------------------------
# Saha elemani canli takip
# ---------------------------------------------------------------------------
@app.route("/i/<slug>/saha")
def field_agent_view(slug: str):
    tenant = get_tenant_by_slug(slug)
    if not tenant or not tenant_usable(tenant) or tenant.get("module_type") != "mobil-saha":
        abort(404)
    if not _token_ok(tenant):
        return redirect(url_for("tenant_login", slug=slug, next=request.full_path.rstrip("?")))
    tok = (request.args.get("t") or tenant.get("access_token") or "").strip()
    return render_template("saha_agent.html", tenant=tenant, token=tok)


@app.route("/i/<slug>/saha/ping", methods=["POST"])
def field_agent_ping(slug: str):
    tenant = get_tenant_by_slug(slug)
    if not tenant or not tenant_usable(tenant) or tenant.get("module_type") != "mobil-saha":
        abort(404)
    if not _token_ok(tenant):
        return jsonify({"ok": False, "error": "Yetkisiz cihaz anahtarı"}), 403
    data = request.get_json(silent=True) or request.form or {}
    agent_name = clean_text(str(data.get("agent_name") or ""), 80)
    if not agent_name:
        return jsonify({"ok": False, "error": "Personel adı gerekli"}), 400
    status_text = clean_text(str(data.get("status_text") or "Sahada Aktif"), 80)
    active_package = clean_text(str(data.get("active_package") or ""), 120)
    target_customer = clean_text(str(data.get("target_customer") or ""), 120)
    lat = clean_text(str(data.get("latitude") or ""), 32)
    lng = clean_text(str(data.get("longitude") or ""), 32)
    charging = str(data.get("is_charging") or "").lower() in ("1", "true", "yes", "on")
    try:
        bat = int(data.get("battery_level"))
        if bat < 0 or bat > 100:
            bat = -1
    except (TypeError, ValueError):
        bat = -1

    now = now_tr()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM field_agents WHERE tenant_id = %s AND LOWER(agent_name) = LOWER(%s) ORDER BY id DESC LIMIT 1",
                (tenant["id"], agent_name),
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """UPDATE field_agents
                       SET agent_name=%s, status_text=%s, active_package=%s, target_customer=%s,
                           battery_level=%s, is_charging=%s, latitude=%s, longitude=%s, updated_at=%s
                       WHERE id=%s AND tenant_id=%s""",
                    (
                        agent_name, status_text, active_package, target_customer,
                        bat, charging, lat, lng, now, existing["id"], tenant["id"],
                    ),
                )
            else:
                cur.execute(
                    """INSERT INTO field_agents
                       (tenant_id, agent_name, status_text, active_package, target_customer,
                        battery_level, is_charging, latitude, longitude, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        tenant["id"], agent_name, status_text, active_package, target_customer,
                        bat, charging, lat, lng, now,
                    ),
                )
    return jsonify({"ok": True, "updated_at": now.strftime("%H:%M:%S")})


@app.route("/i/<slug>/panel/saha/veri")
@login_required_for_tenant
def panel_saha_data(tenant):
    return jsonify({"agents": get_field_agents(tenant["id"])})


@app.route("/i/<slug>/panel/saha/<int:agent_id>/sil", methods=["POST"])
@login_required_for_tenant
def panel_saha_delete(tenant, agent_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM field_agents WHERE id = %s AND tenant_id = %s", (agent_id, tenant["id"]))
    return redirect(url_for("tenant_panel", slug=tenant["slug"], tab="pane-saha"))


# ---------------------------------------------------------------------------
# Web otomasyon (Webhook / WhatsApp / veri cekme - Telegram yok)
# ---------------------------------------------------------------------------
@app.route("/i/<slug>/panel/bot/kaydet", methods=["POST"])
@login_required_for_tenant
def tenant_save_bot_config(tenant):
    prev = get_bot_config(tenant)
    new_token = (request.form.get("wa_api_token") or "").strip()
    hour = (request.form.get("report_hour") or "21:00").strip()
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hour):
        hour = "21:00"
    cfg = {
        "wa_api_url": clean_text(request.form.get("wa_api_url", ""), 300),
        "wa_api_token": new_token if new_token else prev["wa_api_token"],
        "wa_template_name": clean_text(request.form.get("wa_template_name", ""), 100),
        "wa_auto_reply": bool(request.form.get("wa_auto_reply")),
        "scraper_url": clean_text(request.form.get("scraper_url", ""), 300),
        "report_hour": hour,
        "webhook_url": clean_text(request.form.get("webhook_url", ""), 300),
    }
    save_bot_config(tenant["id"], cfg)
    bot_log(tenant["id"], f"Entegrasyon ayarları güncellendi (Rapor saati: {hour}).")
    return redirect(url_for("tenant_panel", slug=tenant["slug"], tab="pane-bots", bot_saved="Ayarlar kaydedildi."))


@app.route("/i/<slug>/panel/bot/calistir", methods=["POST"])
@login_required_for_tenant
def tenant_run_bot_action(tenant):
    action = (request.form.get("bot_action") or "").strip()
    cfg = get_bot_config(tenant)
    msg = "İşlem tamamlandı."
    if action == "test":
        sample = f"Test bildirimi — {tenant['business_name']} ({now_tr().strftime('%d.%m.%Y %H:%M')})"
        res = send_report_to_channels(tenant, cfg, sample)
        if not res:
            msg = "Webhook URL tanımlanmamış."
            bot_log(tenant["id"], "Test bildirimi gönderilemedi: Webhook URL eksik.", "warn")
        else:
            for ok, info in res:
                bot_log(tenant["id"], f"Test → {info}", "info" if ok else "error")
            msg = "Test bildirimi gönderildi: " + ", ".join(info for _, info in res)
    elif action == "pull_data":
        report_text = build_daily_report(tenant, cfg)
        res = send_report_to_channels(tenant, cfg, report_text)
        if res:
            for ok, info in res:
                bot_log(tenant["id"], f"Rapor → {info}", "info" if ok else "error")
        bot_log(tenant["id"], "Rapor üretildi: " + report_text.replace("\n", " | "))
        msg = "Rapor oluşturuldu ve loglara işlendi."
    return redirect(url_for("tenant_panel", slug=tenant["slug"], tab="pane-bots", bot_saved=msg))


@app.route("/cron/gunluk-rapor")
def cron_daily_reports():
    secret = request.args.get("key") or request.headers.get("X-Cron-Key") or ""
    if not CRON_SECRET or not hmac.compare_digest(secret.encode("utf-8"), CRON_SECRET.encode("utf-8")):
        abort(403)
    return jsonify({"ok": True, "sent_tenants": run_due_reports(), "time": now_tr().strftime("%Y-%m-%d %H:%M")})


# ---------------------------------------------------------------------------
# Masaustu / barkod kasa
# ---------------------------------------------------------------------------
@app.route("/i/<slug>/panel/kasa/urun-ekle", methods=["POST"])
@login_required_for_tenant
def tenant_pos_add_product(tenant):
    barcode = clean_text(request.form.get("barcode", ""), 64)
    name = clean_text(request.form.get("name", ""), 140)
    try:
        price = max(0.0, float((request.form.get("price") or "0").replace(",", ".")))
        stock = int(float(request.form.get("stock") or "0"))
    except ValueError:
        price, stock = 0.0, 0
    if barcode and name:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO pos_products (tenant_id, barcode, name, price, stock) VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (tenant_id, barcode) DO UPDATE
                       SET name = EXCLUDED.name, price = EXCLUDED.price, stock = EXCLUDED.stock""",
                    (tenant["id"], barcode, name, price, stock),
                )
    return redirect(url_for("tenant_panel", slug=tenant["slug"], tab="pane-pos"))


@app.route("/i/<slug>/panel/kasa/okut", methods=["POST"])
@login_required_for_tenant
def tenant_pos_scan(tenant):
    barcode = clean_text(request.form.get("barcode", ""), 64)
    try:
        qty = max(1, int(request.form.get("qty") or "1"))
    except ValueError:
        qty = 1
    msg = ""
    if barcode:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM pos_products WHERE tenant_id = %s AND barcode = %s FOR UPDATE",
                    (tenant["id"], barcode),
                )
                prod = cur.fetchone()
                if not prod:
                    msg = f"Barkod bulunamadı: {barcode}"
                else:
                    unit = float(prod["price"])
                    tot = round(unit * qty, 2)
                    cur.execute(
                        "UPDATE pos_products SET stock = stock - %s, sold_today = sold_today + %s WHERE id = %s",
                        (qty, qty, prod["id"]),
                    )
                    cur.execute(
                        """INSERT INTO pos_sales (tenant_id, product_id, barcode, name, qty, unit_price, total, sold_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (tenant["id"], prod["id"], prod["barcode"], prod["name"], qty, unit, tot, now_tr()),
                    )
                    msg = f"Satış işlendi: {prod['name']} x{qty} ({tot:.2f} TL)"
    return redirect(url_for("tenant_panel", slug=tenant["slug"], tab="pane-pos", bot_saved=msg))


@app.route("/i/<slug>/panel/kasa/urun/<int:product_id>/sil", methods=["POST"])
@login_required_for_tenant
def tenant_pos_delete_product(tenant, product_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pos_products WHERE id = %s AND tenant_id = %s", (product_id, tenant["id"]))
    return redirect(url_for("tenant_panel", slug=tenant["slug"], tab="pane-pos"))


# ---------------------------------------------------------------------------
# Musteri vitrini, QR menu ve randevu/talep formlari
# ---------------------------------------------------------------------------
@app.route("/i/<slug>")
def tenant_public(slug: str):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)
    if not tenant_usable(tenant):
        return redirect(url_for("tenant_pending", slug=slug))

    mod = tenant.get("module_type") or "genel"
    raw_masa = (request.args.get("masa") or "").strip()
    table_no = None
    if raw_masa.isdigit() and 1 <= int(raw_masa) <= 200:
        table_no = int(raw_masa)

    res_date = parse_date(request.args.get("date", "")) or today_tr()
    if res_date < today_tr():
        res_date = today_tr()

    table_count = max(1, min(int(tenant.get("table_count") or 8), 200))
    booked_by_slot = get_booked_tables_by_slot(tenant["id"], res_date) if mod == "kafe-randevu" else {}
    booked_barber = get_booked_barber_slots(tenant["id"], res_date) if mod == "berber-randevu" else set()
    past_slots = past_slots_for(res_date)
    qr_access = tenant_has_qr_access(tenant)
    menu_items = get_menu_items(tenant["id"]) if (qr_access or mod in {"kafe-randevu", "masa-qr"}) else []

    return render_template(
        "tenant_public.html",
        tenant=tenant,
        mod_label=MODULE_LABELS.get(mod, MODULE_LABELS["genel"]),
        qr_access=qr_access,
        table_no=table_no,
        table_count=table_count,
        res_date=res_date.isoformat(),
        today_iso=today_tr().isoformat(),
        time_slots=TIME_SLOTS,
        booked_by_slot={k: sorted(v) for k, v in booked_by_slot.items()},
        booked_barber=sorted(booked_barber),
        past_slots=sorted(past_slots),
        menu_items=menu_items,
        sent=request.args.get("sent") == "1",
        error=request.args.get("err") or "",
    )


@app.route("/i/<slug>/talep", methods=["POST"])
def tenant_submit_ticket(slug: str):
    tenant = get_tenant_by_slug(slug)
    if not tenant or not tenant_usable(tenant):
        abort(404)

    ip = request.remote_addr or "0.0.0.0"
    if rate_limited(f"tkt:{slug}:{ip}", 25, 600):
        return redirect(url_for("tenant_public", slug=slug, err="Çok fazla istek gönderildi. Lütfen kısa süre sonra tekrar deneyin."))

    mod = tenant.get("module_type") or "genel"
    raw_masa = (request.form.get("table_no") or "").strip()
    table_no = int(raw_masa) if raw_masa.isdigit() and 1 <= int(raw_masa) <= 200 else None
    action_type = (request.form.get("action_type") or "").strip()

    name = clean_text(request.form.get("name", ""), 100)
    if not name and table_no:
        name = f"Masa {table_no}"
    if not name and action_type == "garson_cagir":
        name = "Masa Müşterisi"
    phone = clean_text(request.form.get("phone", ""), 40)
    message = clean_text(request.form.get("message", ""), 1000)

    reservation = None
    if mod == "kafe-randevu" and not table_no:
        res_date = parse_date(request.form.get("res_date", ""))
        slot = (request.form.get("slot") or "").strip()
        try:
            t_no = int(request.form.get("res_table") or "0")
        except ValueError:
            t_no = 0
        max_t = max(1, min(int(tenant.get("table_count") or 8), 200))
        if not name or not res_date or res_date < today_tr() or slot not in TIME_SLOTS or slot in past_slots_for(res_date) or not (1 <= t_no <= max_t):
            return redirect(url_for("tenant_public", slug=slug, date=(res_date or today_tr()).isoformat(), err="Lütfen ad, tarih, saat ve masa seçin."))
        service = f"Randevu {res_date.isoformat()} {slot} — Masa {t_no}"
        message = message or f"{res_date.strftime('%d.%m.%Y')} saat {slot} için Masa {t_no} rezervasyonu."
        reservation = {"kind": "table", "res_date": res_date, "slot": slot, "table_no": t_no}
    elif mod == "berber-randevu":
        res_date = parse_date(request.form.get("res_date", ""))
        slot = (request.form.get("slot") or "").strip()
        hizmet = clean_text(request.form.get("barber_service") or "Randevu", 80)
        if not name or not res_date or res_date < today_tr() or slot not in TIME_SLOTS or slot in past_slots_for(res_date):
            return redirect(url_for("tenant_public", slug=slug, date=(res_date or today_tr()).isoformat(), err="Lütfen ad, tarih ve müsait saat seçin."))
        service = f"{hizmet} ({res_date.isoformat()} {slot})"
        message = message or f"{res_date.strftime('%d.%m.%Y')} saat {slot} için {hizmet} randevusu."
        reservation = {"kind": "barber", "res_date": res_date, "slot": slot, "table_no": None}
    else:
        if action_type == "garson_cagir":
            service = f"Garson Çağır (Masa {table_no})" if table_no else "Garson Çağır"
            message = message or "Masaya garson çağrıldı."
        elif action_type == "hesap_iste":
            service = f"Hesap İste (Masa {table_no})" if table_no else "Hesap İste"
            message = message or "Hesap talep edildi."
        else:
            service = clean_text(request.form.get("service") or (f"Masa {table_no} Sipariş" if table_no else "Genel Talep"), 120)
            if not name or not message:
                return redirect(url_for("tenant_public", slug=slug, masa=table_no or "", err="Lütfen adınızı ve talebinizi yazın."))

    if recent_duplicate(tenant["id"], name, service):
        return redirect(url_for("tenant_public", slug=slug, masa=table_no or "", sent="1"))

    try:
        add_ticket(tenant, name, phone, service, message, reservation=reservation)
    except SlotTaken:
        return redirect(url_for("tenant_public", slug=slug, date=request.form.get("res_date", ""), err="Seçilen saat veya masa az önce doldu. Lütfen başka bir seçim yapın."))

    return redirect(url_for("tenant_public", slug=slug, masa=table_no or "", sent="1"))


@app.route("/i/<slug>/panel/talep/<ticket_id>/durum", methods=["POST"])
@login_required_for_tenant
def tenant_update_ticket(tenant, ticket_id: str):
    new_status = (request.form.get("status") or "").strip()
    if new_status in TICKET_STATUSES:
        if not update_ticket_status(tenant["id"], ticket_id, new_status):
            return redirect(url_for("tenant_panel", slug=tenant["slug"], bot_saved="Bu saat/masa için aktif başka bir randevu var."))
    return redirect(url_for("tenant_panel", slug=tenant["slug"]))


@app.route("/i/<slug>/panel/talep/<ticket_id>/sil", methods=["POST"])
@login_required_for_tenant
def tenant_delete_ticket(tenant, ticket_id: str):
    delete_ticket_by_id(tenant["id"], ticket_id)
    return redirect(url_for("tenant_panel", slug=tenant["slug"]))


# ---------------------------------------------------------------------------
# Gorsel servisi
# ---------------------------------------------------------------------------
@app.route("/images/<path:filename>")
def serve_public_image(filename: str):
    p = (IMAGES_DIR / filename).resolve()
    if IMAGES_DIR.resolve() not in p.parents or not p.is_file():
        abort(404)
    return send_from_directory(IMAGES_DIR, filename)


def _serve_tenant_stored_image(tenant_id: int, category: str, filename: str):
    clean = Path(secure_filename(filename)).name
    if not clean:
        abort(404)
    row = get_stored_image_from_db(tenant_id, category, clean)
    if row and row.get("data"):
        return Response(bytes(row["data"]), mimetype=row.get("content_type") or "image/jpeg")
    disk_dir = MENU_IMAGES_DIR if category == "menu" else LOGO_IMAGES_DIR
    disk_file = (disk_dir / str(tenant_id) / clean).resolve()
    if (disk_dir / str(tenant_id)).resolve() in disk_file.parents and disk_file.is_file():
        return send_from_directory(disk_file.parent, disk_file.name)
    abort(404)


@app.route("/i/<slug>/menu-gorsel/<filename>")
def serve_tenant_public_menu_image(slug: str, filename: str):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)
    return _serve_tenant_stored_image(tenant["id"], "menu", filename)


@app.route("/panel/menu-gorsel/<int:tenant_id>/<filename>")
def serve_menu_image(tenant_id: int, filename: str):
    if not is_superadmin() and session.get("tenant_id") != tenant_id:
        abort(403)
    return _serve_tenant_stored_image(tenant_id, "menu", filename)


@app.route("/panel/logo/<int:tenant_id>/<filename>")
def serve_tenant_logo(tenant_id: int, filename: str):
    return _serve_tenant_stored_image(tenant_id, "logos", filename)


# ---------------------------------------------------------------------------
# Super Admin
# ---------------------------------------------------------------------------
@app.route("/admin/giris", methods=["GET", "POST"])
def superadmin_login():
    if not SUPERADMIN_ENABLED:
        abort(404)
    error = None
    if request.method == "POST":
        ip = request.remote_addr or "0.0.0.0"
        if rate_limited(f"sadmin:{ip}", 10, 300):
            error = "Çok fazla giriş denemesi. Lütfen bekleyin."
        else:
            u = (request.form.get("username") or "").strip()
            p = request.form.get("password") or ""
            if hmac.compare_digest(u.encode("utf-8"), SUPERADMIN_USERNAME.encode("utf-8")) and hmac.compare_digest(
                p.encode("utf-8"), SUPERADMIN_PASSWORD.encode("utf-8")
            ):
                session["superadmin"] = True
                return redirect(url_for("superadmin_panel"))
            error = "Super Admin kullanıcı adı veya şifresi hatalı."
    return render_template("superadmin_login.html", error=error)


@app.route("/admin/cikis", methods=["POST"])
def superadmin_logout():
    session.pop("superadmin", None)
    return redirect(url_for("index"))


@app.route("/admin")
def superadmin_panel():
    if not SUPERADMIN_ENABLED:
        abort(404)
    if not is_superadmin():
        return redirect(url_for("superadmin_login"))
    return render_template(
        "superadmin.html",
        tenants=get_all_tenants(),
        module_labels=MODULE_LABELS,
        price_starter=PLAN_PRICE_STARTER,
        price_pro=PLAN_PRICE_PRO,
        qr_addon_price=QR_ADDON_PRICE,
        iban_holder=IBAN_HOLDER,
        iban_bank=IBAN_BANK,
        iban_number=IBAN_NUMBER,
    )


@app.route("/admin/isletme-ekle", methods=["POST"])
def superadmin_create_tenant():
    if not is_superadmin():
        abort(403)
    b_name = clean_text(request.form.get("business_name", ""), 120)
    legal_name = clean_text(request.form.get("company_legal_name", ""), 160)
    tax_office = clean_text(request.form.get("tax_office", ""), 100)
    tax_number = clean_text(request.form.get("tax_number", ""), 40)
    email = clean_text(request.form.get("owner_email", ""), 160)
    pw = request.form.get("password") or secrets.token_urlsafe(8)
    slug_in = clean_text(request.form.get("slug", ""), 60)
    plan = (request.form.get("plan") or "starter").strip()
    mod = (request.form.get("module_type") or "genel").strip()
    wa = clean_text(request.form.get("whatsapp_number", ""), 30)
    activate_now = bool(request.form.get("activate_now"))

    if b_name and email:
        t = create_tenant(
            b_name,
            email,
            pw,
            slug_in,
            plan,
            mod,
            wa,
            company_legal_name=legal_name,
            tax_office=tax_office,
            tax_number=tax_number,
        )
        if activate_now:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE tenants SET is_active = TRUE, payment_requested = FALSE,
                           activated_at = NOW(), expires_at = NOW() + INTERVAL '30 days' WHERE id = %s""",
                        (t["id"],),
                    )
    return redirect(url_for("superadmin_panel"))


@app.route("/admin/isletme/<int:tenant_id>/duzenle", methods=["POST"])
def superadmin_edit_tenant(tenant_id: int):
    if not is_superadmin():
        abort(403)
    b_name = clean_text(request.form.get("business_name", ""), 120)
    legal_name = clean_text(request.form.get("company_legal_name", ""), 160)
    tax_office = clean_text(request.form.get("tax_office", ""), 100)
    tax_number = clean_text(request.form.get("tax_number", ""), 40)
    email = clean_text(request.form.get("owner_email", ""), 160)
    wa = clean_text(request.form.get("whatsapp_number", ""), 30)
    plan = (request.form.get("plan") or "starter").strip()
    mod = (request.form.get("module_type") or "genel").strip()
    if plan not in {"starter", "pro"}:
        plan = "starter"
    if mod not in VALID_MODULES:
        mod = "genel"
    try:
        table_count = max(1, min(int(request.form.get("table_count") or 8), 200))
    except ValueError:
        table_count = 8
    new_pw = (request.form.get("new_password") or "").strip()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE tenants
                   SET business_name = COALESCE(NULLIF(%s, ''), business_name),
                       company_legal_name = %s,
                       tax_office = %s,
                       tax_number = %s,
                       owner_email = COALESCE(NULLIF(%s, ''), owner_email),
                       whatsapp_number = %s,
                       plan = %s,
                       module_type = %s,
                       table_count = %s
                   WHERE id = %s""",
                (b_name, legal_name, tax_office, tax_number, email, wa, plan, mod, table_count, tenant_id),
            )
            if new_pw:
                cur.execute("UPDATE tenants SET password_hash = %s WHERE id = %s", (generate_password_hash(new_pw), tenant_id))
    return redirect(url_for("superadmin_panel"))


@app.route("/admin/isletme/<int:tenant_id>/onayla", methods=["POST"])
def superadmin_approve_tenant(tenant_id: int):
    if not is_superadmin():
        abort(403)
    try:
        days = max(1, min(int(request.form.get("days") or 30), 3650))
    except ValueError:
        days = 30
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE tenants
                   SET is_active = TRUE, payment_requested = FALSE,
                       activated_at = COALESCE(activated_at, NOW()),
                       expires_at = GREATEST(COALESCE(expires_at, NOW()), NOW()) + (%s * INTERVAL '1 day')
                   WHERE id = %s""",
                (days, tenant_id),
            )
    return redirect(url_for("superadmin_panel"))


@app.route("/admin/isletme/<int:tenant_id>/pasif", methods=["POST"])
def superadmin_deactivate_tenant(tenant_id: int):
    if not is_superadmin():
        abort(403)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET is_active = FALSE WHERE id = %s", (tenant_id,))
    return redirect(url_for("superadmin_panel"))


@app.route("/admin/isletme/<int:tenant_id>/qr-onayla", methods=["POST"])
def superadmin_approve_qr_addon(tenant_id: int):
    if not is_superadmin():
        abort(403)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET qr_addon_active = TRUE, qr_addon_requested = FALSE WHERE id = %s", (tenant_id,))
    return redirect(url_for("superadmin_panel"))


@app.route("/admin/isletme/<int:tenant_id>/sil", methods=["POST"])
def superadmin_delete_tenant(tenant_id: int):
    if not is_superadmin():
        abort(403)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT slug FROM tenants WHERE id = %s", (tenant_id,))
            row = cur.fetchone()
            if row and row["slug"] == "kolay-vitrin":
                return redirect(url_for("superadmin_panel"))
            cur.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
    return redirect(url_for("superadmin_panel"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG") == "1")
