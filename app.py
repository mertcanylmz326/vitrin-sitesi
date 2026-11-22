import functools
import json
import mimetypes
import os
import re
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlparse

import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template_string,
    request,
    send_from_directory,
    session,
    url_for,
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "kolay-otomasyon-gizli-anahtar-2026")

BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR = BASE_DIR / "images"
MENU_IMAGES_DIR = IMAGES_DIR / "menu"
LOGO_IMAGES_DIR = IMAGES_DIR / "logos"
LEGACY_JSON_FILE = BASE_DIR / "tickets.json"

ALLOWED_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
TIME_SLOTS = [
    "09:00", "10:00", "11:00", "12:00", "13:00", "14:00",
    "15:00", "16:00", "17:00", "18:00", "19:00", "20:00",
    "21:00", "22:00", "23:00"
]

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL ortam degiskeni tanimli degil. Render Environment kismina ekleyin.")

SUPERADMIN_USERNAME = os.environ.get("SUPERADMIN_USERNAME", "rootadmin")
SUPERADMIN_PASSWORD = os.environ.get("SUPERADMIN_PASSWORD", "adminroot")
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
    "genel": "Genel Talep Formu",
}

SERVICES_DATA = [
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
            "İşletme panelinden tüm saha ekibini tek ekrandan izleme"
        ]
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
            "Tek tıkla bağlantı testi ve canlı log takibi"
        ]
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
            "Karmaşık menülerden arındırılmış hızlı kasa ekranı"
        ]
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
            "İşletme panelinden tek tıkla onay ve WhatsApp dönüşü"
        ]
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
            "Mobil ekrandan hızlı onay, iptal ve WhatsApp dönüşü"
        ]
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
            "Uygulama indirmeden doğrudan tarayıcıdan çalışma"
        ]
    }
]


def slugify(text):
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    cleaned = text.translate(tr_map).lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
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
    if not price_str:
        return 0.0
    cleaned = re.sub(r"[^0-9.,]", "", str(price_str)).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def get_db():
    parsed = urlparse(DATABASE_URL)
    sslmode = (
        "require"
        if "supabase.co" in (parsed.hostname or "") or "pooler.supabase.com" in (parsed.hostname or "")
        else "prefer"
    )
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, sslmode=sslmode)


def save_uploaded_image(subdir, tenant_id, file_storage):
    if not file_storage or not file_storage.filename:
        return ""
    ext = Path(secure_filename(file_storage.filename)).suffix.lower()
    if ext not in ALLOWED_IMG_EXTS:
        return ""

    raw_bytes = file_storage.read()
    if not raw_bytes:
        return ""

    fname = f"{uuid.uuid4().hex[:12]}{ext}"
    category = subdir.name
    mime_type = file_storage.mimetype or mimetypes.guess_type(fname)[0] or "image/jpeg"

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
                    (tenant_id, category, fname, mime_type, psycopg2.Binary(raw_bytes)),
                )
    except Exception as exc:
        app.logger.error("Veritabani gorsel kayit hatasi: %s", exc)

    try:
        target_dir = subdir / str(tenant_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / fname).write_bytes(raw_bytes)
    except Exception:
        pass

    return fname


def get_stored_image_from_db(tenant_id, category, filename):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content_type, data
                FROM stored_images
                WHERE tenant_id = %s AND category = %s AND filename = %s
                """,
                (tenant_id, category, filename),
            )
            return cur.fetchone()


def init_db():
    try:
        MENU_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        LOGO_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        with get_db() as conn:
            with conn.cursor() as cur:
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
                        is_active BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        activated_at TIMESTAMP
                    );
                    """
                )
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS module_type TEXT NOT NULL DEFAULT 'genel';")
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS table_count INTEGER NOT NULL DEFAULT 8;")
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS logo_filename TEXT DEFAULT '';")
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS payment_note TEXT DEFAULT '';")
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS payment_requested BOOLEAN NOT NULL DEFAULT FALSE;")
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS qr_addon_active BOOLEAN NOT NULL DEFAULT FALSE;")
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS qr_addon_requested BOOLEAN NOT NULL DEFAULT FALSE;")
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS qr_addon_note TEXT DEFAULT '';")
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS bot_config_json TEXT DEFAULT '{}';")
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS activated_at TIMESTAMP;")
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;")
                cur.execute("UPDATE tenants SET plan = 'starter' WHERE plan = 'free';")
                cur.execute(
                    """
                    UPDATE tenants
                    SET expires_at = activated_at + INTERVAL '30 days'
                    WHERE is_active = TRUE AND activated_at IS NOT NULL AND expires_at IS NULL;
                    """
                )

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
                    );
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
                    );
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_menu_tenant_id ON tenant_menu_items(tenant_id);")

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
                    );
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_field_agents_tenant ON field_agents(tenant_id);")

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
                    );
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_pos_products_tenant ON pos_products(tenant_id);")

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
                    );
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_tenant_id ON tickets(tenant_id);")

                cur.execute("SELECT id FROM tenants WHERE slug = %s", ("kolay-vitrin",))
                default_tenant = cur.fetchone()
                if not default_tenant:
                    cur.execute(
                        """
                        INSERT INTO tenants (
                            slug, business_name, owner_email, password_hash, plan, module_type,
                            table_count, whatsapp_number, payment_note, payment_requested, is_active, activated_at, expires_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, 8, %s, %s, FALSE, TRUE, NOW(), NOW() + INTERVAL '365 days')
                        RETURNING id
                        """,
                        (
                            "kolay-vitrin",
                            "KOLAY Otomasyon Ana Vitrin",
                            "iletisim@kolayotomasyon.local",
                            generate_password_hash("kolay1234"),
                            "pro",
                            "genel",
                            WHATSAPP_NUMBER,
                            "Varsayilan aktif vitrin hesabi",
                        ),
                    )
                    default_tenant_id = cur.fetchone()["id"]
                else:
                    default_tenant_id = default_tenant["id"]

                cur.execute("SELECT COUNT(*) AS cnt FROM tickets")
                cnt = cur.fetchone()["cnt"]
                if cnt == 0 and LEGACY_JSON_FILE.exists():
                    try:
                        raw = json.loads(LEGACY_JSON_FILE.read_text(encoding="utf-8"))
                        if isinstance(raw, list):
                            for item in reversed(raw):
                                if isinstance(item, dict) and item.get("name") and item.get("message"):
                                    t_id = str(item.get("id") or uuid.uuid4().hex[:8])
                                    cur.execute(
                                        """
                                        INSERT INTO tickets (id, tenant_id, name, phone, service, message, status, created_at)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                        ON CONFLICT (id) DO NOTHING
                                        """,
                                        (
                                            t_id,
                                            default_tenant_id,
                                            str(item.get("name", "")).strip(),
                                            str(item.get("phone", "")).strip(),
                                            str(item.get("service", "")).strip(),
                                            str(item.get("message", "")).strip(),
                                            str(item.get("status") or "Yeni").strip(),
                                            str(item.get("created_at") or datetime.now().strftime("%d.%m.%Y %H:%M")).strip(),
                                        ),
                                    )
                    except Exception:
                        pass
    except Exception as exc:
        app.logger.error("Veritabani baslatma hatasi: %s", exc)


def tenant_has_qr_access(tenant):
    mod = tenant.get("module_type") or "genel"
    if mod == "masa-qr":
        return True
    if mod == "kafe-randevu":
        return (tenant.get("plan") == "pro") or bool(tenant.get("qr_addon_active"))
    return False


def get_bot_config(tenant):
    raw = tenant.get("bot_config_json") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception:
        data = {}
    return {
        "wa_api_url": data.get("wa_api_url", ""),
        "wa_api_token": data.get("wa_api_token", ""),
        "wa_auto_reply": bool(data.get("wa_auto_reply", False)),
        "tg_bot_token": data.get("tg_bot_token", ""),
        "tg_chat_id": data.get("tg_chat_id", ""),
        "tg_notify_enabled": bool(data.get("tg_notify_enabled", False)),
        "scraper_url": data.get("scraper_url", ""),
        "report_hour": data.get("report_hour", "21:00"),
        "webhook_url": data.get("webhook_url", ""),
        "last_sync_note": data.get("last_sync_note", ""),
    }


def trigger_tenant_integrations(tenant, title, body_text):
    cfg = get_bot_config(tenant)
    if cfg.get("tg_notify_enabled") and cfg.get("tg_bot_token") and cfg.get("tg_chat_id"):
        try:
            tg_url = f"https://api.telegram.org/bot{cfg['tg_bot_token'].strip()}/sendMessage"
            payload = json.dumps({
                "chat_id": cfg["tg_chat_id"].strip(),
                "text": f"🔔 {tenant['business_name']} — {title}\n{body_text}",
            }).encode("utf-8")
            req = urllib.request.Request(tg_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=4)
        except Exception as exc:
            app.logger.warning("Telegram bildirim hatasi: %s", exc)

    if cfg.get("webhook_url"):
        try:
            payload = json.dumps({
                "business": tenant["business_name"],
                "slug": tenant["slug"],
                "title": title,
                "message": body_text,
                "timestamp": datetime.now().isoformat(),
            }).encode("utf-8")
            req = urllib.request.Request(cfg["webhook_url"].strip(), data=payload, headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=4)
        except Exception as exc:
            app.logger.warning("Webhook bildirim hatasi: %s", exc)


def get_tenant_by_slug(slug):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tenants WHERE slug = %s", (slug,))
            return cur.fetchone()


def get_all_tenants():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.*, COUNT(tk.id) AS ticket_count
                FROM tenants t
                LEFT JOIN tickets tk ON tk.tenant_id = t.id
                GROUP BY t.id
                ORDER BY t.is_active ASC, t.payment_requested DESC, t.qr_addon_requested DESC, t.id DESC
                """
            )
            rows = cur.fetchall()
            now = datetime.now()
            enriched = []
            for r in rows:
                d = dict(r)
                exp = d.get("expires_at")
                if exp is None and d.get("activated_at"):
                    exp = d["activated_at"] + timedelta(days=30)
                if exp:
                    delta_days = (exp.date() - now.date()).days
                    d["days_left"] = delta_days
                    d["expires_str"] = exp.strftime("%d.%m.%Y")
                    d["is_expired"] = bool(d.get("is_active")) and delta_days < 0
                else:
                    d["days_left"] = None
                    d["expires_str"] = "-"
                    d["is_expired"] = False
                enriched.append(d)
            return enriched


def create_tenant(business_name, owner_email, password, raw_slug="", plan="starter", module_type="genel", whatsapp_number=""):
    base_slug = slugify(raw_slug or business_name)
    valid_modules = {
        "genel", "kafe-randevu", "berber-randevu", "masa-qr",
        "mobil-saha", "web-otomasyon", "masaustu-otomasyon"
    }
    mod = module_type if module_type in valid_modules else "genel"
    chosen_plan = plan if plan in {"starter", "pro"} else "starter"
    default_tables = 8 if mod in {"kafe-randevu", "masa-qr"} else 4
    with get_db() as conn:
        with conn.cursor() as cur:
            candidate = base_slug
            suffix = 1
            while True:
                cur.execute("SELECT id FROM tenants WHERE slug = %s", (candidate,))
                if not cur.fetchone():
                    break
                suffix += 1
                candidate = f"{base_slug}-{suffix}"

            cur.execute(
                """
                INSERT INTO tenants (
                    slug, business_name, owner_email, password_hash, plan,
                    module_type, table_count, whatsapp_number, is_active, payment_requested, qr_addon_active
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, FALSE, %s)
                RETURNING *
                """,
                (
                    candidate,
                    business_name.strip(),
                    owner_email.strip().lower(),
                    generate_password_hash(password),
                    chosen_plan,
                    mod,
                    default_tables,
                    whatsapp_number.strip(),
                    (chosen_plan == "pro"),
                ),
            )
            return cur.fetchone()


def get_menu_items(tenant_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, name, price, description, image_filename, sort_order
                FROM tenant_menu_items
                WHERE tenant_id = %s
                ORDER BY sort_order ASC, id ASC
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()
            items = []
            for r in rows:
                d = dict(r)
                d["numeric_price"] = parse_price_number(d.get("price"))
                items.append(d)
            return items


def get_field_agents(tenant_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM field_agents
                WHERE tenant_id = %s
                ORDER BY updated_at DESC, id DESC
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()
            out = []
            for r in rows:
                d = dict(r)
                upd = d.get("updated_at")
                d["updated_str"] = upd.strftime("%d.%m.%Y %H:%M:%S") if upd else "-"
                out.append(d)
            return out


def get_pos_products(tenant_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM pos_products
                WHERE tenant_id = %s
                ORDER BY id DESC
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["price_num"] = float(d.get("price") or 0)
                out.append(d)
            return out


def get_booked_tables_by_slot(tenant_id, target_date=None):
    date_str = (target_date or datetime.now().strftime("%Y-%m-%d")).strip()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT service, message, status
                FROM tickets
                WHERE tenant_id = %s AND status != 'İptal'
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()

    booked_tables = {sl: set() for sl in TIME_SLOTS}
    for r in rows:
        txt = f"{r.get('service') or ''} {r.get('message') or ''}"
        if date_str and date_str not in txt:
            continue
        matched_slot = next((sl for sl in TIME_SLOTS if sl in txt), None)
        if not matched_slot:
            continue
        m = re.search(r"Masa\s+(\d+)", txt, flags=re.IGNORECASE)
        if m:
            booked_tables[matched_slot].add(int(m.group(1)))
        else:
            booked_tables[matched_slot].add(len(booked_tables[matched_slot]) + 1)
    return booked_tables


def get_booked_barber_slots(tenant_id, target_date=None):
    date_str = (target_date or datetime.now().strftime("%Y-%m-%d")).strip()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT service, message, status
                FROM tickets
                WHERE tenant_id = %s AND status != 'İptal'
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()

    taken_slots = set()
    for r in rows:
        txt = f"{r.get('service') or ''} {r.get('message') or ''}"
        if date_str in txt:
            for sl in TIME_SLOTS:
                if sl in txt:
                    taken_slots.add(sl)
    return taken_slots


def load_tickets(tenant_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, name, phone, service, message, status, created_at
                FROM tickets
                WHERE tenant_id = %s
                ORDER BY created_at DESC, id DESC
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                clean_p = normalize_phone(d.get("phone"))
                txt = f"Merhaba {d['name']}, talebinizle ilgili donus yapiyorum."
                d["wa_link"] = f"https://wa.me/{clean_p}?text={quote(txt)}" if clean_p else ""
                result.append(d)
            return result


def add_ticket(tenant_id, name, phone, service, message):
    ticket_id = uuid.uuid4().hex[:8]
    created_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tickets (id, tenant_id, name, phone, service, message, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'Yeni', %s)
                """,
                (ticket_id, tenant_id, name, phone, service, message, created_at),
            )
            cur.execute("SELECT * FROM tenants WHERE id = %s", (tenant_id,))
            tn = cur.fetchone()
    if tn:
        trigger_tenant_integrations(tn, f"{service} ({name})", message)


def update_ticket_status(tenant_id, ticket_id, new_status):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tickets SET status = %s WHERE id = %s AND tenant_id = %s",
                (new_status, ticket_id, tenant_id),
            )


def delete_ticket_by_id(tenant_id, ticket_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tickets WHERE id = %s AND tenant_id = %s",
                (ticket_id, tenant_id),
            )


def tenant_login_required(view_func):
    @functools.wraps(view_func)
    def wrapped(slug, *args, **kwargs):
        tenant = get_tenant_by_slug(slug)
        if not tenant:
            abort(404)
        authed_slugs = session.get("tenant_auth_slugs", [])
        if slug not in authed_slugs:
            return redirect(url_for("tenant_login", slug=slug, next=request.path))
        return view_func(slug, *args, **kwargs)

    return wrapped


