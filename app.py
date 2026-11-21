import functools
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from flask import (
    Flask,
    abort,
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

MODULE_LABELS = {
    "kafe-randevu": "Kafe & Restoran Masa Randevu",
    "berber-randevu": "Berber & Kuaför Saat Randevu",
    "masa-qr": "Masa QR Sipariş & Garson Çağır",
    "genel": "Genel Talep Formu",
}

SERVICES_DATA = [
    {
        "id": "mobil-otomasyon",
        "tag": "Mobil Otomasyon",
        "title": "Mobil Uygulama & Saha Akışları",
        "image": "mobilsaha.jpg",
        "short": "Android ve mobil tarafta tekrarlayan işlemleri otomatikleştiren, anlık bildirim ve hızlı işlem sunan çözümler.",
        "details": "Saha ekipleri, sipariş takibi, bildirim yönetimi ve mobil cihaz üzerinden yürütülen tekrarlı operasyonları tek dokunuşa indiren özel mobil otomasyon yapıları.",
        "features": [
            "Android uyumlu hızlı arayüz ve anlık bildirim akışı",
            "Tekrarlayan saha işlemlerini otomatikleştirme",
            "Web panel ve sunucu ile gerçek zamanlı veri senkronizasyonu",
            "İşletmeye özel sade ve anlaşılır kullanım ekranları"
        ]
    },
    {
        "id": "web-otomasyon",
        "tag": "Web Otomasyon",
        "title": "Web Panelleri, Formlar & Botlar",
        "image": "webotom.jpg",
        "short": "Tarayıcı üzerinden çalışan yönetim ekranları, otomatik veri işleme, sipariş/talep akışları ve entegrasyonlar.",
        "details": "İşletmenin tüm verilerini tarayıcıdan yönetebileceğin admin panelleri, otomatik veri toplama/işleme botları ve müşteri talep akışları.",
        "features": [
            "Mobil ve masaüstü uyumlu modern yönetim panelleri",
            "Otomatik veri çekme, raporlama ve bildirim botları",
            "Telegram, WhatsApp ve harici servis entegrasyonları",
            "Hızlı kurulum ve düşük bakım maliyeti"
        ]
    },
    {
        "id": "masaustu-otomasyon",
        "tag": "Masaüstü Otomasyon",
        "title": "Kasa, Barkod & Yerel Programlar",
        "image": "masaustuoto.jpg",
        "short": "İşletme bilgisayarlarında hızlı çalışan stok, barkod okuma, fiş/kayıt ve operasyon otomasyon araçları.",
        "details": "İnternet kesintilerinden etkilenmeyen veya yerel ağda ışık hızında çalışan barkod, stok, kasa ve ofis otomasyon yazılımları.",
        "features": [
            "USB barkod okuyucu ve hızlı ürün ekleme desteği",
            "Anlık stok takibi, satış kaydı ve günlük özet raporlar",
            "Tek tıkla çalışan masaüstü (.exe) uygulama yapısı",
            "Karmaşık menülerden arındırılmış pratik kasa ekranı"
        ]
    },
    {
        "id": "kafe-restoran-randevu",
        "tag": "Kafe & Restoran",
        "title": "Masa & Kişi Bazlı Randevu Sistemi",
        "image": "kaferesrandevu.jpg",
        "short": "Yoğun saatlerde masa planlamasını kolaylaştıran, müşteri rezervasyonlarını düzenli yöneten randevu altyapısı.",
        "details": "Kafe ve restoranlarda özel gün, akşam yoğunluğu veya grup rezervasyonlarını karmaşa yaşamadan planlamanı sağlayan masa rezervasyon sistemi.",
        "features": [
            "Tarih, saat ve kişi sayısına göre hızlı masa talebi",
            "İşletme panelinden tek tıkla onay veya alternatif saat önerisi",
            "Müşteri iletişim bilgisi ve özel not yönetimi",
            "Boş/dolu masa yoğunluğunu tek ekranda görme imkânı"
        ]
    },
    {
        "id": "berber-kuafor-randevu",
        "tag": "Berber & Kuaför",
        "title": "Salon Randevu & Saat Yönetimi",
        "image": "berberrandevu.jpg",
        "short": "Müşterilerin müsait saatleri kolayca seçebildiği, çakışmayı önleyen ve salon düzenini koruyan randevu sistemi.",
        "details": "Telefon trafiğini azaltan, müşterinin doğrudan müsait saati seçip talep bıraktığı ve ustanın cebinden yönetebildiği modern salon randevu altyapısı.",
        "features": [
            "Saat çakışmasını önleyen akıllı slot kontrolü",
            "Saç, sakal, bakım gibi hizmet süresine göre planlama",
            "Usta/personel bazlı ayrı randevu takvimi",
            "Mobil ekrandan hızlı onay, iptal ve saat güncelleme"
        ]
    },
    {
        "id": "masa-qr-garson",
        "tag": "Masa QR & Garson",
        "title": "QR Sipariş & Garson Çağır Sistemi",
        "image": "kaferestoqr.jpg",
        "short": "Masadaki QR kod üzerinden menü/sipariş akışı ve tek dokunuşla garson çağırma özelliğiyle servis hızını artırır.",
        "details": "Müşterilerin masadaki QR kodu okutarak menüyü incelemesini, sipariş vermesini veya tek tuşla garson/hesap çağırmasını sağlayan masa yönetim sistemi.",
        "features": [
            "Her masaya özel tanımlı QR kod yapısı",
            "Tek dokunuşla 'Garson Çağır' ve 'Hesap İste' bildirimi",
            "Kasa/bar ekranına anında düşen masa sipariş akışı",
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


def save_uploaded_image(subdir, tenant_id, file_storage):
    if not file_storage or not file_storage.filename:
        return ""
    ext = Path(secure_filename(file_storage.filename)).suffix.lower()
    if ext not in ALLOWED_IMG_EXTS:
        return ""
    target_dir = subdir / str(tenant_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex[:12]}{ext}"
    file_storage.save(str(target_dir / fname))
    return fname


def get_db():
    parsed = urlparse(DATABASE_URL)
    sslmode = (
        "require"
        if "supabase.co" in (parsed.hostname or "") or "pooler.supabase.com" in (parsed.hostname or "")
        else "prefer"
    )
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, sslmode=sslmode)


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
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS activated_at TIMESTAMP;")
                cur.execute("UPDATE tenants SET plan = 'starter' WHERE plan = 'free';")

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
                            table_count, whatsapp_number, payment_note, payment_requested, is_active, activated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, 8, %s, %s, FALSE, TRUE, NOW())
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
                ORDER BY t.is_active ASC, t.payment_requested DESC, t.id DESC
                """
            )
            return cur.fetchall()


def create_tenant(business_name, owner_email, password, raw_slug="", plan="starter", module_type="genel", whatsapp_number=""):
    base_slug = slugify(raw_slug or business_name)
    valid_modules = {"genel", "kafe-randevu", "berber-randevu", "masa-qr"}
    mod = module_type if module_type in valid_modules else "genel"
    chosen_plan = plan if plan in {"starter", "pro"} else "starter"
    default_tables = 8 if mod == "kafe-randevu" else 4
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
                    module_type, table_count, whatsapp_number, is_active, payment_requested
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, FALSE)
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
            return cur.fetchall()


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
    .mini-list li { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; border-radius: 11px; background: rgba(8, 13, 11, 0.65); border: 1px solid rgba(16, 185, 129, 0.14); font-size: 0.86rem; gap: 8px; flex-wrap: wrap; }
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
            müşteri randevu linkin ile işletme yönetim panelin hemen aktif olsun.
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
            <li><span>Starter Paket</span><span class="pill">{{ price_starter }}</span></li>
            <li><span>Pro Paket</span><span class="pill-amber">{{ price_pro }}</span></li>
            <li><span>Modül Seçimi</span><span class="pill">İlk Üyelikte Kilitlenir</span></li>
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
          <p>Kartlara tıklayarak modül detaylarını görebilirsin.</p>
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
          <p>İlk üyelikte seçtiğin modül panele kilitlenir; IBAN ödemesi onaylandığında sistem aktif olur.</p>
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
                  <option value="starter">Starter — {{ price_starter }}</option>
                  <option value="pro">Pro — {{ price_pro }}</option>
                </select>
              </div>
            </div>

            <div>
              <label for="module_type">Modül Seçimi (Üyelik Sonrası Kilitlenir)</label>
              <select id="module_type" name="module_type">
                <option value="kafe-randevu">Kafe &amp; Restoran Masa Randevu + Menü</option>
                <option value="berber-randevu">Berber &amp; Kuaför Saat Randevu</option>
                <option value="masa-qr">Masa QR Sipariş &amp; Garson Çağır</option>
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
        <a href="#saas-basla" class="btn-primary" onclick="closeServiceModal()">Bu Modülle Hesap Aç</a>
      </div>
    </div>
  </div>

  <script>
    const SERVICES = {{ services | tojson }};
    function openServiceModal(id) {
      const item = SERVICES.find(s => s.id === id);
      if (!item) return;
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
      <div style="font-size:0.78rem;color:#fbbf24;font-weight:800;">HESAP DURUMU: ÖDEME ONAYI BEKLENİYOR</div>
      <h1 style="font-size:1.28rem;">{{ tenant.business_name }}</h1>
      <p style="color:#9ca3af;font-size:0.88rem;">
        Hesabın açıldı ve modülün <strong>{{ mod_label }}</strong> olarak kilitlendi.
        IBAN ödemesi onaylandığında müşteri randevu linkin aktif olur.
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

TENANT_PUBLIC_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{{ tenant.business_name }} — Randevu &amp; Talep</title>
  <style>
    * { box-sizing:border-box; margin:0; padding:0; }
    body { background:#080d0b; color:#f8fafc; font-family:Inter,system-ui,sans-serif; padding:20px 14px 48px; overflow-x:hidden; }
    .wrap { max-width:940px; margin:0 auto; display:grid; gap:16px; }
    .top { display:flex; justify-content:space-between; align-items:center; gap:12px; border-bottom:1px solid rgba(16,185,129,0.22); padding-bottom:14px; }
    .brand-row { display:flex; align-items:center; gap:12px; min-width:0; }
    .biz-logo { width:48px; height:48px; border-radius:12px; object-fit:cover; border:1px solid rgba(16,185,129,0.35); background:#0f1714; flex-shrink:0; display:block; }
    .biz-logo-fallback { width:48px; height:48px; border-radius:12px; display:grid; place-items:center; font-weight:900; font-size:1.1rem; color:#04130d; background:linear-gradient(135deg,#34d399,#10b981); flex-shrink:0; }
    .btn-main { text-decoration:none; padding:11px 16px; border-radius:10px; font-weight:800; font-size:0.9rem; background:linear-gradient(135deg,#34d399,#10b981); color:#04130d; border:none; cursor:pointer; display:inline-flex; align-items:center; justify-content:center; width:100%; }
    .card { background:#121d18; border:1px solid rgba(16,185,129,0.22); border-radius:16px; padding:18px; display:grid; gap:13px; }
    .row-2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .row-3 { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }
    label { display:block; font-size:0.84rem; color:#d1d5db; margin-bottom:5px; font-weight:600; }
    input, select, textarea { width:100%; padding:10px 12px; border-radius:10px; border:1px solid rgba(16,185,129,0.22); background:#0f1714; color:#f8fafc; font-size:0.92rem; }
    .ok { padding:12px 14px; border-radius:10px; background:rgba(16,185,129,0.16); border:1px solid rgba(16,185,129,0.4); color:#a7f3d0; font-weight:600; font-size:0.9rem; }
    .badge { font-size:0.74rem; color:#34d399; background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.28); padding:3px 9px; border-radius:999px; font-weight:700; display:inline-block; margin-bottom:4px; }
    .menu-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:11px; }
    .menu-card { background:#0f1714; border:1px solid rgba(16,185,129,0.18); border-radius:12px; padding:11px; display:grid; gap:8px; }
    .menu-img { width:100%; aspect-ratio:16/10; object-fit:cover; border-radius:8px; display:block; }
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
    <div class="ok">Kaydınız <strong>{{ tenant.business_name }}</strong> tarafına başarıyla iletildi!</div>
    {% endif %}

    {% if tenant.module_type == 'kafe-randevu' %}
    <form class="card" method="POST">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;">
        <h2 style="font-size:1.1rem;">Masa Randevusu &amp; İsteğe Bağlı Menü</h2>
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

      <div class="row-2">
        <div>
          <label>Kişi Sayısı</label>
          <select name="guest_count">
            <option value="2 Kişilik">2 Kişilik</option>
            <option value="4 Kişilik">4 Kişilik</option>
            <option value="6 Kişilik">6 Kişilik</option>
            <option value="8+ Kişilik Grup">8+ Kişilik Grup</option>
          </select>
        </div>
        <div>
          <label>Menü Tercihi</label>
          <select name="menu_mode">
            <option value="decide_on_arrival">Gelince Karar Vereceğim (Menü Seçmeden Devam Et)</option>
            <option value="preselect">Şimdi Menüden Seçim Yapıyorum</option>
          </select>
        </div>
      </div>

      {% if menu_items %}
      <div>
        <label>Menü Ürünleri (İsteğe Bağlı Seçebilirsin)</label>
        <div class="menu-grid">
          {% for item in menu_items %}
          <div class="menu-card">
            {% if item.image_filename %}
              <img src="/images/menu/{{ tenant.id }}/{{ item.image_filename }}" alt="{{ item.name }}" class="menu-img" onerror="this.style.display='none'" />
            {% endif %}
            <label class="menu-check">
              <input type="checkbox" name="menu_item" value="{{ item.name }}{% if item.price %} ({{ item.price }}){% endif %}" />
              <span>
                <strong>{{ item.name }}</strong>
                {% if item.price %}<span style="color:#34d399;font-weight:700;"> • {{ item.price }}</span>{% endif %}
                {% if item.description %}<div style="font-size:0.78rem;color:#9ca3af;margin-top:2px;">{{ item.description }}</div>{% endif %}
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
          const opt = document.createElement("option");
          opt.value = `Masa ${tNo}`;
          opt.textContent = `Masa ${tNo} (Müsait)`;
          tableSel.appendChild(opt);
        });
      }

      updateTableOptions();
    </script>

    {% elif tenant.module_type == 'berber-randevu' %}
    <form class="card" method="POST">
      <h2 style="font-size:1.1rem;">Salon Randevu Talebi</h2>
      <div class="row-2">
        <div><label>Ad Soyad</label><input type="text" name="name" placeholder="Adınız Soyadınız" required /></div>
        <div><label>Telefon</label><input type="text" name="phone" placeholder="05xx xxx xx xx" required /></div>
      </div>
      <div class="row-2">
        <div>
          <label>Hizmet Seçimi</label>
          <select name="service">
            <option value="Saç Kesimi">Saç Kesimi</option>
            <option value="Saç + Sakal Tıraşı">Saç + Sakal Tıraşı</option>
            <option value="Sakal Tıraşı & Bakım">Sakal Tıraşı &amp; Bakım</option>
            <option value="Damat / Özel Bakım">Damat / Özel Bakım</option>
          </select>
        </div>
        <div><label>İstenen Gün ve Saat</label><input type="text" name="slot_time" placeholder="Örn: Yarın 15:30" required /></div>
      </div>
      <div><label>Usta Tercihi / Ek Not</label><textarea name="message" rows="3" placeholder="Model veya saat ile ilgili notunuz..." required></textarea></div>
      <button type="submit" class="btn-main">Gönder</button>
    </form>

    {% elif tenant.module_type == 'masa-qr' %}
    <form class="card" method="POST">
      <h2 style="font-size:1.1rem;">Masa Sipariş &amp; Garson İsteği</h2>
      <div class="row-2">
        <div><label>Masa Numarası / Adı</label><input type="text" name="name" placeholder="Örn: Masa 4 veya Bahçe 2" required /></div>
        <div><label>İletişim / Not Kodu (Opsiyonel)</label><input type="text" name="phone" placeholder="Opsiyonel" /></div>
      </div>
      <div>
        <label>Masa İsteği</label>
        <select name="service">
          <option value="Garson Çağır">Garson Çağır</option>
          <option value="Hesap İste">Hesap İste</option>
          <option value="Sipariş Notu / İstek">Sipariş Notu / İstek</option>
        </select>
      </div>
      <div><label>Sipariş veya İstek Detayı</label><textarea name="message" rows="3" placeholder="Örn: 2 Türk kahvesi, su veya hesap rica ediyoruz..." required></textarea></div>
      <button type="submit" class="btn-main">Gönder</button>
    </form>

    {% else %}
    <form class="card" method="POST">
      <h2 style="font-size:1.1rem;">Talep / Randevu Bırak</h2>
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
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{{ tenant.business_name }} — Yönetim Paneli</title>
  <style>
    :root { --bg:#080d0b; --card:#121d18; --soft:#0f1714; --text:#f8fafc; --muted:#9ca3af; --accent:#10b981; --bright:#34d399; --amber:#f59e0b; --border:rgba(16,185,129,0.22); }
    * { box-sizing:border-box; margin:0; padding:0; font-family:Inter,system-ui,sans-serif; }
    body { background:var(--bg); color:var(--text); padding:20px 14px 48px; overflow-x:hidden; }
    .wrap { max-width:1120px; margin:0 auto; display:grid; gap:16px; }
    .top { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; border-bottom:1px solid var(--border); padding-bottom:14px; }
    .btn { text-decoration:none; padding:9px 13px; border-radius:10px; font-weight:700; font-size:0.86rem; border:1px solid var(--border); background:var(--card); color:var(--bright); cursor:pointer; display:inline-flex; align-items:center; justify-content:center; gap:6px; }
    .btn-wa { background:rgba(34,197,94,0.16); border-color:rgba(34,197,94,0.45); color:#86efac; }
    .btn-del { background:rgba(239,68,68,0.14); border-color:rgba(239,68,68,0.35); color:#fca5a5; }
    .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; }
    .stat { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:14px; }
    .stat span { font-size:0.78rem; color:var(--muted); display:block; }
    .stat strong { font-size:1.35rem; color:var(--bright); }
    .card { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:16px; display:grid; gap:12px; }
    .msg { background:var(--soft); padding:12px; border-radius:10px; font-size:0.9rem; word-break:break-word; }
    input, select { padding:9px 10px; border-radius:8px; border:1px solid var(--border); background:var(--soft); color:var(--text); font-size:0.9rem; }
    .locked-pill { padding:8px 12px; border-radius:8px; background:rgba(245,158,11,0.12); border:1px solid rgba(245,158,11,0.35); color:#fcd34d; font-size:0.82rem; font-weight:700; }
    .menu-admin-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }
    .menu-box { background:var(--soft); border:1px solid var(--border); border-radius:12px; padding:12px; display:grid; gap:8px; }
    .menu-thumb { width:100%; aspect-ratio:16/10; object-fit:cover; border-radius:8px; }
    .logo-preview { width:52px; height:52px; border-radius:10px; object-fit:cover; border:1px solid var(--border); }
    .row-flex { display:flex; gap:10px; flex-wrap:wrap; align-items:end; }
    .share-box { background:var(--soft); border:1px dashed rgba(52,211,153,0.45); border-radius:10px; padding:10px 12px; display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; font-size:0.85rem; }
    @media (max-width:768px) {
      .row-flex > div, .row-flex > button { width:100% !important; min-width:0 !important; }
      .top > div { width:100%; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <h1>{{ tenant.business_name }} — Yönetim Paneli</h1>
        <p style="color:var(--muted);font-size:0.84rem;">
          Slug: <code>{{ tenant.slug }}</code> • Plan: <code>{{ tenant.plan|upper }}</code> • Kilitli Modül: <strong>{{ mod_label }}</strong>
        </p>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <form method="POST" action="{{ url_for('tenant_logout', slug=tenant.slug) }}"><button type="submit" class="btn btn-del">Çıkış</button></form>
      </div>
    </div>

    <div class="share-box">
      <span><strong>Müşteri Linki:</strong> <code id="custLinkText">{{ request.url_root }}i/{{ tenant.slug }}</code></span>
      <button type="button" class="btn" onclick="copyCustLink()">Linki Kopyala</button>
    </div>

    <form class="card" method="POST" action="{{ url_for('tenant_update_settings', slug=tenant.slug) }}" enctype="multipart/form-data">
      <div style="font-size:0.84rem;font-weight:800;color:var(--bright);">İŞLETME AYARLARI &amp; LOGO (MODÜL KİLİTLİ: {{ mod_label|upper }})</div>
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
        {% if tenant.module_type == 'kafe-randevu' %}
        <div style="width:130px;">
          <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Masa Sayısı</label>
          <input type="number" name="table_count" min="1" max="200" value="{{ tenant.table_count or 8 }}" style="width:100%;" required />
        </div>
        {% endif %}
        <div class="locked-pill">Modül: {{ mod_label }}</div>
        <button type="submit" class="btn">Ayarları Kaydet</button>
      </div>
    </form>

    {% if tenant.module_type == 'kafe-randevu' %}
    <div class="card">
      <div style="font-size:0.84rem;font-weight:800;color:var(--bright);">MENÜ YÖNETİMİ (EKLE / DÜZENLE / FOTOĞRAF YÜKLE)</div>
      <form method="POST" action="{{ url_for('tenant_add_menu_item', slug=tenant.slug) }}" enctype="multipart/form-data" class="row-flex">
        <div style="flex:1;min-width:160px;">
          <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Ürün Adı</label>
          <input type="text" name="name" placeholder="Örn: Latte veya Burger" style="width:100%;" required />
        </div>
        <div style="width:110px;">
          <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Fiyat</label>
          <input type="text" name="price" placeholder="140 TL" style="width:100%;" />
        </div>
        <div style="flex:1;min-width:160px;">
          <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Kısa Açıklama</label>
          <input type="text" name="description" placeholder="İçerik veya not" style="width:100%;" />
        </div>
        <div style="min-width:170px;">
          <label style="display:block;font-size:0.78rem;color:var(--muted);margin-bottom:4px;">Ürün Fotoğrafı</label>
          <input type="file" name="image" accept=".jpg,.jpeg,.png,.webp" style="width:100%;" />
        </div>
        <button type="submit" class="btn">+ Menüye Ekle</button>
      </form>

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
            <button type="submit" class="btn">Kaydet</button>
          </form>
          <form method="POST" action="{{ url_for('tenant_delete_menu_item', slug=tenant.slug, item_id=item.id) }}" onsubmit="return confirm('Menü ürünü silinsin mi?');">
            <button type="submit" class="btn btn-del" style="width:100%;">Ürünü Sil</button>
          </form>
        </div>
        {% endfor %}
      </div>
      {% else %}
      <p style="color:var(--muted);font-size:0.86rem;">Henüz menü ürünü eklenmedi. Müşteriler randevu alırken "Gelince Karar Vereceğim" seçeneğini kullanabilir veya yukarıdan menü ekleyebilirsin.</p>
      {% endif %}
    </div>
    {% endif %}

    <div class="stats">
      <div class="stat"><span>Toplam Talep</span><strong>{{ tickets|length }}</strong></div>
      <div class="stat"><span>Yeni</span><strong style="color:var(--amber);">{{ yeni_count }}</strong></div>
      <div class="stat"><span>Tamamlanan</span><strong>{{ tamam_count }}</strong></div>
    </div>

    {% for t in tickets %}
    <div class="card">
      <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;">
        <div><strong>{{ t.name }}</strong> — <span style="color:var(--bright);">{{ t.service or 'Genel' }}</span><div style="font-size:0.82rem;color:var(--muted);">{{ t.phone or '-' }} • {{ t.created_at }}</div></div>
        <span style="font-size:0.8rem;font-weight:700;color:var(--amber);">{{ t.status }}</span>
      </div>
      <div class="msg">{{ t.message }}</div>
      <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center;">
        <form method="POST" action="{{ url_for('tenant_update_ticket', slug=tenant.slug, ticket_id=t.id) }}" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <select name="status">
            <option value="Yeni" {% if t.status=='Yeni' %}selected{% endif %}>Yeni</option>
            <option value="İnceleniyor" {% if t.status=='İnceleniyor' %}selected{% endif %}>İnceleniyor</option>
            <option value="Tamamlandı" {% if t.status=='Tamamlandı' %}selected{% endif %}>Tamamlandı</option>
            <option value="İptal" {% if t.status=='İptal' %}selected{% endif %}>İptal</option>
          </select>
          <button type="submit" class="btn">Güncelle</button>
          {% if t.wa_link %}
          <a class="btn btn-wa" href="{{ t.wa_link }}" target="_blank" rel="noopener noreferrer">WhatsApp Yaz</a>
          {% endif %}
        </form>
        <form method="POST" action="{{ url_for('tenant_delete_ticket', slug=tenant.slug, ticket_id=t.id) }}" onsubmit="return confirm('Silinsin mi?');">
          <button type="submit" class="btn btn-del">Sil</button>
        </form>
      </div>
    </div>
    {% else %}
    <div class="card" style="text-align:center;color:var(--muted);">Bu işletmeye ait henüz talep yok.</div>
    {% endfor %}
  </div>

  <script>
    function copyCustLink() {
      const txt = document.getElementById("custLinkText").textContent.trim();
      navigator.clipboard?.writeText(txt);
    }
  </script>
</body>
</html>
"""

SUPERADMIN_LOGIN_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Süper Admin Girişi</title>
  <style>
    * { box-sizing:border-box; margin:0; padding:0; }
    body { min-height:100vh; display:grid; place-items:center; background:#080d0b; color:#f8fafc; font-family:Inter,system-ui,sans-serif; padding:16px; }
    .box { width:100%; max-width:400px; background:#121d18; border:1px solid rgba(16,185,129,0.25); border-radius:16px; padding:22px; display:grid; gap:13px; }
    label { display:block; font-size:0.84rem; margin-bottom:5px; color:#d1d5db; }
    input { width:100%; padding:10px 12px; border-radius:10px; border:1px solid rgba(16,185,129,0.25); background:#0f1714; color:#f8fafc; }
    button { padding:11px; border-radius:10px; border:none; background:linear-gradient(135deg,#34d399,#10b981); color:#04130d; font-weight:800; cursor:pointer; width:100%; }
  </style>
</head>
<body>
  <form class="box" method="POST">
    <h1 style="font-size:1.2rem;">Süper Admin Girişi</h1>
    {% if error %}<div style="color:#fca5a5;font-size:0.86rem;">{{ error }}</div>{% endif %}
    <div><label>Kullanıcı Adı</label><input type="text" name="username" required /></div>
    <div><label>Şifre</label><input type="password" name="password" required /></div>
    <button type="submit">Giriş Yap</button>
  </form>
</body>
</html>
"""

SUPERADMIN_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Süper Admin — IBAN Ödeme Onayı &amp; İşletmeler</title>
  <style>
    :root { --bg:#080d0b; --card:#121d18; --soft:#0f1714; --text:#f8fafc; --muted:#9ca3af; --accent:#10b981; --bright:#34d399; --amber:#f59e0b; --danger:#ef4444; --border:rgba(16,185,129,0.22); }
    * { box-sizing:border-box; margin:0; padding:0; font-family:Inter,system-ui,sans-serif; }
    body { background:var(--bg); color:var(--text); padding:20px 14px 48px; overflow-x:hidden; }
    .wrap { max-width:1140px; margin:0 auto; display:grid; gap:16px; }
    .top { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; border-bottom:1px solid var(--border); padding-bottom:14px; }
    .btn { text-decoration:none; padding:8px 13px; border-radius:9px; font-weight:700; font-size:0.84rem; border:1px solid var(--border); background:var(--card); color:var(--bright); cursor:pointer; display:inline-flex; align-items:center; justify-content:center; }
    .btn-approve { background:linear-gradient(135deg,#34d399,#10b981); color:#04130d; border:none; font-weight:800; }
    .btn-suspend { background:rgba(239,68,68,0.15); border-color:rgba(239,68,68,0.4); color:#fca5a5; }
    .card { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:16px; display:grid; gap:10px; }
    .card.pending { border-color:rgba(245,158,11,0.48); }
    .badge-on { padding:3px 9px; border-radius:999px; font-size:0.75rem; font-weight:800; background:rgba(16,185,129,0.16); color:#6ee7b7; }
    .badge-off { padding:3px 9px; border-radius:999px; font-size:0.75rem; font-weight:800; background:rgba(245,158,11,0.18); color:#fcd34d; }
    select { padding:7px 10px; border-radius:8px; border:1px solid var(--border); background:var(--soft); color:var(--text); }
    @media (max-width:768px) {
      .card > div > div:last-child { width:100%; }
      .card > div > div:last-child form, .card > div > div:last-child a { width:100%; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <h1>Süper Admin — IBAN Ödeme Onayı</h1>
        <p style="color:var(--muted);font-size:0.84rem;">Toplam {{ tenants|length }} işletme • IBAN: <code>{{ iban_number }}</code></p>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <form method="POST" action="{{ url_for('superadmin_logout') }}"><button type="submit" class="btn">Çıkış</button></form>
      </div>
    </div>

    {% for tn in tenants %}
    <div class="card {% if not tn.is_active %}pending{% endif %}">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
        <div>
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <strong>{{ tn.business_name }}</strong>
            <code>/i/{{ tn.slug }}</code>
            {% if tn.is_active %}
              <span class="badge-on">AKTİF</span>
            {% else %}
              <span class="badge-off">ONAY BEKLİYOR</span>
            {% endif %}
            {% if tn.payment_requested and not tn.is_active %}
              <span class="badge-off">ÖDEME BİLDİRİMİ VAR</span>
            {% endif %}
          </div>
          <div style="font-size:0.82rem;color:var(--muted);margin-top:4px;">
            {{ tn.owner_email }} • Paket: <strong>{{ tn.plan|upper }}</strong> • Modül: <code>{{ tn.module_type }}</code> • Masa: {{ tn.table_count or '-' }} • Talep: {{ tn.ticket_count }}
            {% if tn.payment_note %} • Not: <span style="color:#fcd34d;">{{ tn.payment_note }}</span>{% endif %}
          </div>
        </div>

        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <a class="btn" href="{{ url_for('tenant_public', slug=tn.slug) }}">Müşteri Linki</a>
          <a class="btn" href="{{ url_for('tenant_panel', slug=tn.slug) }}">Panel</a>

          {% if not tn.is_active %}
          <form method="POST" action="{{ url_for('superadmin_approve_tenant', tenant_id=tn.id) }}">
            <button type="submit" class="btn btn-approve" style="width:100%;">Ödeme Alındı &amp; Onayla</button>
          </form>
          {% else %}
          <form method="POST" action="{{ url_for('superadmin_suspend_tenant', tenant_id=tn.id) }}">
            <button type="submit" class="btn btn-suspend" style="width:100%;">Askıya Al</button>
          </form>
          {% endif %}

          <form method="POST" action="{{ url_for('superadmin_tenant_plan', tenant_id=tn.id) }}" style="display:flex;gap:6px;">
            <select name="plan">
              <option value="starter" {% if tn.plan!='pro' %}selected{% endif %}>STARTER</option>
              <option value="pro" {% if tn.plan=='pro' %}selected{% endif %}>PRO</option>
            </select>
            <button type="submit" class="btn">Plan Kaydet</button>
          </form>
        </div>
      </div>
    </div>
    {% endfor %}
  </div>
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
    target_dir = LOGO_IMAGES_DIR / str(tenant_id)
    candidate = target_dir / safe_name
    if candidate.exists() and candidate.is_file():
        return send_from_directory(target_dir, safe_name)
    abort(404)


@app.route("/images/menu/<int:tenant_id>/<path:filename>")
def serve_menu_image(tenant_id, filename):
    safe_name = Path(filename).name
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

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        raw_service = request.form.get("service", "").strip()
        slot_time = request.form.get("slot_time", "").strip()
        table_no = request.form.get("table_no", "").strip()
        guest_count = request.form.get("guest_count", "").strip()
        res_date = request.form.get("res_date", selected_date).strip()
        menu_mode = request.form.get("menu_mode", "decide_on_arrival").strip()
        selected_menu = request.form.getlist("menu_item")
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
            if menu_mode == "preselect" and selected_menu:
                parts.append("Menü Seçimi: " + ", ".join(selected_menu))
            else:
                parts.append("Menü: Gelince Karar Verecek")
            if raw_message:
                parts.append(f"Not: {raw_message}")
            message = " | ".join(parts)
        elif mod_type == "berber-randevu":
            service = raw_service or "Salon Randevu"
            parts = []
            if slot_time:
                parts.append(f"Saat: {slot_time}")
            if raw_message:
                parts.append(f"Not: {raw_message}")
            message = " | ".join(parts)
        elif mod_type == "masa-qr":
            service = raw_service or "Masa QR İsteği"
            message = raw_message
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

    tickets = load_tickets(tenant["id"])
    menu_items = get_menu_items(tenant["id"]) if mod_type == "kafe-randevu" else []
    yeni_count = sum(1 for t in tickets if (t.get("status") or "Yeni") == "Yeni")
    tamam_count = sum(1 for t in tickets if t.get("status") == "Tamamlandı")
    return render_template_string(
        TENANT_PANEL_HTML,
        tenant=tenant,
        mod_label=mod_label,
        menu_items=menu_items,
        tickets=tickets,
        yeni_count=yeni_count,
        tamam_count=tamam_count,
    )


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
    if (tenant.get("module_type") or "genel") != "kafe-randevu":
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
                "UPDATE tenants SET is_active = TRUE, payment_requested = FALSE, activated_at = NOW() WHERE id = %s",
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