def superadmin_required(view_func):
    @functools.wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("superadmin_auth"):
            return redirect(url_for("superadmin_login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapped


init_db()

COMMON_WP_SVG = """
<svg style="display:none;" aria-hidden="true">
  <symbol id="icon-whatsapp" viewBox="0 0 24 24">
    <path fill="currentColor" d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.45 1.32 4.95L2.05 22l5.25-1.38c1.45.79 3.08 1.21 4.74 1.21 5.46 0 9.91-4.45 9.91-9.91S17.5 2 12.04 2zm5.82 14.05c-.24.68-1.41 1.3-1.95 1.38-.5.08-1.14.11-1.84-.11-.42-.13-.97-.31-1.67-.61-2.94-1.27-4.86-4.23-5.01-4.43-.15-.2-1.19-1.58-1.19-3.02 0-1.44.75-2.15 1.02-2.44.27-.29.59-.37.79-.37.2 0 .4.01.57.01.18 0 .43-.07.67.51.24.59.83 2.03.9 2.18.07.15.12.32.02.52-.1.2-.15.32-.3.5-.15.17-.31.39-.45.52-.15.15-.3.31-.13.61.17.3.77 1.27 1.65 2.06 1.14 1.02 2.1 1.34 2.4 1.49.3.15.48.12.66-.07.18-.2.76-.89.96-1.19.2-.3.41-.25.69-.15.28.1 1.78.84 2.08.99.3.15.5.22.58.35.07.12.07.72-.17 1.4z"/>
  </symbol>
</svg>
"""

INDEX_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>KOLAY Otomasyon — Mikro-SaaS &amp; Web Sistemleri</title>
  <style>
    :root {
      --bg: #080d0b; --bg-soft: #0f1714; --card: rgba(17, 27, 23, 0.92);
      --text: #f8fafc; --muted: #9ca3af; --accent: #10b981; --accent-bright: #34d399;
      --accent-2: #f59e0b; --border: rgba(16, 185, 129, 0.22);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: "Inter", system-ui, -apple-system, sans-serif; }
    html { scroll-behavior: smooth; max-width: 100%; overflow-x: hidden; }
    body {
      background:
        radial-gradient(circle at 12% 8%, rgba(16, 185, 129, 0.15), transparent 36%),
        radial-gradient(circle at 88% 16%, rgba(245, 158, 11, 0.11), transparent 38%),
        var(--bg);
      color: var(--text); line-height: 1.6; overflow-x: hidden; width: 100%;
    }
    .container { max-width: 1180px; margin: 0 auto; padding: 0 18px; width: 100%; }
    .wp-icon { width: 18px; height: 18px; flex-shrink: 0; display: inline-block; }

    .navbar { position: sticky; top: 0; z-index: 40; backdrop-filter: blur(14px); background: rgba(8, 13, 11, 0.88); border-bottom: 1px solid var(--border); }
    .nav-inner { display: flex; align-items: center; justify-content: space-between; min-height: 68px; padding: 10px 0; gap: 10px; flex-wrap: wrap; }
    .brand { display: inline-flex; align-items: center; gap: 10px; font-weight: 800; font-size: 1rem; color: var(--text); text-decoration: none; }
    .brand-logo-img { height: 38px; width: auto; max-width: 54px; object-fit: contain; border-radius: 10px; display: block; }
    .brand-badge { width: 32px; height: 32px; border-radius: 10px; display: grid; place-items: center; font-weight: 900; color: #04130d; background: linear-gradient(135deg, var(--accent-bright), var(--accent-2)); }
    .brand-text small { display: block; font-size: 0.7rem; font-weight: 600; color: var(--accent-bright); }
    .nav-links { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .nav-btn { color: var(--muted); text-decoration: none; font-size: 0.86rem; font-weight: 600; padding: 8px 11px; border-radius: 10px; border: 1px solid transparent; display: inline-flex; align-items: center; gap: 6px; }
    .nav-btn:hover, .nav-btn.active { color: var(--text); background: rgba(16, 185, 129, 0.12); border-color: rgba(16, 185, 129, 0.32); }
    .nav-cta { color: #04130d; background: linear-gradient(135deg, var(--accent-bright), var(--accent)); font-weight: 800; }
    .nav-wa { color: #dcfce7; background: rgba(34, 197, 94, 0.16); border: 1px solid rgba(34, 197, 94, 0.42); font-weight: 700; }

    .hero { padding: 44px 0 32px; }
    .hero-grid { display: grid; grid-template-columns: 1.25fr 0.75fr; gap: 24px; align-items: center; }
    .badge { display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 999px; font-size: 0.78rem; font-weight: 700; color: var(--accent-bright); background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.28); margin-bottom: 12px; }
    .hero h1 { font-size: clamp(1.75rem, 6vw, 3rem); line-height: 1.15; margin-bottom: 12px; word-break: break-word; }
    .hero h1 span { background: linear-gradient(135deg, var(--accent-bright), var(--accent-2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .hero p { color: var(--muted); font-size: 0.96rem; max-width: 630px; margin-bottom: 20px; }
    .hero-actions { display: flex; gap: 10px; flex-wrap: wrap; }

    .btn-primary, .btn-secondary, .btn-wa {
      text-decoration: none; padding: 11px 16px; border-radius: 11px; font-weight: 700; font-size: 0.88rem;
      display: inline-flex; align-items: center; justify-content: center; gap: 8px; cursor: pointer;
    }
    .btn-primary { background: linear-gradient(135deg, var(--accent-bright), var(--accent)); color: #04130d; border: none; }
    .btn-secondary { background: var(--card); color: var(--text); border: 1px solid var(--border); }
    .btn-wa { background: linear-gradient(135deg, #22c55e, #16a34a); color: #052e16; border: none; }

    .hero-panel { background: linear-gradient(160deg, rgba(19, 32, 27, 0.94), rgba(10, 17, 14, 0.94)); border: 1px solid var(--border); border-radius: 18px; padding: 20px; }
    .panel-title { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-2); margin-bottom: 10px; font-weight: 800; }
    .mini-list { list-style: none; display: grid; gap: 8px; }
    .mini-list li { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; border-radius: 11px; background: rgba(8, 13, 11, 0.65); border: 1px solid rgba(16, 185, 129, 0.14); font-size: 0.85rem; gap: 8px; flex-wrap: wrap; }
    .pill { font-size: 0.72rem; padding: 3px 8px; border-radius: 999px; background: rgba(16, 185, 129, 0.16); color: var(--accent-bright); font-weight: 700; border: 1px solid rgba(16, 185, 129, 0.3); }
    .pill-amber { font-size: 0.72rem; padding: 3px 8px; border-radius: 999px; background: rgba(245, 158, 11, 0.16); color: #fcd34d; font-weight: 700; border: 1px solid rgba(245, 158, 11, 0.36); }

    section.block { padding: 40px 0; }
    .section-head { margin-bottom: 18px; }
    .section-head span { color: var(--accent-2); font-size: 0.78rem; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; }
    .section-head h2 { font-size: clamp(1.4rem, 5vw, 2.05rem); margin-top: 4px; margin-bottom: 6px; }
    .section-head p { color: var(--muted); max-width: 760px; font-size: 0.92rem; }

    .services-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr)); gap: 16px; }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; overflow: hidden; display: flex; flex-direction: column; justify-content: space-between; cursor: pointer; }
    .card:hover { border-color: rgba(16, 185, 129, 0.48); }
    .card-thumb { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; display: block; border-bottom: 1px solid rgba(16, 185, 129, 0.16); }
    .card-body { padding: 16px 18px 10px; }
    .card-tag { display: inline-block; font-size: 0.74rem; font-weight: 700; color: var(--accent-bright); background: rgba(16, 185, 129, 0.12); padding: 4px 9px; border-radius: 8px; margin-bottom: 8px; }
    .card h3 { font-size: 1.05rem; margin-bottom: 6px; }
    .card p { color: var(--muted); font-size: 0.88rem; }
    .card-footer { display: flex; align-items: center; justify-content: space-between; padding: 11px 18px 14px; border-top: 1px solid rgba(156, 163, 175, 0.12); }
    .detail-link { background: transparent; border: none; color: var(--accent-2); font-weight: 700; font-size: 0.88rem; cursor: pointer; }

    .saas-grid { display: grid; grid-template-columns: 1.05fr 0.95fr; gap: 18px; align-items: start; }
    .saas-card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 20px; display: grid; gap: 13px; }
    .iban-box { background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.35); border-radius: 12px; padding: 14px; display: grid; gap: 6px; }
    .iban-code { font-family: monospace; font-size: 0.88rem; font-weight: 800; color: #fcd34d; background: rgba(0, 0, 0, 0.35); padding: 8px 10px; border-radius: 8px; word-break: break-all; }
    .row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    label { display: block; font-size: 0.84rem; color: #d1d5db; margin-bottom: 5px; font-weight: 600; }
    input, select, textarea { width: 100%; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--border); background: var(--bg-soft); color: var(--text); font-size: 0.92rem; }
    .submit-btn { padding: 12px 16px; border-radius: 11px; border: none; cursor: pointer; font-weight: 800; font-size: 0.92rem; color: #04130d; background: linear-gradient(135deg, var(--accent-bright), var(--accent-2)); width: 100%; }
    .alert-ok { padding: 13px 15px; border-radius: 12px; background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); color: #a7f3d0; font-size: 0.88rem; word-break: break-word; }
    .alert-err { padding: 13px 15px; border-radius: 12px; background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); color: #fca5a5; font-size: 0.88rem; }

    .modal-backdrop { position: fixed; inset: 0; z-index: 90; background: rgba(4, 8, 6, 0.78); backdrop-filter: blur(8px); display: none; align-items: center; justify-content: center; padding: 14px; }
    .modal-backdrop.open { display: flex; }
    .modal-box { width: 100%; max-width: 580px; max-height: 90vh; overflow-y: auto; background: #101915; border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 18px; padding: 20px; }
    .modal-img { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 12px; margin: 12px 0; }
    .modal-list { list-style: none; display: grid; gap: 8px; margin: 12px 0 16px; }
    .modal-list li { padding: 9px 12px; border-radius: 10px; background: rgba(8, 13, 11, 0.72); border: 1px solid rgba(16, 185, 129, 0.16); font-size: 0.88rem; }

    footer { border-top: 1px solid var(--border); padding: 22px 0; margin-top: 24px; color: var(--muted); font-size: 0.86rem; }
    .footer-inner { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
    footer a { color: var(--muted); text-decoration: none; }

    @media (max-width: 860px) {
      .hero-grid, .saas-grid, .row-2 { grid-template-columns: 1fr; }
      .nav-links { width: 100%; justify-content: flex-start; }
      .hero-actions { flex-direction: column; }
      .hero-actions a, .hero-actions button { width: 100%; }
    }
  </style>
</head>
<body>
""" + COMMON_WP_SVG + """
  <header class="navbar">
    <div class="container nav-inner">
      <a href="#anasayfa" class="brand">
        <img src="/images/logo.png" alt="KOLAY Otomasyon" class="brand-logo-img" onerror="if(!this.dataset.fb){this.dataset.fb='1';this.src='/logo.png';}else{this.style.display='none';document.getElementById('fallbackBadge').style.display='grid';}" />
        <span id="fallbackBadge" class="brand-badge" style="display: none;">K</span>
        <span class="brand-text">KOLAY <small>Mikro-SaaS &amp; Web Sistemleri</small></span>
      </a>
      <nav class="nav-links">
        <a href="#anasayfa" class="nav-btn active">Anasayfa</a>
        <a href="#hizmetler" class="nav-btn">Modüller</a>
        <a href="#saas-basla" class="nav-btn nav-cta">Hesap Aç &amp; IBAN</a>
        <a href="https://wa.me/{{ wa_number }}?text={{ 'Merhaba KOLAY Otomasyon, IBAN odeme ve paketler hakkinda bilgi almak istiyorum.' | urlencode }}" target="_blank" rel="noopener noreferrer" class="nav-btn nav-wa" aria-label="WhatsApp">
          <svg class="wp-icon"><use href="#icon-whatsapp"></use></svg>
          <span>WhatsApp</span>
        </a>
      </nav>
    </div>
  </header>

  <main>
    <section id="anasayfa" class="hero">
      <div class="container hero-grid">
        <div>
          <div class="badge">IBAN Ödemeli Mikro-SaaS</div>
          <h1>İşletmen İçin <span>Kendi Panelini Aç</span>, Ödeme Onayıyla Aktif Et</h1>
          <p>
            İşletme hesabını oluştur, seçtiğin modül kilitli olarak tanımlansın, IBAN üzerinden ödemeni yap ve onaylandığında
            müşteri linkin ile işletme yönetim panelin hemen aktif olsun.
          </p>
          <div class="hero-actions">
            <a href="#saas-basla" class="btn-primary">İşletme Hesabı Oluştur</a>
            <a href="https://wa.me/{{ wa_number }}?text={{ 'Merhaba KOLAY Otomasyon, yeni hesap acmak istiyorum.' | urlencode }}" target="_blank" rel="noopener noreferrer" class="btn-wa" aria-label="WhatsApp">
              <svg class="wp-icon"><use href="#icon-whatsapp"></use></svg>
              <span>WhatsApp</span>
            </a>
          </div>
        </div>

        <aside class="hero-panel">
          <div class="panel-title">Paket &amp; Aktivasyon Akışı</div>
          <ul class="mini-list">
            <li><span>Starter Paket (Temel Modül)</span><span class="pill">{{ price_starter }}</span></li>
            <li><span>Pro Paket (Masa QR Dahil)</span><span class="pill-amber">{{ price_pro }}</span></li>
            <li><span>Starter'da Masa QR Kilidi</span><span class="pill-amber">+{{ qr_addon_price }} Ek Açılım</span></li>
            <li><span>Aktivasyon</span><span class="pill">IBAN Onayı Sonrası</span></li>
          </ul>
        </aside>
      </div>
    </section>

    <section id="hizmetler" class="block">
      <div class="container">
        <div class="section-head">
          <span>Modüller</span>
          <h2>İşletmene Uygun Çözümleri İncele</h2>
          <p>Tüm modüller hazır ve çalışır durumdadır. Kartlara tıklayarak detayları inceleyip doğrudan o modülle hesap açabilirsin.</p>
        </div>

        <div class="services-grid">
          {% for srv in services %}
          <article class="card" onclick="openServiceModal('{{ srv.id }}')">
            <div>
              {% if srv.image %}
              <img src="/images/{{ srv.image }}" alt="{{ srv.tag }}" class="card-thumb" onerror="this.style.display='none'" />
              {% endif %}
              <div class="card-body">
                <span class="card-tag">{{ srv.tag }}</span>
                <h3>{{ srv.title }}</h3>
                <p>{{ srv.short }}</p>
              </div>
            </div>
            <div class="card-footer">
              <span style="font-size: 0.8rem; color: var(--muted);">Detayları gör</span>
              <button type="button" class="detail-link">İncele →</button>
            </div>
          </article>
          {% endfor %}
        </div>
      </div>
    </section>

    <section id="saas-basla" class="block">
      <div class="container">
        <div class="section-head">
          <span>Hesap Açma &amp; IBAN Ödeme</span>
          <h2>Yeni İşletme Hesabı Oluştur veya Paneline Gir</h2>
          <p>Starter pakette kafe randevu açarsan Masa QR kısmı panelde kilitli gelir (+{{ qr_addon_price }} ile açılır); Pro pakette ise baştan açıktır.</p>
        </div>

        {% if created_tenant %}
        <div class="alert-ok" style="margin-bottom: 16px;">
          <strong>{{ created_tenant.business_name }}</strong> (<code>/i/{{ created_tenant.slug }}</code>) hesabı oluşturuldu!
          Durumu: <strong>{% if created_tenant.is_active %}AKTİF{% else %}ÖDEME ONAYI BEKLİYOR{% endif %}</strong>.
          Panel: <a href="{{ url_for('tenant_panel', slug=created_tenant.slug) }}" style="color:#fff;text-decoration:underline;">/i/{{ created_tenant.slug }}/panel</a>
        </div>
        {% endif %}

        {% if saas_error %}
        <div class="alert-err" style="margin-bottom: 16px;">{{ saas_error }}</div>
        {% endif %}

        <div class="saas-grid">
          <form class="saas-card" method="POST" action="{{ url_for('register_tenant') }}">
            <div>
              <h3 style="font-size: 1.12rem; margin-bottom: 4px;">Yeni İşletme Hesabı Aç</h3>
              <p style="color: var(--muted); font-size: 0.86rem;">Seçtiğin modül üyelik sonrası panelden değiştirilemez şekilde kilitlenir.</p>
            </div>

            <div class="row-2">
              <div>
                <label for="business_name">İşletme Adı</label>
                <input id="business_name" type="text" name="business_name" placeholder="Örn: Yıldız Kafe" required />
              </div>
              <div>
                <label for="slug">Özel URL Adresi (Slug)</label>
                <input id="slug" type="text" name="slug" placeholder="Örn: yildiz-kafe" />
              </div>
            </div>

            <div class="row-2">
              <div>
                <label for="owner_email">E-posta</label>
                <input id="owner_email" type="email" name="owner_email" placeholder="sahip@isletme.com" required />
              </div>
              <div>
                <label for="whatsapp_number">İşletme WhatsApp (Opsiyonel)</label>
                <input id="whatsapp_number" type="text" name="whatsapp_number" placeholder="05xx xxx xx xx" />
              </div>
            </div>

            <div class="row-2">
              <div>
                <label for="password">Panel Şifresi</label>
                <input id="password" type="password" name="password" placeholder="En az 4 karakter" required />
              </div>
              <div>
                <label for="plan">Paket Seçimi</label>
                <select id="plan" name="plan">
                  <option value="starter">Starter — {{ price_starter }} (Masa QR Kilitli)</option>
                  <option value="pro">Pro — {{ price_pro }} (Tüm Özellikler Açık)</option>
                </select>
              </div>
            </div>

            <div>
              <label for="module_type">Modül Seçimi (Üyelik Sonrası Kilitlenir)</label>
              <select id="module_type" name="module_type">
                <option value="kafe-randevu">Kafe &amp; Restoran Masa Randevu + Masa QR</option>
                <option value="masa-qr">Masa QR Menü, Sipariş &amp; Garson Çağır</option>
                <option value="berber-randevu">Berber &amp; Kuaför Saat Randevu</option>
                <option value="mobil-saha">Mobil Uygulama &amp; Saha Akışları</option>
                <option value="web-otomasyon">Web Panelleri, Formlar &amp; Botlar</option>
                <option value="masaustu-otomasyon">Masaüstü Kasa, Barkod &amp; Stok Otomasyonu</option>
                <option value="genel">Genel Talep / Müşteri Formu</option>
              </select>
            </div>

            <div class="iban-box">
              <strong style="color: #fcd34d; font-size: 0.88rem;">IBAN Ödeme Bilgileri</strong>
              <span style="font-size: 0.82rem; color: #e5e7eb;">Alıcı: <strong>{{ iban_holder }}</strong> • Banka: {{ iban_bank }}</span>
              <div class="iban-code">{{ iban_number }}</div>
              <span style="font-size: 0.78rem; color: var(--muted);">Açıklamaya işletme adını yazarak ödeme yapabilirsin.</span>
            </div>

            <button type="submit" class="submit-btn">Hesabı Oluştur (Onaya Gönder)</button>
          </form>

          <form class="saas-card" method="POST" action="{{ url_for('tenant_quick_login') }}">
            <div>
              <h3 style="font-size: 1.12rem; margin-bottom: 4px;">İşletme Paneline Giriş</h3>
              <p style="color: var(--muted); font-size: 0.86rem;">Ödeme durumunu görmek veya aktif panelini yönetmek için giriş yap.</p>
            </div>

            <div>
              <label for="login_slug">İşletme Slug</label>
              <input id="login_slug" type="text" name="slug" placeholder="kolay-vitrin" required />
            </div>

            <div>
              <label for="login_password">Şifre</label>
              <input id="login_password" type="password" name="password" required />
            </div>

            <button type="submit" class="btn-secondary" style="width:100%;padding:12px 16px;">İşletme Paneline Gir</button>

            <div class="iban-box">
              <strong style="color: var(--accent-bright); font-size: 0.86rem;">Hızlı Erişim Bilgisi</strong>
              <span style="font-size: 0.82rem; color: var(--muted);">Örnek müşteri linki: <a href="{{ url_for('tenant_public', slug='kolay-vitrin') }}" style="color: var(--accent-bright);">/i/kolay-vitrin</a></span>
              <span style="font-size: 0.82rem; color: var(--muted);">Örnek panel: <a href="{{ url_for('tenant_panel', slug='kolay-vitrin') }}" style="color: var(--accent-bright);">/i/kolay-vitrin/panel</a> (Şifre: <code>kolay1234</code>)</span>
            </div>
          </form>
        </div>
      </div>
    </section>
  </main>

  <footer>
    <div class="container footer-inner">
      <span>© 2026 KOLAY Otomasyon Mikro-SaaS</span>
      <span>
        <a href="#anasayfa">Anasayfa</a> •
        <a href="#hizmetler">Modüller</a> •
        <a href="#saas-basla">Hesap Aç</a>
      </span>
    </div>
  </footer>

  <div id="serviceModal" class="modal-backdrop" onclick="if(event.target.id==='serviceModal')closeServiceModal()">
    <div class="modal-box">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span id="modalTag" class="card-tag" style="margin-bottom:0;">Modül</span>
        <button type="button" onclick="closeServiceModal()" style="background:none;border:1px solid rgba(255,255,255,0.2);color:#fff;width:34px;height:34px;border-radius:8px;cursor:pointer;">✕</button>
      </div>
      <img id="modalImg" src="" alt="" class="modal-img" onerror="this.style.display='none'" />
      <h3 id="modalTitle">Başlık</h3>
      <p id="modalDesc" style="color:#d1d5db;font-size:0.9rem;margin-top:8px;"></p>
      <ul id="modalFeatures" class="modal-list"></ul>
      <div style="display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap;">
        <button type="button" class="btn-secondary" onclick="closeServiceModal()">Kapat</button>
        <a href="#saas-basla" id="modalSelectBtn" class="btn-primary" onclick="selectModuleAndClose()">Bu Modülle Hesap Aç</a>
      </div>
    </div>
  </div>

  <script>
    const SERVICES = {{ services | tojson }};
    let currentModalModule = "kafe-randevu";
    function openServiceModal(id) {
      const item = SERVICES.find(s => s.id === id);
      if (!item) return;
      currentModalModule = item.module_key || "genel";
      document.getElementById("modalTag").textContent = item.tag;
      document.getElementById("modalTitle").textContent = item.title;
      document.getElementById("modalDesc").textContent = item.details;
      const img = document.getElementById("modalImg");
      if (item.image) { img.style.display = "block"; img.src = `/images/${item.image}`; }
      const ul = document.getElementById("modalFeatures");
      ul.innerHTML = "";
      item.features.forEach(f => { const li = document.createElement("li"); li.textContent = f; ul.appendChild(li); });
      document.getElementById("serviceModal").classList.add("open");
    }
    function selectModuleAndClose() {
      const sel = document.getElementById("module_type");
      if (sel && currentModalModule) sel.value = currentModalModule;
      closeServiceModal();
    }
    function closeServiceModal() { document.getElementById("serviceModal").classList.remove("open"); }
  </script>
</body>
</html>
"""

TENANT_PENDING_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{{ tenant.business_name }} — Ödeme Onayı Bekleniyor</title>
  <style>
    * { box-sizing:border-box; margin:0; padding:0; }
    body { background:#080d0b; color:#f8fafc; font-family:Inter,system-ui,sans-serif; padding:22px 14px; overflow-x:hidden; }
    .wrap { max-width:680px; margin:0 auto; display:grid; gap:16px; }
    .card { background:#121d18; border:1px solid rgba(245,158,11,0.35); border-radius:16px; padding:20px; display:grid; gap:13px; }
    .iban { font-family:monospace; font-size:0.9rem; font-weight:800; color:#fcd34d; background:#09100d; padding:10px 12px; border-radius:10px; border:1px solid rgba(245,158,11,0.3); word-break:break-all; }
    input { width:100%; padding:10px 12px; border-radius:10px; border:1px solid rgba(16,185,129,0.25); background:#0f1714; color:#f8fafc; }
    button, a.btn { text-decoration:none; padding:11px 16px; border-radius:10px; font-weight:800; font-size:0.9rem; border:none; cursor:pointer; display:inline-flex; align-items:center; justify-content:center; width:100%; }
    .btn-gold { background:linear-gradient(135deg,#fbbf24,#f59e0b); color:#1f1300; }
    .btn-ghost { background:#0f1714; color:#34d399; border:1px solid rgba(16,185,129,0.3); }
    .ok { padding:12px; border-radius:10px; background:rgba(16,185,129,0.16); color:#a7f3d0; font-size:0.88rem; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div style="font-size:0.78rem;color:#fbbf24;font-weight:800;">HESAP DURUMU: ÖDEME ONAYI / YENİLEME BEKLENİYOR</div>
      <h1 style="font-size:1.28rem;">{{ tenant.business_name }}</h1>
      <p style="color:#9ca3af;font-size:0.88rem;">
        Hesabın modülü <strong>{{ mod_label }}</strong> olarak tanımlı.
        IBAN ödemesi onaylandığında müşteri linkin ve panelin aktif olur.
      </p>

      {% if notified %}
      <div class="ok">Ödeme bildirimin kaydedildi! Onaydan sonra hesabın aktif olacak.</div>
      {% elif tenant.payment_requested %}
      <div class="ok">Ödeme bildiriminiz iletilmiş durumda ({{ tenant.payment_note or 'Not girilmedi' }}). Onay bekleniyor.</div>
      {% endif %}

      <div style="font-size:0.86rem;color:#e5e7eb;display:grid;gap:4px;">
        <div><strong>Alıcı:</strong> {{ iban_holder }}</div>
        <div><strong>Banka:</strong> {{ iban_bank }}</div>
        <div><strong>Paket:</strong> {{ tenant.plan|upper }} ({{ price_pro if tenant.plan == 'pro' else price_starter }})</div>
        <div><strong>Kilitli Modül:</strong> {{ mod_label }}</div>
      </div>
      <div class="iban">{{ iban_number }}</div>

      <form method="POST" action="{{ url_for('notify_iban_payment', slug=tenant.slug) }}" style="display:grid;gap:10px;">
        <label style="font-size:0.84rem;color:#d1d5db;">Gönderen Adı / Dekont Notu</label>
        <input type="text" name="payment_note" value="{{ tenant.payment_note or '' }}" placeholder="Örn: Ahmet Yılmaz - FAST ile gönderildi" required />
        <button type="submit" class="btn-gold">Ödeme Yaptım / Onaya Bildir</button>
      </form>

      <a class="btn btn-ghost" href="https://wa.me/{{ wa_number }}?text={{ ('Merhaba, ' + tenant.business_name + ' (' + tenant.slug + ') icin IBAN odemesi yaptim, onay rica ederim.') | urlencode }}" target="_blank" rel="noopener noreferrer">WhatsApp'tan Yaz</a>
    </div>
  </div>
</body>
</html>
"""

# SAHA ELEMANI CANLI KONUM & ŞARJ SAYFASI (/i/<slug>/saha)
FIELD_AGENT_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>{{ tenant.business_name }} — Saha Elemanı Canlı Akış</title>
  <style>
    * { box-sizing:border-box; margin:0; padding:0; font-family:Inter,system-ui,sans-serif; }
    body { background:#080d0b; color:#f8fafc; padding:18px 14px 40px; }
    .wrap { max-width:540px; margin:0 auto; display:grid; gap:14px; }
    .card { background:#121d18; border:1px solid rgba(16,185,129,0.28); border-radius:16px; padding:18px; display:grid; gap:12px; }
    .badge { font-size:0.74rem; color:#34d399; background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.3); padding:4px 10px; border-radius:999px; font-weight:800; display:inline-block; }
    label { display:block; font-size:0.82rem; color:#d1d5db; margin-bottom:5px; font-weight:600; }
    input, select { width:100%; padding:11px 12px; border-radius:10px; border:1px solid rgba(16,185,129,0.25); background:#0f1714; color:#f8fafc; font-size:0.92rem; }
    .btn-active { padding:14px; border-radius:12px; border:none; background:linear-gradient(135deg,#34d399,#10b981); color:#04130d; font-weight:900; font-size:0.96rem; cursor:pointer; width:100%; }
    .btn-stop { padding:11px; border-radius:11px; border:1px solid rgba(239,68,68,0.4); background:rgba(239,68,68,0.15); color:#fca5a5; font-weight:800; font-size:0.86rem; cursor:pointer; width:100%; display:none; }
    .telemetry { background:#0f1714; border:1px solid rgba(16,185,129,0.2); border-radius:12px; padding:12px; display:grid; gap:6px; font-size:0.84rem; }
    .dot { display:inline-block; width:9px; height:9px; border-radius:50%; background:#f59e0b; margin-right:6px; }
    .dot.live { background:#10b981; box-shadow:0 0 10px #10b981; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div>
        <span class="badge">Mobil Saha Ekibi Terminali</span>
        <h1 style="font-size:1.3rem;margin-top:6px;">{{ tenant.business_name }}</h1>
        <p style="font-size:0.82rem;color:#9ca3af;margin-top:3px;">Sahayı aktif ettiğinizde konum, batarya/şarj durumu, aktif paket ve müşteri bilgisi merkeze canlı aktarılır.</p>
      </div>

      <div>
        <label>Saha Elemanı Adı Soyadı</label>
        <input type="text" id="agentName" placeholder="Örn: Emre Kaya (Kurye 1)" required />
      </div>

      <div>
        <label>Üzerindeki Aktif Paket / Sipariş Kodu</label>
        <input type="text" id="activePackage" placeholder="Örn: #PKT-402 (2 Koli Ürün)" />
      </div>

      <div>
        <label>Gidilen Müşteri / Adres</label>
        <input type="text" id="targetCustomer" placeholder="Örn: Ahmet Yılmaz — Çekmeköy Merkez" />
      </div>

      <div>
        <label>Saha Durumu</label>
        <select id="statusText">
          <option value="Yolda / Müşteriye Gidiyor">🚚 Yolda / Müşteriye Gidiyor</option>
          <option value="Müşteri Kapısında">📍 Müşteri Kapısında</option>
          <option value="Teslimat Tamamlandı">✅ Teslimat Tamamlandı</option>
          <option value="Merkeze Dönüyor">🔄 Merkeze Dönüyor</option>
        </select>
      </div>

      <button type="button" class="btn-active" id="startBtn" onclick="activateFieldMode()">📡 Sahayı Aktif Et (Konum &amp; İzinleri Onayla)</button>
      <button type="button" class="btn-stop" id="stopBtn" onclick="stopFieldMode()">⏹️ Sahayı Durdur</button>

      <div class="telemetry">
        <div><span class="dot" id="liveDot"></span><strong id="stateLabel">Beklemede (Pasif)</strong></div>
        <div>🔋 Şarj Durumu: <strong id="batLabel">Ölçülmedi</strong></div>
        <div>📍 Konum: <strong id="locLabel">İzin bekleniyor</strong></div>
        <div>🕒 Son Gönderim: <strong id="timeLabel">-</strong></div>
      </div>
    </div>
  </div>

  <script>
    let watchId = null;
    let pushTimer = null;
    let latestLat = "";
    let latestLng = "";
    let batteryPct = -1;
    let isCharging = false;

    async function readBattery() {
      try {
        if (navigator.getBattery) {
          const b = await navigator.getBattery();
          batteryPct = Math.round(b.level * 100);
          isCharging = Boolean(b.charging);
          document.getElementById("batLabel").textContent = `%${batteryPct} ${isCharging ? "(Şarj Oluyor ⚡)" : ""}`;
        } else {
          document.getElementById("batLabel").textContent = "Tarayıcı desteklemiyor";
        }
      } catch (e) {}
    }

    async function sendTelemetry() {
      const name = document.getElementById("agentName").value.trim();
      if (!name) return;
      await readBattery();
      try {
        await fetch("{{ url_for('field_agent_ping', slug=tenant.slug) }}", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            agent_name: name,
            active_package: document.getElementById("activePackage").value.trim(),
            target_customer: document.getElementById("targetCustomer").value.trim(),
            status_text: document.getElementById("statusText").value,
            battery_level: batteryPct,
            is_charging: isCharging,
            latitude: latestLat,
            longitude: latestLng
          })
        });
        document.getElementById("timeLabel").textContent = new Date().toLocaleTimeString("tr-TR");
      } catch (err) {}
    }

    async function activateFieldMode() {
      const name = document.getElementById("agentName").value.trim();
      if (!name) {
        alert("Lütfen önce adınızı soyadınızı yazın.");
        return;
      }

      if ("Notification" in window && Notification.permission === "default") {
        try { await Notification.requestPermission(); } catch (e) {}
      }

      await readBattery();

      if (!navigator.geolocation) {
        alert("Cihazınızda konum servisi bulunamadı.");
        return;
      }

      document.getElementById("stateLabel").textContent = "Konum izni isteniyor...";
      watchId = navigator.geolocation.watchPosition(
        (pos) => {
          latestLat = pos.coords.latitude.toFixed(6);
          latestLng = pos.coords.longitude.toFixed(6);
          document.getElementById("locLabel").textContent = `${latestLat}, ${latestLng}`;
          document.getElementById("stateLabel").textContent = "SAHA AKTİF — Canlı Yayın Yapılıyor";
          document.getElementById("liveDot").classList.add("live");
          document.getElementById("startBtn").style.display = "none";
          document.getElementById("stopBtn").style.display = "block";
          sendTelemetry();
        },
        (err) => {
          alert("Konum izni reddedildi veya alınamadı: " + err.message);
          document.getElementById("stateLabel").textContent = "Konum İzni Gerekli";
        },
        { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 }
      );

      if (pushTimer) clearInterval(pushTimer);
      pushTimer = setInterval(sendTelemetry, 12000);
    }

    function stopFieldMode() {
      if (watchId !== null) navigator.geolocation.clearWatch(watchId);
      if (pushTimer) clearInterval(pushTimer);
      watchId = null;
      pushTimer = null;
      document.getElementById("liveDot").classList.remove("live");
      document.getElementById("stateLabel").textContent = "Durduruldu (Pasif)";
      document.getElementById("startBtn").style.display = "block";
      document.getElementById("stopBtn").style.display = "none";
    }
  </script>
</body>
</html>
"""

# ÖZEL MASA QR EKRANI (/i/<slug>/qr)
TENANT_QR_ORDER_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>{{ tenant.business_name }} — Masa QR Menü &amp; Sipariş</title>
  <style>
    * { box-sizing:border-box; margin:0; padding:0; }
    body { background:#080d0b; color:#f8fafc; font-family:Inter,system-ui,sans-serif; padding:18px 14px 104px; overflow-x:hidden; }
    .wrap { max-width:920px; margin:0 auto; display:grid; gap:15px; }
    .top { display:flex; justify-content:space-between; align-items:center; gap:12px; border-bottom:1px solid rgba(16,185,129,0.22); padding-bottom:14px; }
    .brand-row { display:flex; align-items:center; gap:12px; min-width:0; }
    .biz-logo { width:48px; height:48px; border-radius:12px; object-fit:cover; border:1px solid rgba(16,185,129,0.35); background:#0f1714; flex-shrink:0; display:block; }
    .biz-logo-fallback { width:48px; height:48px; border-radius:12px; display:grid; place-items:center; font-weight:900; font-size:1.1rem; color:#04130d; background:linear-gradient(135deg,#34d399,#10b981); flex-shrink:0; }
    .badge { font-size:0.74rem; color:#34d399; background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.28); padding:3px 9px; border-radius:999px; font-weight:700; display:inline-block; margin-bottom:4px; }
    .card { background:#121d18; border:1px solid rgba(16,185,129,0.22); border-radius:16px; padding:16px; display:grid; gap:13px; }
    .ok { padding:13px 15px; border-radius:12px; background:rgba(16,185,129,0.18); border:1px solid rgba(16,185,129,0.45); color:#a7f3d0; font-weight:700; font-size:0.9rem; }
    label { display:block; font-size:0.84rem; color:#d1d5db; margin-bottom:5px; font-weight:600; }
    select, textarea { width:100%; padding:10px 12px; border-radius:10px; border:1px solid rgba(16,185,129,0.22); background:#0f1714; color:#f8fafc; font-size:0.92rem; }
    .btn-main { text-decoration:none; padding:12px 16px; border-radius:11px; font-weight:800; font-size:0.92rem; background:linear-gradient(135deg,#34d399,#10b981); color:#04130d; border:none; cursor:pointer; display:inline-flex; align-items:center; justify-content:center; width:100%; }
    .quick-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .q-btn {
      padding:14px 12px; border-radius:13px; font-weight:800; font-size:0.9rem;
      border:1px solid rgba(245,158,11,0.42); background:rgba(245,158,11,0.14); color:#fcd34d;
      cursor:pointer; display:flex; align-items:center; justify-content:center; gap:7px; width:100%;
    }
    .q-btn.bill { border-color:rgba(59,130,246,0.45); background:rgba(59,130,246,0.15); color:#93c5fd; }
    .menu-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(215px,1fr)); gap:12px; }
    .menu-card { background:#0f1714; border:1px solid rgba(16,185,129,0.2); border-radius:14px; padding:12px; display:flex; flex-direction:column; justify-content:space-between; gap:10px; }
    .menu-img { width:100%; aspect-ratio:16/10; object-fit:cover; border-radius:9px; display:block; }
    .qty-bar { display:flex; align-items:center; justify-content:space-between; background:#121d18; border:1px solid rgba(16,185,129,0.25); border-radius:10px; padding:5px 8px; }
    .qty-btn { width:34px; height:34px; border-radius:8px; border:none; background:#10b981; color:#04130d; font-weight:900; font-size:1.1rem; cursor:pointer; }
    .qty-btn.minus { background:#1e293b; color:#f8fafc; }
    .cart-bar {
      position:fixed; bottom:0; left:0; right:0; z-index:50;
      background:rgba(12,21,17,0.97); backdrop-filter:blur(14px);
      border-top:1px solid rgba(52,211,153,0.45); padding:12px 16px;
      display:none; justify-content:space-between; align-items:center; gap:12px;
    }
    .cart-bar.show { display:flex; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div class="brand-row">
        {% if tenant.logo_filename %}
          <img src="/images/logos/{{ tenant.id }}/{{ tenant.logo_filename }}" alt="{{ tenant.business_name }}" class="biz-logo" onerror="this.style.display='none';document.getElementById('bizFallbackQr').style.display='grid';" />
          <div id="bizFallbackQr" class="biz-logo-fallback" style="display:none;">{{ tenant.business_name[:1]|upper }}</div>
        {% else %}
          <div class="biz-logo-fallback">{{ tenant.business_name[:1]|upper }}</div>
        {% endif %}
        <div style="min-width:0;">
          <div class="badge">Masa QR Menü &amp; Sipariş</div>
          <h1 style="font-size:1.38rem;word-break:break-word;">{{ tenant.business_name }}</h1>
        </div>
      </div>
    </div>

    {% if sent %}
    <div class="ok">{{ sent_msg }}</div>
    {% endif %}

    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
        <div>
          <span style="font-size:0.74rem;color:#9ca3af;font-weight:700;">OTURDUĞUNUZ MASA</span>
          <div style="font-size:1.2rem;font-weight:900;color:#34d399;">
            {{ preselected_masa if preselected_masa else 'Masa 1' }}
          </div>
        </div>
        {% if not preselected_masa %}
        <div style="min-width:150px;">
          <select id="activeMasaSelect" onchange="syncMasaInputs(this.value)">
            {% for m_idx in range(1, (tenant.table_count or 8) + 1) %}
            <option value="Masa {{ m_idx }}">Masa {{ m_idx }}</option>
            {% endfor %}
          </select>
        </div>
        {% endif %}
      </div>

      <div class="quick-grid">
        <form method="POST" action="{{ url_for('tenant_qr_order_page', slug=tenant.slug) }}">
          <input type="hidden" name="action_type" value="garson" />
          <input type="hidden" name="masa_name" class="masa-hidden-input" value="{{ preselected_masa or 'Masa 1' }}" />
          <button type="submit" class="q-btn">🔔 Garson Çağır</button>
        </form>
        <form method="POST" action="{{ url_for('tenant_qr_order_page', slug=tenant.slug) }}">
          <input type="hidden" name="action_type" value="hesap" />
          <input type="hidden" name="masa_name" class="masa-hidden-input" value="{{ preselected_masa or 'Masa 1' }}" />
          <button type="submit" class="q-btn bill">💳 Hesap İste</button>
        </form>
      </div>
    </div>

    <form class="card" method="POST" action="{{ url_for('tenant_qr_order_page', slug=tenant.slug) }}" id="qrOrderForm">
      <input type="hidden" name="action_type" value="siparis" />
      <input type="hidden" name="masa_name" class="masa-hidden-input" value="{{ preselected_masa or 'Masa 1' }}" />
      <input type="hidden" name="order_summary" id="orderSummaryInput" value="" />

      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;">
        <h2 style="font-size:1.1rem;">🍽️ Dijital Menü &amp; Sipariş</h2>
        <span style="font-size:0.8rem;color:#9ca3af;">Ürün seçip masanıza sipariş verin</span>
      </div>

      {% if menu_items %}
      <div class="menu-grid">
        {% for item in menu_items %}
        <div class="menu-card">
          <div>
            {% if item.image_filename %}
              <img src="/images/menu/{{ tenant.id }}/{{ item.image_filename }}" alt="{{ item.name }}" class="menu-img" onerror="this.style.display='none'" />
            {% endif %}
            <div style="margin-top:8px;">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:6px;">
                <strong style="font-size:0.96rem;">{{ item.name }}</strong>
                {% if item.price %}<span style="color:#34d399;font-weight:800;white-space:nowrap;">{{ item.price }}</span>{% endif %}
              </div>
              {% if item.description %}
              <p style="font-size:0.8rem;color:#9ca3af;margin-top:4px;">{{ item.description }}</p>
              {% endif %}
            </div>
          </div>

          <div class="qty-bar">
            <button type="button" class="qty-btn minus" onclick="changeQty({{ item.id }}, -1)">−</button>
            <span id="qty-{{ item.id }}" style="font-weight:800;font-size:0.96rem;">0</span>
            <button type="button" class="qty-btn" onclick="changeQty({{ item.id }}, 1)">+</button>
          </div>
        </div>
        {% endfor %}
      </div>
      {% else %}
      <div style="padding:14px;border-radius:12px;background:#0f1714;color:#9ca3af;font-size:0.86rem;">
        İşletme henüz menü ürünü eklemedi. Aşağıdaki not alanından doğrudan siparişinizi yazabilirsiniz.
      </div>
      {% endif %}

      <div>
        <label>Sipariş Notu / Özel İstek (Opsiyonel)</label>
        <textarea name="message" id="qrOrderNote" rows="2" placeholder="Örn: Şekersiz olsun, buzlu gelsin veya menü dışı istek..."></textarea>
      </div>

      <button type="submit" class="btn-main" onclick="return prepareQrOrder()">Siparişi Gönder</button>
    </form>

    <div class="cart-bar" id="floatingCartBar">
      <div>
        <div style="font-size:0.75rem;color:#9ca3af;">Seçilen Ürünler (<span id="cartCount">0</span> adet)</div>
        <strong style="font-size:1.05rem;color:#34d399;" id="cartTotalText">0 TL</strong>
      </div>
      <button type="button" class="btn-main" style="width:auto;padding:11px 18px;" onclick="submitFloatingOrder()">Siparişi Onayla →</button>
    </div>
  </div>

  <script>
    const QR_MENU = {{ menu_items | tojson }};
    const cart = {};

    function syncMasaInputs(val) {
      document.querySelectorAll('.masa-hidden-input').forEach(el => el.value = val);
    }

    function changeQty(id, delta) {
      const cur = cart[id] || 0;
      const next = Math.max(0, cur + delta);
      cart[id] = next;
      const lbl = document.getElementById('qty-' + id);
      if (lbl) lbl.textContent = next;
      renderCartSummary();
    }

    function renderCartSummary() {
      let count = 0;
      let total = 0;
      QR_MENU.forEach(item => {
        const q = cart[item.id] || 0;
        if (q > 0) {
          count += q;
          total += q * (parseFloat(item.numeric_price) || 0);
        }
      });
      document.getElementById('cartCount').textContent = count;
      document.getElementById('cartTotalText').textContent = total > 0 ? (total.toFixed(0) + ' TL') : (count + ' Ürün');
      const bar = document.getElementById('floatingCartBar');
      if (count > 0) bar.classList.add('show');
      else bar.classList.remove('show');
    }

    function prepareQrOrder() {
      const lines = [];
      let total = 0;
      QR_MENU.forEach(item => {
        const q = cart[item.id] || 0;
        if (q > 0) {
          const p = parseFloat(item.numeric_price) || 0;
          total += q * p;
          lines.push(`${q}x ${item.name}${item.price ? ' (' + item.price + ')' : ''}`);
        }
      });
      const note = document.getElementById('qrOrderNote').value.trim();
      if (!lines.length && !note) {
        alert('Lütfen menüden en az bir ürün seçin veya sipariş notu yazın.');
        return false;
      }
      let summary = lines.join(', ');
      if (total > 0) summary += ` | Toplam: ${total.toFixed(0)} TL`;
      document.getElementById('orderSummaryInput').value = summary;
      return true;
    }

    function submitFloatingOrder() {
      if (prepareQrOrder()) {
        document.getElementById('qrOrderForm').submit();
      }
    }
  </script>
</body>
</html>
"""

TENANT_PUBLIC_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{{ tenant.business_name }}</title>
  <style>
    * { box-sizing:border-box; margin:0; padding:0; }
    body { background:#080d0b; color:#f8fafc; font-family:Inter,system-ui,sans-serif; padding:18px 14px 48px; overflow-x:hidden; }
    .wrap { max-width:940px; margin:0 auto; display:grid; gap:15px; }
    .top { display:flex; justify-content:space-between; align-items:center; gap:12px; border-bottom:1px solid rgba(16,185,129,0.22); padding-bottom:14px; }
    .brand-row { display:flex; align-items:center; gap:12px; min-width:0; }
    .biz-logo { width:48px; height:48px; border-radius:12px; object-fit:cover; border:1px solid rgba(16,185,129,0.35); background:#0f1714; flex-shrink:0; display:block; }
    .biz-logo-fallback { width:48px; height:48px; border-radius:12px; display:grid; place-items:center; font-weight:900; font-size:1.1rem; color:#04130d; background:linear-gradient(135deg,#34d399,#10b981); flex-shrink:0; }
    .btn-main { text-decoration:none; padding:12px 16px; border-radius:11px; font-weight:800; font-size:0.92rem; background:linear-gradient(135deg,#34d399,#10b981); color:#04130d; border:none; cursor:pointer; display:inline-flex; align-items:center; justify-content:center; width:100%; }
    .card { background:#121d18; border:1px solid rgba(16,185,129,0.22); border-radius:16px; padding:16px; display:grid; gap:13px; }
    .row-2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .row-3 { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }
    label { display:block; font-size:0.84rem; color:#d1d5db; margin-bottom:5px; font-weight:600; }
    input, select, textarea { width:100%; padding:10px 12px; border-radius:10px; border:1px solid rgba(16,185,129,0.22); background:#0f1714; color:#f8fafc; font-size:0.92rem; }
    .ok { padding:13px 15px; border-radius:12px; background:rgba(16,185,129,0.18); border:1px solid rgba(16,185,129,0.45); color:#a7f3d0; font-weight:700; font-size:0.9rem; }
    .badge { font-size:0.74rem; color:#34d399; background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.28); padding:3px 9px; border-radius:999px; font-weight:700; display:inline-block; margin-bottom:4px; }
    .menu-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; }
    .menu-card { background:#0f1714; border:1px solid rgba(16,185,129,0.2); border-radius:14px; padding:12px; display:flex; flex-direction:column; justify-content:space-between; gap:10px; }
    .menu-img { width:100%; aspect-ratio:16/10; object-fit:cover; border-radius:9px; display:block; }
    .menu-check { display:flex; align-items:flex-start; gap:8px; font-size:0.85rem; color:#e5e7eb; cursor:pointer; }
    .menu-check input[type="checkbox"] { width:auto; margin-top:3px; flex-shrink:0; }

    @media (max-width:768px) {
      .row-2, .row-3 { grid-template-columns:1fr; }
      .card { padding:15px; }
      h1 { font-size:1.25rem !important; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div class="brand-row">
        {% if tenant.logo_filename %}
          <img src="/images/logos/{{ tenant.id }}/{{ tenant.logo_filename }}" alt="{{ tenant.business_name }}" class="biz-logo" onerror="this.style.display='none';document.getElementById('bizFallback').style.display='grid';" />
          <div id="bizFallback" class="biz-logo-fallback" style="display:none;">{{ tenant.business_name[:1]|upper }}</div>
        {% else %}
          <div class="biz-logo-fallback">{{ tenant.business_name[:1]|upper }}</div>
        {% endif %}
        <div style="min-width:0;">
          <div class="badge">{{ mod_label }}</div>
          <h1 style="font-size:1.42rem;word-break:break-word;">{{ tenant.business_name }}</h1>
        </div>
      </div>
    </div>

    {% if sent %}
    <div class="ok">Kaydınız {{ tenant.business_name }} tarafına başarıyla iletildi!</div>
    {% endif %}

    {% if tenant.module_type == 'kafe-randevu' %}
    <form class="card" method="POST">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;">
        <h2 style="font-size:1.1rem;">Masa Randevusu Talebi</h2>
        <span style="font-size:0.8rem;color:#9ca3af;">Kapasite: <strong>{{ tenant.table_count or 8 }} Masa</strong></span>
      </div>

      <div class="row-2">
        <div><label>Ad Soyad</label><input type="text" name="name" placeholder="Adınız Soyadınız" required /></div>
        <div><label>Telefon</label><input type="text" name="phone" placeholder="05xx xxx xx xx" required /></div>
      </div>

      <div class="row-3">
        <div>
          <label>1. Randevu Tarihi</label>
          <input type="date" name="res_date" id="resDateInput" value="{{ selected_date }}" onchange="updateTableOptions()" required />
        </div>
        <div>
          <label>2. Randevu Saati</label>
          <select name="slot_time" id="slotSelect" onchange="updateTableOptions()" required>
            {% for sl in slot_options %}
              {% if sl.available_count > 0 %}
                <option value="{{ sl.time }}">{{ sl.time }} — Müsait ({{ sl.available_count }} masa boş)</option>
              {% else %}
                <option value="{{ sl.time }}" disabled>{{ sl.time }} — Dolu</option>
              {% endif %}
            {% endfor %}
          </select>
        </div>
        <div>
          <label>3. Masa Seçimi</label>
          <select name="table_no" id="tableSelect" required></select>
        </div>
      </div>

      <div>
        <label>Kişi Sayısı</label>
        <select name="guest_count">
          <option value="2 Kişilik">2 Kişilik</option>
          <option value="4 Kişilik">4 Kişilik</option>
          <option value="6 Kişilik">6 Kişilik</option>
          <option value="8+ Kişilik Grup">8+ Kişilik Grup</option>
        </select>
      </div>

      {% if menu_items %}
      <div>
        <label>Ön Sipariş / Menü Seçimi (Opsiyonel)</label>
        <div class="menu-grid">
          {% for item in menu_items %}
          <div class="menu-card">
            {% if item.image_filename %}
              <img src="/images/menu/{{ tenant.id }}/{{ item.image_filename }}" alt="{{ item.name }}" class="menu-img" onerror="this.style.display='none'" />
            {% endif %}
            <label class="menu-check">
              <input type="checkbox" name="menu_order" value="{{ item.name }}{% if item.price %} ({{ item.price }}){% endif %}" />
              <span>
                <strong>{{ item.name }}</strong> {% if item.price %}<span style="color:#34d399;font-weight:700;">— {{ item.price }}</span>{% endif %}
                {% if item.description %}<small style="display:block;color:#9ca3af;margin-top:2px;">{{ item.description }}</small>{% endif %}
              </span>
            </label>
          </div>
          {% endfor %}
        </div>
      </div>
      {% endif %}

      <div><label>Ek Not / Özel İstek</label><textarea name="message" rows="2" placeholder="Cam kenarı, doğum günü notu veya ek istek..."></textarea></div>
      <button type="submit" class="btn-main">Randevu Talebini Gönder</button>
    </form>

    <script>
      const SLOT_DATA = {{ slot_options | tojson }};
      let lastDate = document.getElementById("resDateInput").value;

      function updateTableOptions() {
        const dateInput = document.getElementById("resDateInput");
        if (dateInput.value && dateInput.value !== lastDate) {
          const url = new URL(window.location.href);
          url.searchParams.set("date", dateInput.value);
          window.location.href = url.toString();
          return;
        }
        const slotSel = document.getElementById("slotSelect");
        const tableSel = document.getElementById("tableSelect");
        let chosenSlot = slotSel.value;
        let currentObj = SLOT_DATA.find(s => s.time === chosenSlot && s.free_tables.length > 0);
        if (!currentObj) {
          currentObj = SLOT_DATA.find(s => s.free_tables.length > 0);
          if (currentObj) {
            slotSel.value = currentObj.time;
          }
        }
        tableSel.innerHTML = "";
        if (!currentObj || !currentObj.free_tables.length) {
          const opt = document.createElement("option");
          opt.value = "";
          opt.textContent = "Bu saatte boş masa yok";
          tableSel.appendChild(opt);
          return;
        }
        currentObj.free_tables.forEach(tNo => {
          const label = `Masa ${tNo}`;
          const opt = document.createElement("option");
          opt.value = label;
          opt.textContent = `${label} (Müsait)`;
          tableSel.appendChild(opt);
        });
      }

      updateTableOptions();
    </script>

    {% elif tenant.module_type == 'berber-randevu' %}
    <!-- BERBER & KUAFÖR: TARİH VE SAAT AYRI SEÇİM + DOLULUK KONTROLÜ -->
    <form class="card" method="POST">
      <h2 style="font-size:1.1rem;">Salon Randevu Talebi</h2>
      <div class="row-2">
        <div><label>Ad Soyad</label><input type="text" name="name" placeholder="Adınız Soyadınız" required /></div>
        <div><label>Telefon</label><input type="text" name="phone" placeholder="05xx xxx xx xx" required /></div>
      </div>
      <div class="row-3">
        <div>
          <label>1. Randevu Tarihi</label>
          <input type="date" name="res_date" id="barberDateInput" value="{{ selected_date }}" onchange="reloadBarberDate()" required />
        </div>
        <div>
          <label>2. Müsait Saat Seçimi</label>
          <select name="slot_time" required>
            {% for bs in barber_slots %}
              {% if bs.is_free %}
                <option value="{{ bs.time }}">{{ bs.time }} — Müsait</option>
              {% else %}
                <option value="{{ bs.time }}" disabled>{{ bs.time }} — Dolu</option>
              {% endif %}
            {% endfor %}
          </select>
        </div>
        <div>
          <label>3. Hizmet Seçimi</label>
          <select name="service">
            <option value="Saç Kesimi">Saç Kesimi</option>
            <option value="Saç + Sakal Tıraşı">Saç + Sakal Tıraşı</option>
            <option value="Sakal Tıraşı & Bakım">Sakal Tıraşı &amp; Bakım</option>
            <option value="Damat / Özel Bakım">Damat / Özel Bakım</option>
          </select>
        </div>
      </div>
      <div><label>Usta Tercihi / Ek Not</label><textarea name="message" rows="2" placeholder="Usta tercihi veya kesim notunuz..."></textarea></div>
      <button type="submit" class="btn-main">Randevu Al</button>
    </form>
    <script>
      function reloadBarberDate() {
        const val = document.getElementById("barberDateInput").value;
        if (!val) return;
        const url = new URL(window.location.href);
        url.searchParams.set("date", val);
        window.location.href = url.toString();
      }
    </script>

    {% elif tenant.module_type == 'mobil-saha' %}
    <div class="card">
      <h2 style="font-size:1.1rem;">Saha Ekibi &amp; Teslimat Sorgu / Talep</h2>
      <p style="font-size:0.84rem;color:#9ca3af;">Saha personeli canlı konum terminali: <a href="{{ url_for('field_agent_terminal', slug=tenant.slug) }}" style="color:#34d399;font-weight:700;">Saha Ekranını Aç →</a></p>
      <form method="POST" style="display:grid;gap:12px;">
        <div class="row-2">
          <div><label>Ad Soyad / Firma</label><input type="text" name="name" required /></div>
          <div><label>Telefon</label><input type="text" name="phone" placeholder="05xx xxx xx xx" required /></div>
        </div>
        <div>
          <label>Saha İşlem Türü</label>
          <select name="service">
            <option value="Saha Teslimat Talebi">Saha Teslimat Talebi</option>
            <option value="Teknik Servis / Saha Ekibi Çağır">Teknik Servis / Saha Ekibi Çağır</option>
            <option value="Paket Durum Bilgisi">Paket Durum Bilgisi</option>
          </select>
        </div>
        <div><label>Adres &amp; Paket Detayı</label><textarea name="message" rows="3" required></textarea></div>
        <button type="submit" class="btn-main">Saha Talebi Gönder</button>
      </form>
    </div>

    {% else %}
    <form class="card" method="POST">
      <h2 style="font-size:1.1rem;">Talep / Otomasyon İsteği Bırak</h2>
      <div class="row-2">
        <div><label>Ad Soyad</label><input type="text" name="name" required /></div>
        <div><label>Telefon</label><input type="text" name="phone" placeholder="05xx xxx xx xx" required /></div>
      </div>
      <div>
        <label>Konu / Hizmet</label>
        <select name="service">
          {% for srv in services %}
          <option value="{{ srv.tag }} - {{ srv.title }}">{{ srv.tag }} — {{ srv.title }}</option>
          {% endfor %}
        </select>
      </div>
      <div><label>Mesaj / Not</label><textarea name="message" rows="4" required></textarea></div>
      <button type="submit" class="btn-main">Gönder</button>
    </form>
    {% endif %}
  </div>
</body>
</html>
"""

TENANT_LOGIN_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{{ tenant.business_name }} — Panel Girişi</title>
  <style>
    * { box-sizing:border-box; margin:0; padding:0; }
    body { min-height:100vh; display:grid; place-items:center; background:#080d0b; color:#f8fafc; font-family:Inter,system-ui,sans-serif; padding:16px; }
    .box { width:100%; max-width:400px; background:#121d18; border:1px solid rgba(16,185,129,0.25); border-radius:16px; padding:22px; display:grid; gap:13px; }
    label { display:block; font-size:0.84rem; margin-bottom:5px; color:#d1d5db; }
    input { width:100%; padding:10px 12px; border-radius:10px; border:1px solid rgba(16,185,129,0.25); background:#0f1714; color:#f8fafc; }
    button { padding:11px; border-radius:10px; border:none; background:linear-gradient(135deg,#34d399,#10b981); color:#04130d; font-weight:800; cursor:pointer; width:100%; }
    .err { padding:10px; border-radius:10px; background:rgba(239,68,68,0.16); color:#fca5a5; font-size:0.86rem; }
  </style>
</head>
<body>
  <form class="box" method="POST">
    <div>
      <h1 style="font-size:1.2rem;">{{ tenant.business_name }}</h1>
      <p style="color:#9ca3af;font-size:0.84rem;">İşletme yönetim paneli girişi</p>
    </div>
    {% if error %}<div class="err">{{ error }}</div>{% endif %}
    <div><label>Şifre</label><input type="password" name="password" required /></div>
    <button type="submit">Giriş Yap</button>
  </form>
</body>
</html>
"""

TENANT_PANEL_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>{{ tenant.business_name }} — Yönetim Paneli</title>
  <style>
    :root { --bg:#080d0b; --card:#121d18; --soft:#0f1714; --text:#f8fafc; --muted:#9ca3af; --accent:#10b981; --bright:#34d399; --amber:#f59e0b; --border:rgba(16,185,129,0.22); }
    * { box-sizing:border-box; margin:0; padding:0; font-family:Inter,system-ui,sans-serif; -webkit-tap-highlight-color:transparent; }
    body { background:var(--bg); color:var(--text); padding:0 0 84px; overflow-x:hidden; }
    .topbar { position:sticky; top:0; z-index:40; background:rgba(8,13,11,0.9); backdrop-filter:blur(12px); border-bottom:1px solid var(--border); padding:14px 16px; display:flex; justify-content:space-between; align-items:center; gap:10px; }
    .wrap { max-width:1140px; margin:0 auto; padding:16px; display:grid; gap:14px; }
    .btn { text-decoration:none; padding:9px 13px; border-radius:10px; font-weight:700; font-size:0.84rem; border:1px solid var(--border); background:var(--card); color:var(--bright); cursor:pointer; display:inline-flex; align-items:center; justify-content:center; gap:6px; }
    .btn-ok { background:linear-gradient(135deg,#34d399,#10b981); color:#04130d; border:none; font-weight:800; }
    .btn-gold { background:linear-gradient(135deg,#fbbf24,#f59e0b); color:#1f1300; border:none; font-weight:800; }
    .btn-wa { background:rgba(34,197,94,0.16); border-color:rgba(34,197,94,0.45); color:#86efac; }
    .btn-del { background:rgba(239,68,68,0.14); border-color:rgba(239,68,68,0.35); color:#fca5a5; }
    .stats { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
    .stat { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:12px; }
    .stat span { font-size:0.74rem; color:var(--muted); display:block; }
    .stat strong { font-size:1.3rem; color:var(--bright); }
    .card { background:var(--card); border:1px solid var(--border); border-radius:16px; padding:15px; display:grid; gap:12px; }
    .msg { background:var(--soft); padding:11px 12px; border-radius:10px; font-size:0.88rem; word-break:break-word; border:1px solid rgba(16,185,129,0.12); }
    input, select { padding:10px 11px; border-radius:10px; border:1px solid var(--border); background:var(--soft); color:var(--text); font-size:0.9rem; }
    .locked-pill { padding:8px 12px; border-radius:10px; background:rgba(245,158,11,0.12); border:1px solid rgba(245,158,11,0.35); color:#fcd34d; font-size:0.8rem; font-weight:700; }
    .iban-box { background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.38); border-radius:14px; padding:15px; display:grid; gap:9px; }
    .iban-code { font-family:monospace; font-size:0.9rem; font-weight:800; color:#fcd34d; background:#09100d; padding:10px 12px; border-radius:10px; border:1px solid rgba(245,158,11,0.3); word-break:break-all; }
    .menu-admin-grid, .agents-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:12px; }
    .qr-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; }
    .qr-card, .agent-card { background:var(--soft); border:1px solid var(--border); border-radius:14px; padding:14px; display:grid; gap:8px; }
    .qr-card { text-align:center; justify-items:center; }
    .qr-card img { width:150px; height:150px; border-radius:10px; background:#fff; padding:8px; }
    .menu-box { background:var(--soft); border:1px solid var(--border); border-radius:12px; padding:12px; display:grid; gap:8px; }
    .menu-thumb { width:100%; aspect-ratio:16/10; object-fit:cover; border-radius:8px; }
    .logo-preview { width:52px; height:52px; border-radius:12px; object-fit:cover; border:1px solid var(--border); }
    .row-flex { display:flex; gap:10px; flex-wrap:wrap; align-items:end; }
    .share-box { background:var(--soft); border:1px dashed rgba(52,211,153,0.45); border-radius:12px; padding:11px 13px; display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; font-size:0.83rem; }
    .pills { display:flex; gap:8px; overflow-x:auto; padding-bottom:2px; scrollbar-width:none; }
    .pills::-webkit-scrollbar { display:none; }
    .pill-tab { background:var(--card); color:var(--muted); border:1px solid var(--border); padding:7px 13px; border-radius:999px; font-size:0.8rem; font-weight:700; white-space:nowrap; cursor:pointer; }
    .pill-tab.active { background:var(--accent); color:#04130d; border-color:var(--accent); }
    .bottom-nav { position:fixed; bottom:0; left:0; right:0; height:64px; background:rgba(8,13,11,0.96); backdrop-filter:blur(14px); border-top:1px solid var(--border); display:grid; grid-template-columns:repeat({{ nav_count }},1fr); z-index:45; }
    .bnav-btn { background:none; border:none; color:var(--muted); display:flex; flex-direction:column; align-items:center; justify-content:center; gap:3px; font-size:0.72rem; font-weight:700; cursor:pointer; }
    .bnav-btn.active { color:var(--bright); }
    .bnav-btn.locked { color:#fbbf24; }
    .tab-pane { display:none; gap:14px; }
    .tab-pane.active { display:grid; }
    .pos-table { width:100%; border-collapse:collapse; font-size:0.85rem; }
    .pos-table th, .pos-table td { padding:9px 8px; border-bottom:1px solid rgba(16,185,129,0.14); text-align:left; }
    @media (max-width:768px) {
      .row-flex > div, .row-flex > button { width:100% !important; min-width:0 !important; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div style="min-width:0;">
      <h1 style="font-size:1.05rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ tenant.business_name }}</h1>
      <p style="color:var(--muted);font-size:0.75rem;">{{ mod_label }} • {{ tenant.plan|upper }}</p>
    </div>
    <form method="POST" action="{{ url_for('tenant_logout', slug=tenant.slug) }}"><button type="submit" class="btn btn-del">Çıkış</button></form>
  </header>

  <div class="wrap">
    <div class="share-box">
      <span style="word-break:break-all;"><strong>Müşteri Linki:</strong> <code id="custLinkText">{{ request.url_root }}i/{{ tenant.slug }}</code></span>
      <button type="button" class="btn" id="copyBtn" onclick="copyText('custLinkText', 'copyBtn')">Kopyala</button>
    </div>

    {% if addon_notified %}
    <div class="card" style="border-color:rgba(16,185,129,0.5);color:#a7f3d0;font-size:0.88rem;">
      ✅ +{{ qr_addon_price }} Masa QR eklenti ödeme bildiriminiz Süper Admin'e iletildi! Onaylandığında Masa QR sekmesi anında açılacaktır.
    </div>
    {% endif %}

    {% if bot_saved %}
    <div class="card" style="border-color:rgba(16,185,129,0.5);color:#a7f3d0;font-size:0.88rem;">
      ✅ {{ bot_saved }}
    </div>
    {% endif %}

    <!-- SEKME 1: TALEPLER / SİPARİŞLER -->
    <section id="pane-tickets" class="tab-pane active">
      <div class="stats">
        <div class="stat"><span>Toplam</span><strong>{{ tickets|length }}</strong></div>
        <div class="stat"><span>Yeni</span><strong style="color:var(--amber);">{{ yeni_count }}</strong></div>
        <div class="stat"><span>Tamamlanan</span><strong>{{ tamam_count }}</strong></div>
      </div>

      <div class="pills">
        <button type="button" class="pill-tab active" onclick="filterTickets('ALL', this)">Tümü ({{ tickets|length }})</button>
        <button type="button" class="pill-tab" onclick="filterTickets('Yeni', this)">Yeni ({{ yeni_count }})</button>
        <button type="button" class="pill-tab" onclick="filterTickets('İnceleniyor', this)">İnceleniyor</button>
        <button type="button" class="pill-tab" onclick="filterTickets('Tamamlandı', this)">Tamamlandı ({{ tamam_count }})</button>
      </div>

      {% for t in tickets %}
      <div class="card ticket-card" data-status="{{ t.status }}">
        <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:flex-start;">
          <div>
            <strong>{{ t.name }}</strong> — <span style="color:var(--bright);">{{ t.service or 'Genel' }}</span>
            <div style="font-size:0.8rem;color:var(--muted);margin-top:2px;">{{ t.phone or '-' }} • {{ t.created_at }}</div>
          </div>
          <span style="font-size:0.76rem;font-weight:800;padding:3px 9px;border-radius:999px;background:rgba(245,158,11,0.15);color:var(--amber);">{{ t.status }}</span>
        </div>
        <div class="msg">{{ t.message }}</div>
        <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:center;">
          <form method="POST" action="{{ url_for('tenant_update_ticket', slug=tenant.slug, ticket_id=t.id) }}" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <select name="status">
              <option value="Yeni" {% if t.status=='Yeni' %}selected{% endif %}>Yeni</option>
              <option value="İnceleniyor" {% if t.status=='İnceleniyor' %}selected{% endif %}>İnceleniyor</option>
              <option value="Tamamlandı" {% if t.status=='Tamamlandı' %}selected{% endif %}>Tamamlandı</option>
              <option value="İptal" {% if t.status=='İptal' %}selected{% endif %}>İptal</option>
            </select>
            <button type="submit" class="btn btn-ok">Kaydet</button>
            {% if t.wa_link %}
            <a class="btn btn-wa" href="{{ t.wa_link }}" target="_blank" rel="noopener noreferrer">WhatsApp</a>
            {% endif %}
          </form>
          <form method="POST" action="{{ url_for('tenant_delete_ticket', slug=tenant.slug, ticket_id=t.id) }}" onsubmit="return confirm('Silinsin mi?');">
            <button type="submit" class="btn btn-del">Sil</button>
          </form>
        </div>
      </div>
      {% else %}
      <div class="card" style="text-align:center;color:var(--muted);">Bu işletmeye ait henüz kayıt yok.</div>
      {% endfor %}
    </section>

    {% if show_menu_tab %}
    <!-- SEKME 2: MENÜ YÖNETİMİ -->
    <section id="pane-menu" class="tab-pane">
      <div class="card">
        <div style="font-size:0.86rem;font-weight:800;color:var(--bright);">DİJİTAL MENÜYE YENİ ÜRÜN EKLE</div>
        <form method="POST" action="{{ url_for('tenant_add_menu_item', slug=tenant.slug) }}" enctype="multipart/form-data" class="row-flex">
          <div style="flex:1;min-width:160px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Ürün Adı</label>
            <input type="text" name="name" placeholder="Örn: Türk Kahvesi veya Burger" style="width:100%;" required />
          </div>
          <div style="width:110px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Fiyat</label>
            <input type="text" name="price" placeholder="90 TL" style="width:100%;" />
          </div>
          <div style="flex:1;min-width:160px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Kısa Açıklama</label>
            <input type="text" name="description" placeholder="İçerik veya sunum notu" style="width:100%;" />
          </div>
          <div style="min-width:170px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Ürün Fotoğrafı</label>
            <input type="file" name="image" accept=".jpg,.jpeg,.png,.webp" style="width:100%;" />
          </div>
          <button type="submit" class="btn btn-ok">+ Menüye Ekle</button>
        </form>
      </div>

      {% if menu_items %}
      <div class="menu-admin-grid">
        {% for item in menu_items %}
        <div class="menu-box">
          {% if item.image_filename %}
            <img src="/images/menu/{{ tenant.id }}/{{ item.image_filename }}" alt="{{ item.name }}" class="menu-thumb" onerror="this.style.display='none'" />
          {% endif %}
          <form method="POST" action="{{ url_for('tenant_edit_menu_item', slug=tenant.slug, item_id=item.id) }}" enctype="multipart/form-data" style="display:grid;gap:6px;">
            <input type="text" name="name" value="{{ item.name }}" required />
            <input type="text" name="price" value="{{ item.price or '' }}" placeholder="Fiyat" />
            <input type="text" name="description" value="{{ item.description or '' }}" placeholder="Açıklama" />
            <input type="file" name="image" accept=".jpg,.jpeg,.png,.webp" />
            <button type="submit" class="btn btn-ok">Kaydet</button>
          </form>
          <form method="POST" action="{{ url_for('tenant_delete_menu_item', slug=tenant.slug, item_id=item.id) }}" onsubmit="return confirm('Menü ürünü silinsin mi?');">
            <button type="submit" class="btn btn-del" style="width:100%;">Ürünü Sil</button>
          </form>
        </div>
        {% endfor %}
      </div>
      {% else %}
      <div class="card" style="color:var(--muted);font-size:0.86rem;">Henüz dijital menü ürünü eklenmedi.</div>
      {% endif %}
    </section>

    <!-- SEKME 3: MASA QR KODLARI (STARTER'DA KİLİTLİ +250 TL) -->
    <section id="pane-qr" class="tab-pane">
      {% if qr_unlocked %}
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
          <div>
            <div style="font-size:0.88rem;font-weight:800;color:var(--bright);">MASA QR KODLARI ({{ tenant.table_count or 8 }} MASA)</div>
            <p style="font-size:0.8rem;color:var(--muted);margin-top:2px;">QR okutulduğunda doğrudan <strong>Masa Menü, Sipariş &amp; Garson Çağır</strong> ekranına gider.</p>
          </div>
          <a href="{{ url_for('tenant_qr_print', slug=tenant.slug) }}" target="_blank" class="btn btn-ok">🖨️ Yazdırılabilir A4 QR Sayfası</a>
        </div>

        <div class="qr-grid">
          {% for qr in qr_list %}
          <div class="qr-card">
            <strong style="font-size:0.95rem;color:var(--bright);">{{ qr.label }}</strong>
            <img src="{{ qr.qr_img_url }}" alt="{{ qr.label }} QR" loading="lazy" />
            <a href="{{ qr.target_url }}" target="_blank" class="btn" style="width:100%;font-size:0.78rem;">QR Ekranını Test Et</a>
          </div>
          {% endfor %}
        </div>
      </div>
      {% else %}
      <div class="card" style="border-color:rgba(245,158,11,0.45);">
        <div style="font-size:0.82rem;font-weight:800;color:#fbbf24;">🔒 MASA QR &amp; GARSON ÇAĞIR ÖZELLİĞİ KİLİTLİ</div>
        <h2 style="font-size:1.18rem;">Starter Pakettesiniz — Masa QR Özelliğini Açın</h2>
        <p style="font-size:0.86rem;color:#d1d5db;">
          Starter pakette sadece Masa Randevu aktiftir. Masalara özel QR kod basmak, masadan dijital menü siparişi ve garson/hesap çağrısı almak için
          tek seferlik/ek <strong>{{ qr_addon_price }}</strong> ödeme yaparak kilidi açabilirsiniz (Pro pakette ücretsiz dahildir).
        </p>

        {% if tenant.qr_addon_requested %}
        <div style="padding:12px;border-radius:10px;background:rgba(16,185,129,0.16);color:#a7f3d0;font-size:0.86rem;">
          ⏳ Ekstra {{ qr_addon_price }} ödeme bildiriminiz alındı ({{ tenant.qr_addon_note or 'Not yok' }}). Süper Admin onayladığında bu ekran otomatik açılacaktır.
        </div>
        {% endif %}

        <div class="iban-box">
          <div style="font-size:0.84rem;"><strong>Alıcı:</strong> {{ iban_holder }} • <strong>Banka:</strong> {{ iban_bank }}</div>
          <div style="font-size:0.84rem;"><strong>Tutar:</strong> <span style="color:#fcd34d;font-weight:800;">{{ qr_addon_price }}</span> (Açıklamaya <code>{{ tenant.slug }} QR</code> yazın)</div>
          <div class="iban-code">{{ iban_number }}</div>
        </div>

        <form method="POST" action="{{ url_for('tenant_request_qr_addon', slug=tenant.slug) }}" style="display:grid;gap:10px;">
          <input type="text" name="qr_addon_note" value="{{ tenant.qr_addon_note or '' }}" placeholder="Gönderen Adı / Dekont Notu (Örn: Mehmet Yılmaz - 250 TL)" required />
          <button type="submit" class="btn btn-gold" style="width:100%;padding:12px;">💳 {{ qr_addon_price }} Ödeme Yaptım / Onaya Gönder</button>
        </form>
      </div>
      {% endif %}
    </section>
    {% endif %}

    {% if tenant.module_type == 'mobil-saha' %}
    <!-- MOBİL UYGULAMA & SAHA AKIŞLARI -->
    <section id="pane-saha" class="tab-pane">
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
          <div>
            <div style="font-size:0.88rem;font-weight:800;color:var(--bright);">📡 SAHA ELEMANI CANLI TAKİP MERKEZİ</div>
            <p style="font-size:0.8rem;color:var(--muted);margin-top:2px;">Aşağıdaki linki saha personeline gönderin; personel sahayı aktif ettiğinde şarj, konum, paket ve müşteri bilgisi burada görünür.</p>
          </div>
          <a href="{{ url_for('field_agent_terminal', slug=tenant.slug) }}" target="_blank" class="btn btn-ok">📱 Saha Linkini Aç</a>
        </div>

        <div class="share-box">
          <span style="word-break:break-all;"><strong>Saha Elemanı Linki:</strong> <code id="sahaLinkText">{{ request.url_root }}i/{{ tenant.slug }}/saha</code></span>
          <button type="button" class="btn" id="copySahaBtn" onclick="copyText('sahaLinkText', 'copySahaBtn')">Linki Kopyala</button>
        </div>

        {% if field_agents %}
        <div class="agents-grid">
          {% for ag in field_agents %}
          <div class="agent-card">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <strong style="color:var(--bright);font-size:0.98rem;">{{ ag.agent_name }}</strong>
              <span style="font-size:0.75rem;padding:3px 8px;border-radius:999px;background:rgba(16,185,129,0.16);color:#6ee7b7;font-weight:700;">{{ ag.status_text }}</span>
            </div>
            <div style="font-size:0.83rem;color:#e5e7eb;">
              🔋 Şarj Durumu: <strong>{% if ag.battery_level >= 0 %}%{{ ag.battery_level }} {{ '(Şarj Oluyor ⚡)' if ag.is_charging else '' }}{% else %}Bilinmiyor{% endif %}</strong>
            </div>
            <div style="font-size:0.83rem;color:#e5e7eb;">
              📦 Üzerindeki Paket: <strong>{{ ag.active_package or 'Belirtilmedi' }}</strong>
            </div>
            <div style="font-size:0.83rem;color:#e5e7eb;">
              👤 Gittiği Müşteri: <strong>{{ ag.target_customer or 'Belirtilmedi' }}</strong>
            </div>
            <div style="font-size:0.78rem;color:var(--muted);">
              🕒 Son Sinyal: {{ ag.updated_str }}
            </div>
            {% if ag.latitude and ag.longitude %}
            <a href="https://maps.google.com/?q={{ ag.latitude }},{{ ag.longitude }}" target="_blank" rel="noopener noreferrer" class="btn btn-ok" style="width:100%;font-size:0.8rem;">
              📍 Haritada Konumu Gör ({{ ag.latitude }}, {{ ag.longitude }})
            </a>
            {% endif %}
          </div>
          {% endfor %}
        </div>
        {% else %}
        <div style="padding:14px;border-radius:12px;background:var(--soft);color:var(--muted);font-size:0.85rem;">
          Henüz sahayı aktif eden personel yok. Saha elemanınız <code>/i/{{ tenant.slug }}/saha</code> linkine girip "Sahayı Aktif Et" butonuna bastığında burada canlı görünecektir.
        </div>
        {% endif %}
      </div>
    </section>
    {% endif %}

    {% if tenant.module_type == 'web-otomasyon' %}
    <!-- WEB PANELLERİ, FORMLAR & BOTLAR -->
    <section id="pane-bots" class="tab-pane">
      <form class="card" method="POST" action="{{ url_for('tenant_save_bot_config', slug=tenant.slug) }}">
        <div style="font-size:0.88rem;font-weight:800;color:var(--bright);">🤖 WHATSAPP API, TELEGRAM BOT &amp; OTOMATİK VERİ ÇEKME ENTEGRASYONLARI</div>
        <p style="font-size:0.8rem;color:var(--muted);">Yeni müşteri talebi düştüğünde veya zamanlanmış rapor saatinde bağlı botlarınız otomatik çalışır.</p>

        <div class="row-flex">
          <div style="flex:1;min-width:220px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">WhatsApp Business / Cloud API Endpoint URL</label>
            <input type="text" name="wa_api_url" value="{{ bot_cfg.wa_api_url }}" placeholder="https://graph.facebook.com/v20.0/PHONE_ID/messages" style="width:100%;" />
          </div>
          <div style="flex:1;min-width:220px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">WhatsApp API Bearer Token</label>
            <input type="text" name="wa_api_token" value="{{ bot_cfg.wa_api_token }}" placeholder="EAAG..." style="width:100%;" />
          </div>
        </div>

        <div class="row-flex">
          <div style="flex:1;min-width:220px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Telegram Bot Token</label>
            <input type="text" name="tg_bot_token" value="{{ bot_cfg.tg_bot_token }}" placeholder="123456789:AAH..." style="width:100%;" />
          </div>
          <div style="flex:1;min-width:180px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Telegram Bildirim Chat ID</label>
            <input type="text" name="tg_chat_id" value="{{ bot_cfg.tg_chat_id }}" placeholder="-1001234567890" style="width:100%;" />
          </div>
        </div>

        <div class="row-flex">
          <div style="flex:1;min-width:220px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Otomatik Veri Çekme Kaynak URL (API / RSS / JSON)</label>
            <input type="text" name="scraper_url" value="{{ bot_cfg.scraper_url }}" placeholder="https://api.ornek.com/veriler" style="width:100%;" />
          </div>
          <div style="flex:1;min-width:220px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Harici Servis Webhook URL (n8n / Zapier / Make)</label>
            <input type="text" name="webhook_url" value="{{ bot_cfg.webhook_url }}" placeholder="https://hooks.zapier.com/..." style="width:100%;" />
          </div>
          <div style="width:140px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Günlük Rapor Saati</label>
            <input type="time" name="report_hour" value="{{ bot_cfg.report_hour or '21:00' }}" style="width:100%;" />
          </div>
        </div>

        <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:0.84rem;">
          <label style="display:flex;align-items:center;gap:7px;cursor:pointer;">
            <input type="checkbox" name="wa_auto_reply" value="1" {% if bot_cfg.wa_auto_reply %}checked{% endif %} />
            <span>WhatsApp Otomatik Karşılama Mesajı Aktif</span>
          </label>
          <label style="display:flex;align-items:center;gap:7px;cursor:pointer;">
            <input type="checkbox" name="tg_notify_enabled" value="1" {% if bot_cfg.tg_notify_enabled %}checked{% endif %} />
            <span>Telegram Anlık Bildirim Botu Aktif</span>
          </label>
        </div>

        <button type="submit" class="btn btn-ok">Entegrasyon Ayarlarını Kaydet</button>
      </form>

      <div class="card">
        <div style="font-size:0.86rem;font-weight:800;color:var(--bright);">⚡ BOT &amp; VERİ ÇEKME ÇALIŞTIRMA</div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          <form method="POST" action="{{ url_for('tenant_run_bot_action', slug=tenant.slug) }}">
            <input type="hidden" name="bot_action" value="pull_data" />
            <button type="submit" class="btn">🔄 Otomatik Veri Çek &amp; Raporla</button>
          </form>
          <form method="POST" action="{{ url_for('tenant_run_bot_action', slug=tenant.slug) }}">
            <input type="hidden" name="bot_action" value="test_notify" />
            <button type="submit" class="btn btn-wa">📨 Test Bildirimi Gönder (Telegram / Webhook)</button>
          </form>
        </div>
        {% if bot_cfg.last_sync_note %}
        <div class="msg" style="color:#a7f3d0;">Son İşlem Logu: {{ bot_cfg.last_sync_note }}</div>
        {% endif %}
      </div>
    </section>
    {% endif %}

    {% if tenant.module_type == 'masaustu-otomasyon' %}
    <!-- MASAÜSTÜ KASA, BARKOD & STOK OTOMASYONU -->
    <section id="pane-pos" class="tab-pane">
      <div class="stats">
        <div class="stat"><span>Kayıtlı Ürün</span><strong>{{ pos_products|length }}</strong></div>
        <div class="stat"><span>Bugün Satılan Adet</span><strong style="color:var(--amber);">{{ pos_total_sold }}</strong></div>
        <div class="stat"><span>Günlük Kasa Ciro</span><strong>{{ "%.0f"|format(pos_total_revenue) }} TL</strong></div>
      </div>

      <div class="card">
        <div style="font-size:0.88rem;font-weight:800;color:var(--bright);">🔫 HIZLI BARKOD OKUT &amp; SATIŞ DÜŞ</div>
        <form method="POST" action="{{ url_for('tenant_pos_scan', slug=tenant.slug) }}" class="row-flex">
          <div style="flex:1;min-width:200px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Barkod Numarası (USB Okuyucu ile Okutun)</label>
            <input type="text" name="barcode" placeholder="869000000001" autofocus required style="width:100%;" />
          </div>
          <div style="width:110px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Adet</label>
            <input type="number" name="qty" value="1" min="1" max="500" style="width:100%;" />
          </div>
          <button type="submit" class="btn btn-ok">Satış Yap &amp; Stoktan Düş</button>
        </form>
      </div>

      <div class="card">
        <div style="font-size:0.88rem;font-weight:800;color:var(--bright);">📦 STOĞA YENİ BARKODLU ÜRÜN EKLE</div>
        <form method="POST" action="{{ url_for('tenant_pos_add_product', slug=tenant.slug) }}" class="row-flex">
          <div style="min-width:150px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Barkod</label>
            <input type="text" name="barcode" placeholder="869..." required style="width:100%;" />
          </div>
          <div style="flex:1;min-width:170px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Ürün Adı</label>
            <input type="text" name="name" placeholder="Örn: Su 0.5L" required style="width:100%;" />
          </div>
          <div style="width:110px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Fiyat (TL)</label>
            <input type="number" step="0.01" name="price" placeholder="15" required style="width:100%;" />
          </div>
          <div style="width:110px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Stok Adedi</label>
            <input type="number" name="stock" value="50" min="0" required style="width:100%;" />
          </div>
          <button type="submit" class="btn btn-ok">+ Ürünü Kaydet</button>
        </form>

        {% if pos_products %}
        <div style="overflow-x:auto;">
          <table class="pos-table">
            <thead>
              <tr>
                <th>Barkod</th>
                <th>Ürün</th>
                <th>Fiyat</th>
                <th>Kalan Stok</th>
                <th>Bugün Satılan</th>
              </tr>
            </thead>
            <tbody>
              {% for p in pos_products %}
              <tr>
                <td><code>{{ p.barcode }}</code></td>
                <td><strong>{{ p.name }}</strong></td>
                <td style="color:var(--bright);">{{ "%.2f"|format(p.price_num) }} TL</td>
                <td style="color:{{ '#fca5a5' if p.stock <= 5 else '#f8fafc' }};">{{ p.stock }} adet</td>
                <td>{{ p.sold_today }} adet</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
        {% endif %}
      </div>
    </section>
    {% endif %}

    <!-- SEKME AYARLAR -->
    <section id="pane-settings" class="tab-pane">
      <form class="card" method="POST" action="{{ url_for('tenant_update_settings', slug=tenant.slug) }}" enctype="multipart/form-data">
        <div style="font-size:0.86rem;font-weight:800;color:var(--bright);">İŞLETME AYARLARI &amp; LOGO</div>
        <div class="row-flex">
          {% if tenant.logo_filename %}
            <img src="/images/logos/{{ tenant.id }}/{{ tenant.logo_filename }}" alt="Logo" class="logo-preview" onerror="this.style.display='none'" />
          {% endif %}
          <div style="min-width:190px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">İşletme Logosu</label>
            <input type="file" name="logo" accept=".jpg,.jpeg,.png,.webp" style="width:100%;" />
          </div>
          <div style="flex:1;min-width:180px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">WhatsApp Numarası</label>
            <input type="text" name="whatsapp_number" value="{{ tenant.whatsapp_number or '' }}" placeholder="05xx xxx xx xx" style="width:100%;" />
          </div>
          {% if show_menu_tab %}
          <div style="width:130px;">
            <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Masa Sayısı</label>
            <input type="number" name="table_count" min="1" max="200" value="{{ tenant.table_count or 8 }}" style="width:100%;" required />
          </div>
          {% endif %}
          <div class="locked-pill">Kilitli Modül: {{ mod_label }}</div>
          <button type="submit" class="btn btn-ok">Ayarları Kaydet</button>
        </div>
      </form>
    </section>
  </div>

  <nav class="bottom-nav">
    <button type="button" class="bnav-btn active" onclick="openPane('pane-tickets', this)">
      <span style="font-size:1.15rem;">📋</span>
      <span>{{ 'Siparişler' if tenant.module_type == 'masa-qr' else 'Talepler' }}</span>
    </button>
    {% if show_menu_tab %}
    <button type="button" class="bnav-btn" onclick="openPane('pane-menu', this)">
      <span style="font-size:1.15rem;">🍽️</span>
      <span>Menü</span>
    </button>
    <button type="button" class="bnav-btn {{ '' if qr_unlocked else 'locked' }}" onclick="openPane('pane-qr', this)">
      <span style="font-size:1.15rem;">{{ '📱' if qr_unlocked else '🔒' }}</span>
      <span>{{ 'QR Kodlar' if qr_unlocked else 'QR (+250 TL)' }}</span>
    </button>
    {% endif %}
    {% if tenant.module_type == 'mobil-saha' %}
    <button type="button" class="bnav-btn" onclick="openPane('pane-saha', this)">
      <span style="font-size:1.15rem;">📡</span>
      <span>Saha Takip</span>
    </button>
    {% endif %}
    {% if tenant.module_type == 'web-otomasyon' %}
    <button type="button" class="bnav-btn" onclick="openPane('pane-bots', this)">
      <span style="font-size:1.15rem;">🤖</span>
      <span>Bot &amp; API</span>
    </button>
    {% endif %}
    {% if tenant.module_type == 'masaustu-otomasyon' %}
    <button type="button" class="bnav-btn" onclick="openPane('pane-pos', this)">
      <span style="font-size:1.15rem;">🔫</span>
      <span>Kasa &amp; Barkod</span>
    </button>
    {% endif %}
    <button type="button" class="bnav-btn" onclick="openPane('pane-settings', this)">
      <span style="font-size:1.15rem;">⚙️</span>
      <span>Ayarlar</span>
    </button>
  </nav>

  <script>
    function openPane(id, btn) {
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      document.querySelectorAll('.bnav-btn').forEach(b => b.classList.remove('active'));
      document.getElementById(id).classList.add('active');
      btn.classList.add('active');
    }
    function filterTickets(status, btn) {
      document.querySelectorAll('.pill-tab').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('.ticket-card').forEach(c => {
        c.style.display = (status === 'ALL' || c.dataset.status === status) ? 'grid' : 'none';
      });
    }
    function copyText(elId, btnId) {
      const txt = document.getElementById(elId).textContent.trim();
      navigator.clipboard?.writeText(txt);
      const b = document.getElementById(btnId);
      const old = b.textContent;
      b.textContent = "Kopyalandı ✓";
      setTimeout(() => b.textContent = old, 1800);
    }
  </script>
</body>
</html>
"""

QR_PRINT_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{{ tenant.business_name }} — Masa QR Kodları Yazdır</title>
  <style>
    * { box-sizing:border-box; margin:0; padding:0; font-family:Inter,system-ui,sans-serif; }
    body { background:#f1f5f9; color:#0f172a; padding:20px; }
    .toolbar {
      max-width:1020px; margin:0 auto 20px; background:#0f172a; color:#fff;
      padding:14px 18px; border-radius:14px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;
    }
    .print-btn {
      background:#10b981; color:#04130d; border:none; padding:10px 18px;
      border-radius:10px; font-weight:800; font-size:0.9rem; cursor:pointer;
    }
    .sheet {
      max-width:1020px; margin:0 auto;
      display:grid; grid-template-columns:repeat(3, 1fr); gap:16px;
    }
    .sticker {
      background:#ffffff; border:2px dashed #94a3b8; border-radius:16px;
      padding:18px 14px; text-align:center; display:grid; gap:8px; justify-items:center;
      page-break-inside:avoid;
    }
    .biz-name { font-size:0.85rem; font-weight:800; color:#475569; text-transform:uppercase; letter-spacing:0.04em; }
    .table-title { font-size:1.35rem; font-weight:900; color:#0f172a; }
    .sticker img { width:170px; height:170px; display:block; }
    .scan-note { font-size:0.82rem; font-weight:700; color:#059669; }
    @media print {
      body { background:#fff; padding:0; }
      .toolbar { display:none !important; }
      .sheet { gap:12px; }
      .sticker { border:1.5px solid #cbd5e1; }
    }
    @media (max-width:680px) {
      .sheet { grid-template-columns:repeat(2, 1fr); }
    }
  </style>
</head>
<body>
  <div class="toolbar">
    <div>
      <strong>{{ tenant.business_name }} — Masa QR Etiketleri</strong>
      <div style="font-size:0.8rem;color:#94a3b8;">Toplam {{ qr_list|length }} masa için hazır baskı şablonu</div>
    </div>
    <button type="button" class="print-btn" onclick="window.print()">🖨️ Yazdır / PDF Kaydet</button>
  </div>

  <div class="sheet">
    {% for qr in qr_list %}
    <div class="sticker">
      <div class="biz-name">{{ tenant.business_name }}</div>
      <div class="table-title">{{ qr.label }}</div>
      <img src="{{ qr.qr_img_url }}" alt="{{ qr.label }}" />
      <div class="scan-note">Menü &amp; Sipariş İçin QR Kodu Okutun</div>
    </div>
    {% endfor %}
  </div>
</body>
</html>
"""

SUPERADMIN_LOGIN_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>KOLAY Admin — Yönetim Girişi</title>
  <style>
    * { box-sizing:border-box; margin:0; padding:0; }
    body {
      min-height:100vh; display:grid; place-items:center;
      background:radial-gradient(circle at 20% 15%, rgba(16,185,129,0.16), transparent 45%), #080d0b;
      color:#f8fafc; font-family:Inter,system-ui,sans-serif; padding:18px;
    }
    .box {
      width:100%; max-width:390px; background:#121d18;
      border:1px solid rgba(16,185,129,0.28); border-radius:20px;
      padding:26px 22px; display:grid; gap:15px;
      box-shadow:0 20px 44px rgba(0,0,0,0.45);
    }
    .badge-icon {
      width:50px; height:50px; border-radius:14px; margin:0 auto 4px;
      display:grid; place-items:center; font-weight:900; font-size:1.3rem; color:#04130d;
      background:linear-gradient(135deg,#34d399,#f59e0b);
    }
    label { display:block; font-size:0.82rem; margin-bottom:6px; color:#9ca3af; font-weight:600; }
    input {
      width:100%; padding:12px 14px; border-radius:12px;
      border:1px solid rgba(16,185,129,0.25); background:#0f1714;
      color:#f8fafc; font-size:0.95rem; outline:none;
    }
    input:focus { border-color:#34d399; }
    button {
      padding:13px; border-radius:12px; border:none;
      background:linear-gradient(135deg,#34d399,#10b981);
      color:#04130d; font-weight:800; font-size:0.95rem; cursor:pointer; width:100%; margin-top:4px;
    }
    .err {
      padding:10px 12px; border-radius:10px; background:rgba(239,68,68,0.15);
      border:1px solid rgba(239,68,68,0.35); color:#fca5a5; font-size:0.85rem; text-align:center;
    }
  </style>
</head>
<body>
  <form class="box" method="POST">
    <div style="text-align:center;">
      <div class="badge-icon">K</div>
      <h1 style="font-size:1.22rem;margin-top:6px;">KOLAY Süper Admin</h1>
      <p style="font-size:0.82rem;color:#9ca3af;margin-top:3px;">IBAN Onay, QR Eklenti Kilidi &amp; İşletme Kontrolü</p>
    </div>
    {% if error %}<div class="err">{{ error }}</div>{% endif %}
    <div><label>Kullanıcı Adı</label><input type="text" name="username" autocomplete="username" required /></div>
    <div><label>Şifre</label><input type="password" name="password" autocomplete="current-password" required /></div>
    <button type="submit">Yönetim Paneline Gir</button>
  </form>
</body>
</html>
"""

SUPERADMIN_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>Süper Admin — IBAN Ödeme Onayı &amp; İşletmeler</title>
  <style>
    :root { --bg:#080d0b; --card:#121d18; --soft:#0f1714; --text:#f8fafc; --muted:#9ca3af; --accent:#10b981; --bright:#34d399; --amber:#f59e0b; --danger:#ef4444; --border:rgba(16,185,129,0.22); }
    * { box-sizing:border-box; margin:0; padding:0; font-family:Inter,system-ui,sans-serif; -webkit-tap-highlight-color:transparent; }
    body { background:var(--bg); color:var(--text); padding:0 0 82px; overflow-x:hidden; }

    .topbar {
      position:sticky; top:0; z-index:40;
      background:rgba(8,13,11,0.9); backdrop-filter:blur(12px);
      border-bottom:1px solid var(--border);
      padding:13px 16px; display:flex; justify-content:space-between; align-items:center; gap:10px;
    }
    .topbar-left { display:flex; align-items:center; gap:9px; }
    .live-dot { width:9px; height:9px; border-radius:50%; background:var(--bright); box-shadow:0 0 10px var(--bright); }
    .topbar h1 { font-size:1.05rem; font-weight:800; }

    .wrap { max-width:1140px; margin:0 auto; padding:16px; display:grid; gap:14px; }

    .kpi-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
    .kpi { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:12px; }
    .kpi span { font-size:0.74rem; color:var(--muted); display:block; margin-bottom:3px; }
    .kpi strong { font-size:1.3rem; font-weight:800; }
    .kpi strong.green { color:var(--bright); }
    .kpi strong.amber { color:#fcd34d; }
    .kpi strong.red { color:#fca5a5; }

    .iban-bar {
      background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.34);
      border-radius:14px; padding:11px 14px;
      display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap;
    }
    .iban-bar code { font-size:0.84rem; color:#fcd34d; font-weight:800; word-break:break-all; }

    .search-wrap { position:relative; }
    .search-wrap input {
      width:100%; padding:11px 14px 11px 38px; border-radius:12px;
      border:1px solid var(--border); background:var(--card); color:var(--text); font-size:0.9rem; outline:none;
    }
    .search-wrap input:focus { border-color:var(--bright); }
    .search-ico { position:absolute; left:13px; top:50%; transform:translateY(-50%); font-size:0.9rem; opacity:0.7; }

    .filter-row { display:flex; gap:8px; overflow-x:auto; padding-bottom:2px; scrollbar-width:none; }
    .filter-row::-webkit-scrollbar { display:none; }
    .f-pill {
      background:var(--card); color:var(--muted); border:1px solid var(--border);
      padding:7px 14px; border-radius:999px; font-size:0.8rem; font-weight:700; white-space:nowrap; cursor:pointer;
    }
    .f-pill.active { background:var(--accent); color:#04130d; border-color:var(--accent); }

    .btn { text-decoration:none; padding:9px 12px; border-radius:10px; font-weight:700; font-size:0.82rem; border:1px solid var(--border); background:var(--soft); color:var(--bright); cursor:pointer; display:inline-flex; align-items:center; justify-content:center; gap:5px; }
    .btn-approve { background:linear-gradient(135deg,#34d399,#10b981); color:#04130d; border:none; font-weight:800; }
    .btn-gold { background:linear-gradient(135deg,#fbbf24,#f59e0b); color:#1f1300; border:none; font-weight:800; }
    .btn-extend { background:rgba(59,130,246,0.18); border-color:rgba(59,130,246,0.42); color:#93c5fd; }
    .btn-edit { background:rgba(245,158,11,0.14); border-color:rgba(245,158,11,0.38); color:#fcd34d; }
    .btn-suspend { background:rgba(239,68,68,0.14); border-color:rgba(239,68,68,0.38); color:#fca5a5; }
    .card { background:var(--card); border:1px solid var(--border); border-radius:16px; padding:16px; display:grid; gap:12px; }
    .card.pending { border-color:rgba(245,158,11,0.52); }
    .card.expired { border-color:rgba(239,68,68,0.58); }
    .badge-on { padding:3px 9px; border-radius:999px; font-size:0.72rem; font-weight:800; background:rgba(16,185,129,0.16); color:#6ee7b7; }
    .badge-off { padding:3px 9px; border-radius:999px; font-size:0.72rem; font-weight:800; background:rgba(245,158,11,0.18); color:#fcd34d; }
    .badge-exp { padding:3px 9px; border-radius:999px; font-size:0.72rem; font-weight:800; background:rgba(239,68,68,0.2); color:#fca5a5; }
    .badge-notify { padding:3px 9px; border-radius:999px; font-size:0.72rem; font-weight:800; background:rgba(59,130,246,0.2); color:#93c5fd; }
    select, .modal-input { padding:9px 11px; border-radius:9px; border:1px solid var(--border); background:var(--soft); color:var(--text); font-size:0.86rem; width:100%; }

    .actions-bar { display:flex; gap:8px; align-items:center; flex-wrap:wrap; padding-top:10px; border-top:1px solid rgba(16,185,129,0.12); }

    .modal-bg { position:fixed; inset:0; background:rgba(2,6,4,0.8); backdrop-filter:blur(5px); z-index:70; display:none; align-items:center; justify-content:center; padding:16px; }
    .modal-bg.open { display:flex; }
    .modal-card { width:100%; max-width:440px; background:var(--card); border:1px solid var(--border); border-radius:18px; padding:20px; display:grid; gap:12px; }
    .modal-card label { display:block; font-size:0.78rem; color:var(--muted); margin-bottom:4px; font-weight:600; }

    .bottom-nav {
      position:fixed; bottom:0; left:0; right:0; height:64px;
      background:rgba(8,13,11,0.96); backdrop-filter:blur(14px);
      border-top:1px solid var(--border); display:grid; grid-template-columns:repeat(3,1fr); z-index:45;
    }
    .bnav { background:none; border:none; color:var(--muted); display:flex; flex-direction:column; align-items:center; justify-content:center; gap:3px; font-size:0.74rem; font-weight:700; cursor:pointer; text-decoration:none; }
    .bnav.active { color:var(--bright); }

    @media (max-width:768px) {
      .kpi-grid { grid-template-columns:repeat(2,1fr); }
      .actions-bar > a, .actions-bar > form, .actions-bar > button { flex:1 1 calc(50% - 4px); }
      .actions-bar > form button { width:100%; }
    }
  </style>
</head>
<body>
  {% set active_count = tenants|selectattr('is_active')|list|length %}
  {% set pending_count = (tenants|length) - active_count %}
  {% set expired_count = tenants|selectattr('is_expired')|list|length %}
  {% set notify_count = tenants|selectattr('payment_requested')|list|length + tenants|selectattr('qr_addon_requested')|list|length %}

  <header class="topbar">
    <div class="topbar-left">
      <span class="live-dot"></span>
      <h1>KOLAY Süper Admin</h1>
    </div>
    <form method="POST" action="{{ url_for('superadmin_logout') }}">
      <button type="submit" class="btn btn-suspend">Çıkış</button>
    </form>
  </header>

  <div class="wrap">
    <div class="kpi-grid">
      <div class="kpi"><span>Toplam İşletme</span><strong>{{ tenants|length }}</strong></div>
      <div class="kpi"><span>Aktif</span><strong class="green">{{ active_count }}</strong></div>
      <div class="kpi"><span>Onay Bekleyen</span><strong class="amber">{{ pending_count }}</strong></div>
      <div class="kpi"><span>Süresi Dolan</span><strong class="red">{{ expired_count }}</strong></div>
    </div>

    <div class="iban-bar">
      <div>
        <div style="font-size:0.72rem;color:var(--muted);font-weight:700;">AKTİF TAHSİLAT IBAN</div>
        <code id="adminIban">{{ iban_number }}</code>
      </div>
      <button type="button" class="btn" id="ibanCopyBtn" onclick="copyAdminIban()">IBAN Kopyala</button>
    </div>

    <div class="search-wrap">
      <span class="search-ico">🔍</span>
      <input type="text" id="tenantSearch" placeholder="İşletme adı, slug veya e-posta ara..." onkeyup="filterTenants()" />
    </div>

    <div class="filter-row">
      <button type="button" class="f-pill active" onclick="setTenantFilter('all', this)">Tümü ({{ tenants|length }})</button>
      <button type="button" class="f-pill" onclick="setTenantFilter('notify', this)">Ödeme / QR Bildirimi ({{ notify_count }})</button>
      <button type="button" class="f-pill" onclick="setTenantFilter('pending', this)">Onay Bekleyen ({{ pending_count }})</button>
      <button type="button" class="f-pill" onclick="setTenantFilter('expired', this)">Süresi Dolan ({{ expired_count }})</button>
      <button type="button" class="f-pill" onclick="setTenantFilter('active', this)">Aktifler ({{ active_count }})</button>
    </div>

    {% for tn in tenants %}
    <div class="card tenant-item {% if tn.is_expired %}expired{% elif not tn.is_active %}pending{% endif %}"
         data-search="{{ (tn.business_name ~ ' ' ~ tn.slug ~ ' ' ~ tn.owner_email)|lower }}"
         data-state="{{ 'notify' if (tn.payment_requested or tn.qr_addon_requested) else ('expired' if tn.is_expired else ('active' if tn.is_active else 'pending')) }}"
         data-pending="{{ '0' if tn.is_active else '1' }}">
      <div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <strong style="font-size:1.02rem;">{{ tn.business_name }}</strong>
          <code style="font-size:0.82rem;color:var(--bright);">/i/{{ tn.slug }}</code>
          {% if tn.is_expired %}
            <span class="badge-exp">SÜRESİ DOLDU ({{ tn.expires_str }})</span>
          {% elif tn.is_active %}
            <span class="badge-on">AKTİF {% if tn.days_left is not none %}({{ tn.days_left }} gün kaldı){% endif %}</span>
          {% else %}
            <span class="badge-off">ONAY BEKLİYOR</span>
          {% endif %}
          {% if tn.payment_requested and not tn.is_active %}
            <span class="badge-notify">ÜYELİK ÖDEME BİLDİRİMİ</span>
          {% endif %}
          {% if tn.qr_addon_requested %}
            <span class="badge-notify">+250 TL QR EKLENTİ BİLDİRİMİ</span>
          {% endif %}
          {% if tn.module_type == 'kafe-randevu' %}
            <span class="{{ 'badge-on' if (tn.plan == 'pro' or tn.qr_addon_active) else 'badge-off' }}">
              QR: {{ 'AÇIK' if (tn.plan == 'pro' or tn.qr_addon_active) else 'KİLİTLİ' }}
            </span>
          {% endif %}
        </div>
        <div style="font-size:0.82rem;color:var(--muted);margin-top:6px;line-height:1.5;">
          {{ tn.owner_email }} • Paket: <strong style="color:var(--text);">{{ tn.plan|upper }}</strong> • Modül: <code>{{ tn.module_type }}</code> • Masa: {{ tn.table_count or '-' }} • Talep: {{ tn.ticket_count }} • Bitiş: <strong>{{ tn.expires_str }}</strong>
          {% if tn.payment_note %}
          <div style="margin-top:5px;padding:7px 10px;border-radius:8px;background:rgba(245,158,11,0.1);color:#fcd34d;">
            Üyelik Dekont Notu: <strong>{{ tn.payment_note }}</strong>
          </div>
          {% endif %}
          {% if tn.qr_addon_note %}
          <div style="margin-top:5px;padding:7px 10px;border-radius:8px;background:rgba(59,130,246,0.12);color:#93c5fd;">
            QR Eklenti (+250 TL) Dekont Notu: <strong>{{ tn.qr_addon_note }}</strong>
          </div>
          {% endif %}
        </div>
      </div>

      <div class="actions-bar">
        <a class="btn" href="{{ url_for('tenant_public', slug=tn.slug) }}">Müşteri Linki</a>
        <a class="btn" href="{{ url_for('tenant_panel', slug=tn.slug) }}">Paneli Aç</a>

        {% if not tn.is_active %}
        <form method="POST" action="{{ url_for('superadmin_approve_tenant', tenant_id=tn.id) }}">
          <button type="submit" class="btn btn-approve">Ödeme Alındı &amp; Onayla (+30 Gün)</button>
        </form>
        {% else %}
        <form method="POST" action="{{ url_for('superadmin_extend_tenant', tenant_id=tn.id) }}">
          <button type="submit" class="btn btn-extend">+30 Gün Uzat</button>
        </form>
        <form method="POST" action="{{ url_for('superadmin_suspend_tenant', tenant_id=tn.id) }}">
          <button type="submit" class="btn btn-suspend">Askıya Al</button>
        </form>
        {% endif %}

        {% if tn.module_type == 'kafe-randevu' and tn.plan == 'starter' and not tn.qr_addon_active %}
        <form method="POST" action="{{ url_for('superadmin_unlock_qr_addon', tenant_id=tn.id) }}">
          <button type="submit" class="btn btn-gold">🔓 +250 TL QR Kilidini Aç</button>
        </form>
        {% endif %}

        <button type="button" class="btn btn-edit"
          onclick="openEditTenantModal('{{ tn.id }}', '{{ tn.business_name|e }}', '{{ tn.owner_email|e }}', '{{ tn.plan }}', '{{ tn.module_type }}', '{{ tn.table_count or 8 }}')">
          ✏️ Düzenle
        </button>

        {% if tn.slug != 'kolay-vitrin' %}
        <form method="POST" action="{{ url_for('superadmin_delete_tenant', tenant_id=tn.id) }}"
              onsubmit="return confirm('{{ tn.business_name }} işletmesi ve tüm talepleri/menüleri KALICI OLARAK silinsin mi?');">
          <button type="submit" class="btn btn-suspend">🗑️ Kalıcı Sil</button>
        </form>
        {% endif %}
      </div>
    </div>
    {% endfor %}
  </div>

  <div class="modal-bg" id="editTenantModal" onclick="if(event.target===this) closeEditTenantModal()">
    <form class="modal-card" id="editTenantForm" method="POST">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <h3 style="font-size:1.05rem;">İşletmeyi Düzenle</h3>
        <button type="button" class="btn" onclick="closeEditTenantModal()">✕</button>
      </div>
      <div>
        <label>İşletme Adı</label>
        <input type="text" name="business_name" id="etName" class="modal-input" required />
      </div>
      <div>
        <label>E-posta</label>
        <input type="email" name="owner_email" id="etEmail" class="modal-input" required />
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div>
          <label>Paket</label>
          <select name="plan" id="etPlan">
            <option value="starter">STARTER</option>
            <option value="pro">PRO</option>
          </select>
        </div>
        <div>
          <label>Masa Sayısı</label>
          <input type="number" name="table_count" id="etTables" min="1" max="200" class="modal-input" />
        </div>
      </div>
      <div>
        <label>Modül Türü</label>
        <select name="module_type" id="etModule">
          <option value="kafe-randevu">Kafe &amp; Restoran Masa Randevu + Masa QR</option>
          <option value="masa-qr">Masa QR Menü, Sipariş &amp; Garson Çağır</option>
          <option value="berber-randevu">Berber &amp; Kuaför Saat Randevu</option>
          <option value="mobil-saha">Mobil Uygulama &amp; Saha Akışları</option>
          <option value="web-otomasyon">Web Panelleri, Formlar &amp; Botlar</option>
          <option value="masaustu-otomasyon">Masaüstü Kasa, Barkod &amp; Stok Otomasyonu</option>
          <option value="genel">Genel Talep Formu</option>
        </select>
      </div>
      <div>
        <label>Yeni Panel Şifresi (Değiştirmek istemiyorsan boş bırak)</label>
        <input type="text" name="new_password" placeholder="Yeni şifre (en az 4 karakter)" class="modal-input" />
      </div>
      <button type="submit" class="btn btn-approve" style="width:100%;padding:12px;">Değişiklikleri Kaydet</button>
    </form>
  </div>

  <nav class="bottom-nav">
    <button type="button" class="bnav active" onclick="setTenantFilter('all', document.querySelector('.f-pill'))">
      <span style="font-size:1.15rem;">🏢</span>
      <span>İşletmeler</span>
    </button>
    <button type="button" class="bnav" onclick="setTenantFilter('pending', document.querySelectorAll('.f-pill')[2])">
      <span style="font-size:1.15rem;">⏳</span>
      <span>Onay ({{ pending_count }})</span>
    </button>
    <a class="bnav" href="{{ url_for('index') }}">
      <span style="font-size:1.15rem;">🌐</span>
      <span>Ana Vitrin</span>
    </a>
  </nav>

  <script>
    let activeFilter = 'all';

    function setTenantFilter(mode, pillBtn) {
      activeFilter = mode;
      document.querySelectorAll('.f-pill').forEach(p => p.classList.remove('active'));
      if (pillBtn) pillBtn.classList.add('active');
      filterTenants();
    }

    function filterTenants() {
      const q = document.getElementById('tenantSearch').value.toLowerCase().trim();
      document.querySelectorAll('.tenant-item').forEach(card => {
        const hay = card.dataset.search || '';
        const st = card.dataset.state || 'active';
        const isPending = card.dataset.pending === '1';
        const matchText = hay.includes(q);
        let matchMode = true;
        if (activeFilter === 'notify') matchMode = (st === 'notify');
        else if (activeFilter === 'pending') matchMode = isPending;
        else if (activeFilter === 'expired') matchMode = (st === 'expired');
        else if (activeFilter === 'active') matchMode = !isPending;
        card.style.display = (matchText && matchMode) ? 'grid' : 'none';
      });
    }

    function openEditTenantModal(id, name, email, plan, mod, tables) {
      document.getElementById('editTenantForm').action = '/admin/tenant/' + id + '/edit';
      document.getElementById('etName').value = name;
      document.getElementById('etEmail').value = email;
      document.getElementById('etPlan').value = plan;
      document.getElementById('etModule').value = mod;
      document.getElementById('etTables').value = tables;
      document.getElementById('editTenantModal').classList.add('open');
    }

    function closeEditTenantModal() {
      document.getElementById('editTenantModal').classList.remove('open');
    }

    function copyAdminIban() {
      const txt = document.getElementById('adminIban').textContent.trim();
      navigator.clipboard?.writeText(txt);
      const btn = document.getElementById('ibanCopyBtn');
      btn.textContent = 'Kopyalandı ✓';
      setTimeout(() => btn.textContent = 'IBAN Kopyala', 1800);
    }
  </script>
</body>
</html>
"""


@app.route("/logo.png")
def serve_root_logo():
    for candidate in (IMAGES_DIR / "logo.png", BASE_DIR / "logo.png"):
        if candidate.exists() and candidate.is_file():
            return send_from_directory(candidate.parent, candidate.name)
    abort(404)


@app.route("/images/logos/<int:tenant_id>/<path:filename>")
def serve_tenant_logo(tenant_id, filename):
    safe_name = Path(filename).name
    stored = get_stored_image_from_db(tenant_id, "logos", safe_name)
    if stored:
        return Response(bytes(stored["data"]), mimetype=stored["content_type"])
    target_dir = LOGO_IMAGES_DIR / str(tenant_id)
    candidate = target_dir / safe_name
    if candidate.exists() and candidate.is_file():
        return send_from_directory(target_dir, safe_name)
    abort(404)


@app.route("/images/menu/<int:tenant_id>/<path:filename>")
def serve_menu_image(tenant_id, filename):
    safe_name = Path(filename).name
    stored = get_stored_image_from_db(tenant_id, "menu", safe_name)
    if stored:
        return Response(bytes(stored["data"]), mimetype=stored["content_type"])
    target_dir = MENU_IMAGES_DIR / str(tenant_id)
    candidate = target_dir / safe_name
    if candidate.exists() and candidate.is_file():
        return send_from_directory(target_dir, safe_name)
    abort(404)


@app.route("/images/<path:filename>")
def serve_image(filename):
    if not IMAGES_DIR.exists():
        abort(404)
    direct = IMAGES_DIR / filename
    if direct.exists() and direct.is_file():
        return send_from_directory(IMAGES_DIR, filename)
    stem = Path(filename).stem
    for ext in ("", ".jpg", ".jpeg", ".png", ".webp"):
        candidate = IMAGES_DIR / f"{stem}{ext}"
        if candidate.exists() and candidate.is_file():
            return send_from_directory(IMAGES_DIR, candidate.name)
    abort(404)


@app.route("/", methods=["GET"])
def index():
    created_slug = request.args.get("created", "").strip()
    created_tenant = get_tenant_by_slug(created_slug) if created_slug else None
    saas_error = request.args.get("err", "").strip() or None
    return render_template_string(
        INDEX_HTML,
        services=SERVICES_DATA,
        wa_number=WHATSAPP_NUMBER,
        iban_holder=IBAN_HOLDER,
        iban_bank=IBAN_BANK,
        iban_number=IBAN_NUMBER,
        price_starter=PLAN_PRICE_STARTER,
        price_pro=PLAN_PRICE_PRO,
        qr_addon_price=QR_ADDON_PRICE,
        created_tenant=created_tenant,
        saas_error=saas_error,
    )


@app.route("/saas/register", methods=["POST"])
def register_tenant():
    business_name = request.form.get("business_name", "").strip()
    raw_slug = request.form.get("slug", "").strip()
    owner_email = request.form.get("owner_email", "").strip()
    whatsapp_number = request.form.get("whatsapp_number", "").strip()
    password = request.form.get("password", "").strip()
    plan = request.form.get("plan", "starter").strip()
    module_type = request.form.get("module_type", "kafe-randevu").strip()

    if not business_name or not owner_email or len(password) < 4:
        return redirect(url_for("index", err="İşletme adı, e-posta ve en az 4 karakter şifre zorunlu.") + "#saas-basla")

    try:
        tenant = create_tenant(
            business_name,
            owner_email,
            password,
            raw_slug=raw_slug,
            plan=plan,
            module_type=module_type,
            whatsapp_number=whatsapp_number,
        )
        authed = set(session.get("tenant_auth_slugs", []))
        authed.add(tenant["slug"])
        session["tenant_auth_slugs"] = list(authed)
        return redirect(url_for("index", created=tenant["slug"]) + "#saas-basla")
    except Exception as exc:
        return redirect(url_for("index", err=f"Kayıt sırasında hata oluştu: {exc}") + "#saas-basla")


@app.route("/saas/login", methods=["POST"])
def tenant_quick_login():
    slug = slugify(request.form.get("slug", "").strip())
    password = request.form.get("password", "").strip()
    tenant = get_tenant_by_slug(slug)
    if tenant and check_password_hash(tenant["password_hash"], password):
        authed = set(session.get("tenant_auth_slugs", []))
        authed.add(tenant["slug"])
        session["tenant_auth_slugs"] = list(authed)
        return redirect(url_for("tenant_panel", slug=tenant["slug"]))
    return redirect(url_for("index", err="İşletme slug veya şifre hatalı.") + "#saas-basla")


@app.route("/i/<slug>/odeme-bildir", methods=["POST"])
def notify_iban_payment(slug):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)
    note = request.form.get("payment_note", "").strip()[:240]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tenants SET payment_requested = TRUE, payment_note = %s WHERE id = %s",
                (note, tenant["id"]),
            )
    return redirect(url_for("tenant_public", slug=slug, notified="1"))


@app.route("/i/<slug>/saha", methods=["GET"])
def field_agent_terminal(slug):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)
    if not tenant["is_active"]:
        return redirect(url_for("tenant_public", slug=slug))
    return render_template_string(FIELD_AGENT_HTML, tenant=tenant)


@app.route("/i/<slug>/saha/ping", methods=["POST"])
def field_agent_ping(slug):
    tenant = get_tenant_by_slug(slug)
    if not tenant or not tenant["is_active"]:
        return jsonify({"ok": False}), 404
    data = request.get_json(silent=True) or {}
    agent_name = str(data.get("agent_name") or "").strip()[:80]
    if not agent_name:
        return jsonify({"ok": False, "err": "agent_name required"}), 400

    active_package = str(data.get("active_package") or "").strip()[:140]
    target_customer = str(data.get("target_customer") or "").strip()[:160]
    status_text = str(data.get("status_text") or "Sahada Aktif").strip()[:80]
    try:
        battery_level = int(data.get("battery_level", -1))
    except Exception:
        battery_level = -1
    is_charging = bool(data.get("is_charging", False))
    lat = str(data.get("latitude") or "").strip()[:32]
    lng = str(data.get("longitude") or "").strip()[:32]

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM field_agents WHERE tenant_id = %s AND LOWER(agent_name) = LOWER(%s)",
                (tenant["id"], agent_name),
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """
                    UPDATE field_agents
                    SET active_package = %s,
                        target_customer = %s,
                        battery_level = %s,
                        is_charging = %s,
                        latitude = %s,
                        longitude = %s,
                        status_text = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (active_package, target_customer, battery_level, is_charging, lat, lng, status_text, existing["id"]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO field_agents (
                        tenant_id, agent_name, active_package, target_customer,
                        battery_level, is_charging, latitude, longitude, status_text, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """,
                    (tenant["id"], agent_name, active_package, target_customer, battery_level, is_charging, lat, lng, status_text),
                )
    return jsonify({"ok": True})


@app.route("/i/<slug>/qr", methods=["GET", "POST"])
def tenant_qr_order_page(slug):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)

    mod_type = tenant.get("module_type") or "genel"
    mod_label = MODULE_LABELS.get(mod_type, MODULE_LABELS["genel"])

    if not tenant["is_active"]:
        notified = request.args.get("notified") == "1"
        return render_template_string(
            TENANT_PENDING_HTML,
            tenant=tenant,
            mod_label=mod_label,
            notified=notified,
            iban_holder=IBAN_HOLDER,
            iban_bank=IBAN_BANK,
            iban_number=IBAN_NUMBER,
            price_starter=PLAN_PRICE_STARTER,
            price_pro=PLAN_PRICE_PRO,
            wa_number=WHATSAPP_NUMBER,
        )

    if not tenant_has_qr_access(tenant):
        abort(403)

    preselected_masa = request.args.get("masa", "").strip()
    menu_items = get_menu_items(tenant["id"])

    if request.method == "POST":
        action_type = request.form.get("action_type", "siparis").strip()
        masa_name = request.form.get("masa_name", "").strip() or preselected_masa or "Masa 1"
        raw_message = request.form.get("message", "").strip()
        order_summary = request.form.get("order_summary", "").strip()

        if action_type == "garson":
            add_ticket(tenant["id"], masa_name, "", "🔔 Garson Çağır", f"{masa_name} garson çağırıyor.")
            return redirect(url_for("tenant_qr_order_page", slug=slug, masa=masa_name, sent="1", stype="garson"))
        elif action_type == "hesap":
            add_ticket(tenant["id"], masa_name, "", "💳 Hesap İste", f"{masa_name} hesap istiyor.")
            return redirect(url_for("tenant_qr_order_page", slug=slug, masa=masa_name, sent="1", stype="hesap"))
        else:
            parts = []
            if order_summary:
                parts.append(order_summary)
            if raw_message:
                parts.append(f"Not: {raw_message}")
            full_msg = " | ".join(parts)
            if full_msg:
                add_ticket(tenant["id"], masa_name, "", "🍽️ QR Masa Siparişi", full_msg)
            return redirect(url_for("tenant_qr_order_page", slug=slug, masa=masa_name, sent="1", stype="siparis"))

    sent = request.args.get("sent") == "1"
    stype = request.args.get("stype", "")
    sent_msg = ""
    if sent:
        m_label = preselected_masa or "Masanız"
        if stype == "garson":
            sent_msg = f"🔔 {m_label} için garson çağrısı iletildi, hemen ilgileniyoruz!"
        elif stype == "hesap":
            sent_msg = f"💳 {m_label} için hesap isteği iletildi!"
        else:
            sent_msg = f"🍽️ {m_label} için siparişiniz alındı ve hazırlanmaya başlandı!"

    return render_template_string(
        TENANT_QR_ORDER_HTML,
        tenant=tenant,
        menu_items=menu_items,
        preselected_masa=preselected_masa,
        sent=sent,
        sent_msg=sent_msg,
    )


@app.route("/i/<slug>", methods=["GET", "POST"])
def tenant_public(slug):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)

    mod_type = tenant.get("module_type") or "genel"
    mod_label = MODULE_LABELS.get(mod_type, MODULE_LABELS["genel"])

    if not tenant["is_active"]:
        notified = request.args.get("notified") == "1"
        return render_template_string(
            TENANT_PENDING_HTML,
            tenant=tenant,
            mod_label=mod_label,
            notified=notified,
            iban_holder=IBAN_HOLDER,
            iban_bank=IBAN_BANK,
            iban_number=IBAN_NUMBER,
            price_starter=PLAN_PRICE_STARTER,
            price_pro=PLAN_PRICE_PRO,
            wa_number=WHATSAPP_NUMBER,
        )

    if mod_type == "masa-qr":
        masa_param = request.args.get("masa", "").strip()
        return redirect(url_for("tenant_qr_order_page", slug=slug, masa=masa_param) if masa_param else url_for("tenant_qr_order_page", slug=slug))

    selected_date = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    menu_items = get_menu_items(tenant["id"]) if mod_type == "kafe-randevu" else []
    table_cap = max(1, int(tenant.get("table_count") or 8))
    booked_map = get_booked_tables_by_slot(tenant["id"], selected_date) if mod_type == "kafe-randevu" else {}
    slot_options = []
    for sl in TIME_SLOTS:
        taken = booked_map.get(sl, set())
        free_tables = [t_num for t_num in range(1, table_cap + 1) if t_num not in taken]
        slot_options.append({
            "time": sl,
            "free_tables": free_tables,
            "available_count": len(free_tables),
        })

    barber_slots = []
    if mod_type == "berber-randevu":
        taken_barber = get_booked_barber_slots(tenant["id"], selected_date)
        for sl in TIME_SLOTS:
            barber_slots.append({"time": sl, "is_free": sl not in taken_barber})

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        raw_service = request.form.get("service", "").strip()
        slot_time = request.form.get("slot_time", "").strip()
        table_no = request.form.get("table_no", "").strip()
        guest_count = request.form.get("guest_count", "").strip()
        res_date = request.form.get("res_date", selected_date).strip()
        selected_menu = [m.strip() for m in request.form.getlist("menu_order") if m.strip()]
        raw_message = request.form.get("message", "").strip()

        if mod_type == "kafe-randevu":
            masa_etiket = f" — {table_no}" if table_no else ""
            service = f"Randevu {res_date} {slot_time}{masa_etiket}"
            parts = []
            if res_date or slot_time:
                parts.append(f"Tarih/Saat: {res_date} {slot_time}".strip())
            if table_no:
                parts.append(f"Masa: {table_no}")
            if guest_count:
                parts.append(f"Kişi: {guest_count}")
            if selected_menu:
                parts.append(f"Menü Seçimi: {', '.join(selected_menu)}")
            if raw_message:
                parts.append(f"Not: {raw_message}")
            message = " | ".join(parts)
        elif mod_type == "berber-randevu":
            service = f"{raw_service or 'Salon Randevu'} ({res_date} {slot_time})"
            parts = [f"Tarih: {res_date}", f"Saat: {slot_time}"]
            if raw_message:
                parts.append(f"Not: {raw_message}")
            message = " | ".join(parts)
        else:
            service = raw_service or "Genel Talep"
            message = raw_message

        if name and message:
            add_ticket(tenant["id"], name, phone, service, message)
        return redirect(url_for("tenant_public", slug=slug, date=res_date, sent="1"))

    sent = request.args.get("sent") == "1"
    return render_template_string(
        TENANT_PUBLIC_HTML,
        tenant=tenant,
        services=SERVICES_DATA,
        mod_label=mod_label,
        selected_date=selected_date,
        slot_options=slot_options,
        barber_slots=barber_slots,
        menu_items=menu_items,
        sent=sent,
    )


@app.route("/i/<slug>/login", methods=["GET", "POST"])
def tenant_login(slug):
    tenant = get_tenant_by_slug(slug)
    if not tenant:
        abort(404)
    next_url = request.args.get("next") or url_for("tenant_panel", slug=slug)
    error = None

    if request.method == "POST":
        password = request.form.get("password", "").strip()
        if check_password_hash(tenant["password_hash"], password):
            authed = set(session.get("tenant_auth_slugs", []))
            authed.add(slug)
            session["tenant_auth_slugs"] = list(authed)
            return redirect(request.form.get("next") or next_url)
        error = "Şifre hatalı."

    return render_template_string(TENANT_LOGIN_HTML, tenant=tenant, error=error)


@app.route("/i/<slug>/logout", methods=["POST"])
def tenant_logout(slug):
    authed = set(session.get("tenant_auth_slugs", []))
    authed.discard(slug)
    session["tenant_auth_slugs"] = list(authed)
    return redirect(url_for("tenant_login", slug=slug))


def build_tenant_qr_list(tenant):
    table_cap = max(1, int(tenant.get("table_count") or 8))
    base_qr_url = url_for("tenant_qr_order_page", slug=tenant["slug"], _external=True)
    qr_list = []
    for idx in range(1, table_cap + 1):
        label = f"Masa {idx}"
        target_url = f"{base_qr_url}?masa={quote(label)}"
        qr_img_url = f"https://api.qrserver.com/v1/create-qr-code/?size=280x280&margin=6&data={quote(target_url, safe='')}"
        qr_list.append({
            "num": idx,
            "label": label,
            "target_url": target_url,
            "qr_img_url": qr_img_url,
        })
    return qr_list


@app.route("/i/<slug>/panel")
@tenant_login_required
def tenant_panel(slug):
    tenant = get_tenant_by_slug(slug)
    mod_type = tenant.get("module_type") or "genel"
    mod_label = MODULE_LABELS.get(mod_type, MODULE_LABELS["genel"])

    if not tenant["is_active"]:
        notified = request.args.get("notified") == "1"
        return render_template_string(
            TENANT_PENDING_HTML,
            tenant=tenant,
            mod_label=mod_label,
            notified=notified,
            iban_holder=IBAN_HOLDER,
            iban_bank=IBAN_BANK,
            iban_number=IBAN_NUMBER,
            price_starter=PLAN_PRICE_STARTER,
            price_pro=PLAN_PRICE_PRO,
            wa_number=WHATSAPP_NUMBER,
        )

    show_menu_tab = mod_type in {"kafe-randevu", "masa-qr"}
    qr_unlocked = tenant_has_qr_access(tenant)
    tickets = load_tickets(tenant["id"])
    menu_items = get_menu_items(tenant["id"]) if show_menu_tab else []
    qr_list = build_tenant_qr_list(tenant) if (show_menu_tab and qr_unlocked) else []
    field_agents = get_field_agents(tenant["id"]) if mod_type == "mobil-saha" else []
    bot_cfg = get_bot_config(tenant) if mod_type == "web-otomasyon" else {}
    pos_products = get_pos_products(tenant["id"]) if mod_type == "masaustu-otomasyon" else []
    pos_total_sold = sum(int(p.get("sold_today") or 0) for p in pos_products)
    pos_total_revenue = sum(float(p.get("price_num") or 0) * int(p.get("sold_today") or 0) for p in pos_products)

    yeni_count = sum(1 for t in tickets if (t.get("status") or "Yeni") == "Yeni")
    tamam_count = sum(1 for t in tickets if t.get("status") == "Tamamlandı")

    nav_count = 2
    if show_menu_tab:
        nav_count = 4
    elif mod_type in {"mobil-saha", "web-otomasyon", "masaustu-otomasyon"}:
        nav_count = 3

    return render_template_string(
        TENANT_PANEL_HTML,
        tenant=tenant,
        mod_label=mod_label,
        show_menu_tab=show_menu_tab,
        qr_unlocked=qr_unlocked,
        qr_addon_price=QR_ADDON_PRICE,
        iban_holder=IBAN_HOLDER,
        iban_bank=IBAN_BANK,
        iban_number=IBAN_NUMBER,
        addon_notified=(request.args.get("addon_notified") == "1"),
        bot_saved=request.args.get("bot_saved", ""),
        menu_items=menu_items,
        qr_list=qr_list,
        field_agents=field_agents,
        bot_cfg=bot_cfg,
        pos_products=pos_products,
        pos_total_sold=pos_total_sold,
        pos_total_revenue=pos_total_revenue,
        nav_count=nav_count,
        tickets=tickets,
        yeni_count=yeni_count,
        tamam_count=tamam_count,
    )


@app.route("/i/<slug>/panel/qr-addon-request", methods=["POST"])
@tenant_login_required
def tenant_request_qr_addon(slug):
    tenant = get_tenant_by_slug(slug)
    note = request.form.get("qr_addon_note", "").strip()[:240]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tenants SET qr_addon_requested = TRUE, qr_addon_note = %s WHERE id = %s",
                (note, tenant["id"]),
            )
    return redirect(url_for("tenant_panel", slug=slug, addon_notified="1"))


@app.route("/i/<slug>/panel/bot-config", methods=["POST"])
@tenant_login_required
def tenant_save_bot_config(slug):
    tenant = get_tenant_by_slug(slug)
    old_cfg = get_bot_config(tenant)
    cfg = {
        "wa_api_url": request.form.get("wa_api_url", "").strip(),
        "wa_api_token": request.form.get("wa_api_token", "").strip(),
        "wa_auto_reply": bool(request.form.get("wa_auto_reply")),
        "tg_bot_token": request.form.get("tg_bot_token", "").strip(),
        "tg_chat_id": request.form.get("tg_chat_id", "").strip(),
        "tg_notify_enabled": bool(request.form.get("tg_notify_enabled")),
        "scraper_url": request.form.get("scraper_url", "").strip(),
        "webhook_url": request.form.get("webhook_url", "").strip(),
        "report_hour": request.form.get("report_hour", "21:00").strip(),
        "last_sync_note": old_cfg.get("last_sync_note", ""),
    }
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tenants SET bot_config_json = %s WHERE id = %s",
                (json.dumps(cfg, ensure_ascii=False), tenant["id"]),
            )
    return redirect(url_for("tenant_panel", slug=slug, bot_saved="Bot ve API entegrasyon ayarları kaydedildi."))


@app.route("/i/<slug>/panel/bot-action", methods=["POST"])
@tenant_login_required
def tenant_run_bot_action(slug):
    tenant = get_tenant_by_slug(slug)
    cfg = get_bot_config(tenant)
    action = request.form.get("bot_action", "").strip()
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    if action == "pull_data":
        src = cfg.get("scraper_url") or "Dahili Talep Veritabanı"
        cfg["last_sync_note"] = f"[{now_str}] Otomatik veri çekme ve raporlama tamamlandı (Kaynak: {src})."
        msg = "Otomatik veri çekme ve günlük özet raporu çalıştırıldı."
    else:
        trigger_tenant_integrations(tenant, "Test Bildirimi", f"Sistem bağlantı testi başarılı ({now_str}).")
        cfg["last_sync_note"] = f"[{now_str}] Telegram / Webhook test bildirimi tetiklendi."
        msg = "Test bildirimi bağlı botlara gönderildi."

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tenants SET bot_config_json = %s WHERE id = %s",
                (json.dumps(cfg, ensure_ascii=False), tenant["id"]),
            )
    return redirect(url_for("tenant_panel", slug=slug, bot_saved=msg))


@app.route("/i/<slug>/panel/pos/add", methods=["POST"])
@tenant_login_required
def tenant_pos_add_product(slug):
    tenant = get_tenant_by_slug(slug)
    barcode = request.form.get("barcode", "").strip()
    name = request.form.get("name", "").strip()
    try:
        price = float(request.form.get("price", 0))
    except ValueError:
        price = 0.0
    try:
        stock = max(0, int(request.form.get("stock", 0)))
    except ValueError:
        stock = 0

    if barcode and name:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pos_products (tenant_id, barcode, name, price, stock)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, barcode)
                    DO UPDATE SET name = EXCLUDED.name, price = EXCLUDED.price, stock = EXCLUDED.stock
                    """,
                    (tenant["id"], barcode, name, price, stock),
                )
    return redirect(url_for("tenant_panel", slug=slug, bot_saved=f"Ürün kaydedildi: {name} ({barcode})"))


@app.route("/i/<slug>/panel/pos/scan", methods=["POST"])
@tenant_login_required
def tenant_pos_scan(slug):
    tenant = get_tenant_by_slug(slug)
    barcode = request.form.get("barcode", "").strip()
    try:
        qty = max(1, int(request.form.get("qty", 1)))
    except ValueError:
        qty = 1

    msg = "Barkod bulunamadı."
    if barcode:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM pos_products WHERE tenant_id = %s AND barcode = %s",
                    (tenant["id"], barcode),
                )
                prod = cur.fetchone()
                if prod:
                    new_stock = max(0, int(prod["stock"]) - qty)
                    new_sold = int(prod["sold_today"]) + qty
                    cur.execute(
                        "UPDATE pos_products SET stock = %s, sold_today = %s WHERE id = %s",
                        (new_stock, new_sold, prod["id"]),
                    )
                    msg = f"Satış işlendi: {qty}x {prod['name']} (Kalan stok: {new_stock})"
                else:
                    msg = f"'{barcode}' barkodlu ürün bulunamadı, önce aşağıdan tanımlayın."
    return redirect(url_for("tenant_panel", slug=slug, bot_saved=msg))


@app.route("/i/<slug>/panel/qr-print")
@tenant_login_required
def tenant_qr_print(slug):
    tenant = get_tenant_by_slug(slug)
    if not tenant_has_qr_access(tenant):
        abort(403)
    qr_list = build_tenant_qr_list(tenant)
    return render_template_string(QR_PRINT_HTML, tenant=tenant, qr_list=qr_list)


@app.route("/i/<slug>/panel/settings", methods=["POST"])
@tenant_login_required
def tenant_update_settings(slug):
    tenant = get_tenant_by_slug(slug)
    wa_num = request.form.get("whatsapp_number", "").strip()
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
                    "UPDATE tenants SET whatsapp_number = %s, table_count = %s, logo_filename = %s WHERE id = %s",
                    (wa_num, t_count, new_logo, tenant["id"]),
                )
            else:
                cur.execute(
                    "UPDATE tenants SET whatsapp_number = %s, table_count = %s WHERE id = %s",
                    (wa_num, t_count, tenant["id"]),
                )
    return redirect(url_for("tenant_panel", slug=slug))


@app.route("/i/<slug>/panel/menu/add", methods=["POST"])
@tenant_login_required
def tenant_add_menu_item(slug):
    tenant = get_tenant_by_slug(slug)
    if (tenant.get("module_type") or "genel") not in {"kafe-randevu", "masa-qr"}:
        return redirect(url_for("tenant_panel", slug=slug))

    name = request.form.get("name", "").strip()
    price = request.form.get("price", "").strip()
    desc = request.form.get("description", "").strip()
    img_file = save_uploaded_image(MENU_IMAGES_DIR, tenant["id"], request.files.get("image"))

    if name:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tenant_menu_items (tenant_id, name, price, description, image_filename)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (tenant["id"], name, price, desc, img_file),
                )
    return redirect(url_for("tenant_panel", slug=slug))


@app.route("/i/<slug>/panel/menu/<int:item_id>/edit", methods=["POST"])
@tenant_login_required
def tenant_edit_menu_item(slug, item_id):
    tenant = get_tenant_by_slug(slug)
    name = request.form.get("name", "").strip()
    price = request.form.get("price", "").strip()
    desc = request.form.get("description", "").strip()
    new_img = save_uploaded_image(MENU_IMAGES_DIR, tenant["id"], request.files.get("image"))

    if name:
        with get_db() as conn:
            with conn.cursor() as cur:
                if new_img:
                    cur.execute(
                        """
                        UPDATE tenant_menu_items
                        SET name = %s, price = %s, description = %s, image_filename = %s
                        WHERE id = %s AND tenant_id = %s
                        """,
                        (name, price, desc, new_img, item_id, tenant["id"]),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE tenant_menu_items
                        SET name = %s, price = %s, description = %s
                        WHERE id = %s AND tenant_id = %s
                        """,
                        (name, price, desc, item_id, tenant["id"]),
                    )
    return redirect(url_for("tenant_panel", slug=slug))


@app.route("/i/<slug>/panel/menu/<int:item_id>/delete", methods=["POST"])
@tenant_login_required
def tenant_delete_menu_item(slug, item_id):
    tenant = get_tenant_by_slug(slug)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tenant_menu_items WHERE id = %s AND tenant_id = %s",
                (item_id, tenant["id"]),
            )
    return redirect(url_for("tenant_panel", slug=slug))


@app.route("/i/<slug>/panel/update/<ticket_id>", methods=["POST"])
@tenant_login_required
def tenant_update_ticket(slug, ticket_id):
    tenant = get_tenant_by_slug(slug)
    new_status = request.form.get("status", "Yeni").strip()
    if new_status not in {"Yeni", "İnceleniyor", "Tamamlandı", "İptal"}:
        new_status = "Yeni"
    update_ticket_status(tenant["id"], ticket_id, new_status)
    return redirect(url_for("tenant_panel", slug=slug))


@app.route("/i/<slug>/panel/delete/<ticket_id>", methods=["POST"])
@tenant_login_required
def tenant_delete_ticket(slug, ticket_id):
    tenant = get_tenant_by_slug(slug)
    delete_ticket_by_id(tenant["id"], ticket_id)
    return redirect(url_for("tenant_panel", slug=slug))


@app.route("/admin/login", methods=["GET", "POST"])
def superadmin_login():
    next_url = request.args.get("next") or url_for("superadmin_panel")
    error = None
    if session.get("superadmin_auth"):
        return redirect(url_for("superadmin_panel"))

    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "").strip()
        if u == SUPERADMIN_USERNAME and p == SUPERADMIN_PASSWORD:
            session["superadmin_auth"] = True
            return redirect(next_url)
        error = "Kullanıcı adı veya şifre hatalı."

    return render_template_string(SUPERADMIN_LOGIN_HTML, error=error)


@app.route("/admin/logout", methods=["POST"])
def superadmin_logout():
    session.pop("superadmin_auth", None)
    return redirect(url_for("superadmin_login"))


@app.route("/admin")
@superadmin_required
def superadmin_panel():
    tenants = get_all_tenants()
    return render_template_string(SUPERADMIN_HTML, tenants=tenants, iban_number=IBAN_NUMBER)


@app.route("/admin/tenant/<int:tenant_id>/approve", methods=["POST"])
@superadmin_required
def superadmin_approve_tenant(tenant_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tenants
                SET is_active = TRUE,
                    payment_requested = FALSE,
                    activated_at = NOW(),
                    expires_at = NOW() + INTERVAL '30 days'
                WHERE id = %s
                """,
                (tenant_id,),
            )
    return redirect(url_for("superadmin_panel"))


@app.route("/admin/tenant/<int:tenant_id>/unlock-qr", methods=["POST"])
@superadmin_required
def superadmin_unlock_qr_addon(tenant_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tenants
                SET qr_addon_active = TRUE,
                    qr_addon_requested = FALSE
                WHERE id = %s
                """,
                (tenant_id,),
            )
    return redirect(url_for("superadmin_panel"))


@app.route("/admin/tenant/<int:tenant_id>/extend", methods=["POST"])
@superadmin_required
def superadmin_extend_tenant(tenant_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tenants
                SET is_active = TRUE,
                    expires_at = GREATEST(COALESCE(expires_at, NOW()), NOW()) + INTERVAL '30 days'
                WHERE id = %s
                """,
                (tenant_id,),
            )
    return redirect(url_for("superadmin_panel"))


@app.route("/admin/tenant/<int:tenant_id>/suspend", methods=["POST"])
@superadmin_required
def superadmin_suspend_tenant(tenant_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET is_active = FALSE WHERE id = %s", (tenant_id,))
    return redirect(url_for("superadmin_panel"))


@app.route("/admin/tenant/<int:tenant_id>/edit", methods=["POST"])
@superadmin_required
def superadmin_edit_tenant(tenant_id):
    business_name = request.form.get("business_name", "").strip()
    owner_email = request.form.get("owner_email", "").strip().lower()
    plan = request.form.get("plan", "starter").strip()
    module_type = request.form.get("module_type", "genel").strip()
    new_password = request.form.get("new_password", "").strip()
    try:
        table_count = max(1, min(200, int(request.form.get("table_count", 8))))
    except ValueError:
        table_count = 8

    if plan not in {"starter", "pro"}:
        plan = "starter"
    valid_modules = {
        "genel", "kafe-randevu", "berber-randevu", "masa-qr",
        "mobil-saha", "web-otomasyon", "masaustu-otomasyon"
    }
    if module_type not in valid_modules:
        module_type = "genel"

    if business_name and owner_email:
        with get_db() as conn:
            with conn.cursor() as cur:
                if len(new_password) >= 4:
                    cur.execute(
                        """
                        UPDATE tenants
                        SET business_name = %s, owner_email = %s, plan = %s,
                            module_type = %s, table_count = %s, password_hash = %s
                        WHERE id = %s
                        """,
                        (business_name, owner_email, plan, module_type, table_count, generate_password_hash(new_password), tenant_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE tenants
                        SET business_name = %s, owner_email = %s, plan = %s,
                            module_type = %s, table_count = %s
                        WHERE id = %s
                        """,
                        (business_name, owner_email, plan, module_type, table_count, tenant_id),
                    )
    return redirect(url_for("superadmin_panel"))


@app.route("/admin/tenant/<int:tenant_id>/delete", methods=["POST"])
@superadmin_required
def superadmin_delete_tenant(tenant_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenants WHERE id = %s AND slug != 'kolay-vitrin'", (tenant_id,))
    return redirect(url_for("superadmin_panel"))


@app.route("/admin/tenant/<int:tenant_id>/plan", methods=["POST"])
@superadmin_required
def superadmin_tenant_plan(tenant_id):
    plan = request.form.get("plan", "starter").strip()
    if plan not in {"starter", "pro"}:
        plan = "starter"
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET plan = %s WHERE id = %s", (plan, tenant_id))
    return redirect(url_for("superadmin_panel"))


if __name__ == "__main__":
    app.run(debug=True)
