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
LEGACY_JSON_FILE = BASE_DIR / "tickets.json"

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
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS payment_note TEXT DEFAULT '';")
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS payment_requested BOOLEAN NOT NULL DEFAULT FALSE;")
                cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS activated_at TIMESTAMP;")
                cur.execute("UPDATE tenants SET plan = 'starter' WHERE plan = 'free';")

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
                            whatsapp_number, payment_note, payment_requested, is_active, activated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, TRUE, NOW())
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
                    module_type, whatsapp_number, is_active, payment_requested
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, FALSE)
                RETURNING *
                """,
                (
                    candidate,
                    business_name.strip(),
                    owner_email.strip().lower(),
                    generate_password_hash(password),
                    chosen_plan,
                    mod,
                    whatsapp_number.strip(),
                ),
            )
            return cur.fetchone()


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
    html { scroll-behavior: smooth; }
    body {
      background:
        radial-gradient(circle at 12% 8%, rgba(16, 185, 129, 0.15), transparent 36%),
        radial-gradient(circle at 88% 16%, rgba(245, 158, 11, 0.11), transparent 38%),
        var(--bg);
      color: var(--text); line-height: 1.6; overflow-x: hidden;
    }
    .container { max-width: 1180px; margin: 0 auto; padding: 0 22px; }
    .wp-icon { width: 18px; height: 18px; flex-shrink: 0; display: inline-block; }

    .navbar { position: sticky; top: 0; z-index: 40; backdrop-filter: blur(14px); background: rgba(8, 13, 11, 0.85); border-bottom: 1px solid var(--border); }
    .nav-inner { display: flex; align-items: center; justify-content: space-between; min-height: 72px; padding: 10px 0; gap: 14px; flex-wrap: wrap; }
    .brand { display: inline-flex; align-items: center; gap: 11px; font-weight: 800; font-size: 1.04rem; color: var(--text); text-decoration: none; }
    .brand-logo-img { height: 40px; width: auto; max-width: 58px; object-fit: contain; border-radius: 10px; display: block; }
    .brand-badge { width: 32px; height: 32px; border-radius: 10px; display: grid; place-items: center; font-weight: 900; color: #04130d; background: linear-gradient(135deg, var(--accent-bright), var(--accent-2)); }
    .brand-text small { display: block; font-size: 0.72rem; font-weight: 600; color: var(--accent-bright); }
    .nav-links { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .nav-btn { color: var(--muted); text-decoration: none; font-size: 0.9rem; font-weight: 600; padding: 8px 13px; border-radius: 10px; border: 1px solid transparent; display: inline-flex; align-items: center; gap: 6px; }
    .nav-btn:hover, .nav-btn.active { color: var(--text); background: rgba(16, 185, 129, 0.12); border-color: rgba(16, 185, 129, 0.32); }
    .nav-cta { color: #04130d; background: linear-gradient(135deg, var(--accent-bright), var(--accent)); font-weight: 800; }
    .nav-wa { color: #dcfce7; background: rgba(34, 197, 94, 0.16); border: 1px solid rgba(34, 197, 94, 0.42); font-weight: 700; }

    .hero { padding: 60px 0 40px; display: grid; grid-template-columns: 1.25fr 0.75fr; gap: 28px; align-items: center; }
    .badge { display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: 999px; font-size: 0.82rem; font-weight: 700; color: var(--accent-bright); background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.28); margin-bottom: 14px; }
    .hero h1 { font-size: clamp(2rem, 4.2vw, 3.1rem); line-height: 1.14; margin-bottom: 14px; }
    .hero h1 span { background: linear-gradient(135deg, var(--accent-bright), var(--accent-2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .hero p { color: var(--muted); font-size: 1rem; max-width: 630px; margin-bottom: 22px; }
    .hero-actions { display: flex; gap: 12px; flex-wrap: wrap; }

    .btn-primary, .btn-secondary, .btn-wa {
      text-decoration: none; padding: 11px 17px; border-radius: 11px; font-weight: 700; font-size: 0.9rem;
      display: inline-flex; align-items: center; gap: 8px; cursor: pointer;
    }
    .btn-primary { background: linear-gradient(135deg, var(--accent-bright), var(--accent)); color: #04130d; border: none; }
    .btn-secondary { background: var(--card); color: var(--text); border: 1px solid var(--border); }
    .btn-wa { background: linear-gradient(135deg, #22c55e, #16a34a); color: #052e16; border: none; }

    .hero-panel { background: linear-gradient(160deg, rgba(19, 32, 27, 0.94), rgba(10, 17, 14, 0.94)); border: 1px solid var(--border); border-radius: 20px; padding: 22px; }
    .panel-title { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-2); margin-bottom: 12px; font-weight: 800; }
    .mini-list { list-style: none; display: grid; gap: 10px; }
    .mini-list li { display: flex; justify-content: space-between; align-items: center; padding: 10px 13px; border-radius: 12px; background: rgba(8, 13, 11, 0.65); border: 1px solid rgba(16, 185, 129, 0.14); font-size: 0.9rem; gap: 8px; }
    .pill { font-size: 0.73rem; padding: 3px 9px; border-radius: 999px; background: rgba(16, 185, 129, 0.16); color: var(--accent-bright); font-weight: 700; border: 1px solid rgba(16, 185, 129, 0.3); }
    .pill-amber { font-size: 0.73rem; padding: 3px 9px; border-radius: 999px; background: rgba(245, 158, 11, 0.16); color: #fcd34d; font-weight: 700; border: 1px solid rgba(245, 158, 11, 0.36); }

    section.block { padding: 52px 0; }
    .section-head { margin-bottom: 20px; }
    .section-head span { color: var(--accent-2); font-size: 0.82rem; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; }
    .section-head h2 { font-size: clamp(1.5rem, 3vw, 2.15rem); margin-top: 6px; margin-bottom: 8px; }
    .section-head p { color: var(--muted); max-width: 760px; }

    .services-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 18px; }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 18px; overflow: hidden; display: flex; flex-direction: column; justify-content: space-between; cursor: pointer; }
    .card:hover { border-color: rgba(16, 185, 129, 0.48); }
    .card-thumb { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; display: block; border-bottom: 1px solid rgba(16, 185, 129, 0.16); }
    .card-body { padding: 18px 20px 12px; }
    .card-tag { display: inline-block; font-size: 0.76rem; font-weight: 700; color: var(--accent-bright); background: rgba(16, 185, 129, 0.12); padding: 4px 10px; border-radius: 8px; margin-bottom: 8px; }
    .card h3 { font-size: 1.1rem; margin-bottom: 6px; }
    .card p { color: var(--muted); font-size: 0.9rem; }
    .card-footer { display: flex; align-items: center; justify-content: space-between; padding: 12px 20px 16px; border-top: 1px solid rgba(156, 163, 175, 0.12); }
    .detail-link { background: transparent; border: none; color: var(--accent-2); font-weight: 700; font-size: 0.9rem; cursor: pointer; }

    .saas-grid { display: grid; grid-template-columns: 1.05fr 0.95fr; gap: 22px; align-items: start; }
    .saas-card { background: var(--card); border: 1px solid var(--border); border-radius: 18px; padding: 24px; display: grid; gap: 14px; }
    .iban-box { background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.35); border-radius: 14px; padding: 16px; display: grid; gap: 6px; }
    .iban-code { font-family: monospace; font-size: 0.98rem; font-weight: 800; color: #fcd34d; background: rgba(0, 0, 0, 0.35); padding: 8px 10px; border-radius: 8px; }
    .row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    label { display: block; font-size: 0.84rem; color: #d1d5db; margin-bottom: 6px; font-weight: 600; }
    input, select, textarea { width: 100%; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--border); background: var(--bg-soft); color: var(--text); font-size: 0.92rem; }
    .submit-btn { padding: 12px 18px; border-radius: 11px; border: none; cursor: pointer; font-weight: 800; font-size: 0.94rem; color: #04130d; background: linear-gradient(135deg, var(--accent-bright), var(--accent-2)); }
    .alert-ok { padding: 14px 16px; border-radius: 12px; background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); color: #a7f3d0; font-size: 0.9rem; }
    .alert-err { padding: 14px 16px; border-radius: 12px; background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); color: #fca5a5; font-size: 0.9rem; }

    .modal-backdrop { position: fixed; inset: 0; z-index: 90; background: rgba(4, 8, 6, 0.78); backdrop-filter: blur(8px); display: none; align-items: center; justify-content: center; padding: 20px; }
    .modal-backdrop.open { display: flex; }
    .modal-box { width: 100%; max-width: 600px; max-height: 90vh; overflow-y: auto; background: #101915; border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 22px; padding: 24px; }
    .modal-img { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 14px; margin: 12px 0; }
    .modal-list { list-style: none; display: grid; gap: 8px; margin: 12px 0 18px; }
    .modal-list li { padding: 9px 12px; border-radius: 10px; background: rgba(8, 13, 11, 0.72); border: 1px solid rgba(16, 185, 129, 0.16); font-size: 0.9rem; }

    footer { border-top: 1px solid var(--border); padding: 24px 0; margin-top: 28px; color: var(--muted); font-size: 0.88rem; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
    footer a { color: var(--muted); text-decoration: none; }

    @media (max-width: 920px) { .hero, .saas-grid, .row-2 { grid-template-columns: 1fr; } }
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
        <a href="{{ url_for('superadmin_panel') }}" class="nav-btn">Admin Onay</a>
        <a href="https://wa.me/{{ wa_number }}?text={{ 'Merhaba KOLAY Otomasyon, IBAN odeme ve paketler hakkinda bilgi almak istiyorum.' | urlencode }}" target="_blank" rel="noopener noreferrer" class="nav-btn nav-wa" aria-label="WhatsApp">
          <svg class="wp-icon"><use href="#icon-whatsapp"></use></svg>
          <span>WhatsApp</span>
        </a>
      </nav>
    </div>
  </header>

  <main>
    <section id="anasayfa" class="hero">
      <div class="container" style="display: contents;">
        <div>
          <div class="badge">IBAN Ödemeli &amp; Admin Onaylı Mikro-SaaS</div>
          <h1>İşletmen İçin <span>Kendi Panelini Aç</span>, Ödeme Onayıyla Aktif Et</h1>
          <p>
            İşletme hesabını oluştur, IBAN üzerinden ödemeni yap ve admin onayının ardından sana özel
            <code>/i/slug</code> müşteri sayfan ile <code>/i/slug/panel</code> yönetim ekranını anında kullanmaya başla.
          </p>
          <div class="hero-actions">
            <a href="#saas-basla" class="btn-primary">İşletme Hesabı Oluştur</a>
            <a href="{{ url_for('superadmin_panel') }}" class="btn-secondary">Admin Onay Paneli</a>
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
            <li><span>Ödeme Yöntemi</span><span class="pill">IBAN Havale / FAST</span></li>
            <li><span>Aktivasyon</span><span class="pill">Admin Onayı Sonrası</span></li>
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
          <p>Kayıt sonrası IBAN'a ödeme yapıp ödeme bildirimi gönderebilirsin; admin panelinde onaylandığında sistem aktif olur.</p>
        </div>

        {% if created_tenant %}
        <div class="alert-ok" style="margin-bottom: 18px;">
          <strong>{{ created_tenant.business_name }}</strong> (<code>/i/{{ created_tenant.slug }}</code>) hesabı oluşturuldu!
          Durumu: <strong>{% if created_tenant.is_active %}AKTİF{% else %}ÖDEME ONAYI BEKLİYOR{% endif %}</strong>.
          Panel: <a href="{{ url_for('tenant_panel', slug=created_tenant.slug) }}" style="color:#fff;text-decoration:underline;">/i/{{ created_tenant.slug }}/panel</a>
        </div>
        {% endif %}

        {% if saas_error %}
        <div class="alert-err" style="margin-bottom: 18px;">{{ saas_error }}</div>
        {% endif %}

        <div class="saas-grid">
          <form class="saas-card" method="POST" action="{{ url_for('register_tenant') }}">
            <div>
              <h3 style="font-size: 1.15rem; margin-bottom: 4px;">Yeni İşletme Hesabı Aç</h3>
              <p style="color: var(--muted); font-size: 0.88rem;">Önce hesap açılır, IBAN ödemen admin tarafından onaylanınca sistem açılır.</p>
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
              <label for="module_type">Ana Kullanım Modülü</label>
              <select id="module_type" name="module_type">
                <option value="genel">Genel Talep / Müşteri Formu</option>
                <option value="kafe-randevu">Kafe &amp; Restoran Masa Randevu</option>
                <option value="berber-randevu">Berber &amp; Kuaför Saat Randevu</option>
                <option value="masa-qr">Masa QR Sipariş &amp; Garson Çağır</option>
              </select>
            </div>

            <div class="iban-box">
              <strong style="color: #fcd34d; font-size: 0.9rem;">IBAN Ödeme Bilgileri</strong>
              <span style="font-size: 0.84rem; color: #e5e7eb;">Alıcı: <strong>{{ iban_holder }}</strong> • Banka: {{ iban_bank }}</span>
              <div class="iban-code">{{ iban_number }}</div>
              <span style="font-size: 0.78rem; color: var(--muted);">Açıklamaya işletme adını yazarak ödeme yapabilirsin.</span>
            </div>

            <button type="submit" class="submit-btn">Hesabı Oluştur (Onaya Gönder)</button>
          </form>

          <form class="saas-card" method="POST" action="{{ url_for('tenant_quick_login') }}">
            <div>
              <h3 style="font-size: 1.15rem; margin-bottom: 4px;">İşletme Paneline Giriş</h3>
              <p style="color: var(--muted); font-size: 0.88rem;">Ödeme durumunu görmek veya aktif panelini yönetmek için giriş yap.</p>
            </div>

            <div>
              <label for="login_slug">İşletme Slug</label>
              <input id="login_slug" type="text" name="slug" placeholder="kolay-vitrin" required />
            </div>

            <div>
              <label for="login_password">Şifre</label>
              <input id="login_password" type="password" name="password" required />
            </div>

            <button type="submit" class="btn-secondary" style="justify-content: center; padding: 12px 16px;">İşletme Paneline Gir</button>

            <div class="iban-box">
              <strong style="color: var(--accent-bright); font-size: 0.88rem;">Örnek &amp; Yönetim Erişimleri</strong>
              <span style="font-size: 0.82rem; color: var(--muted);">Örnek aktif vitrin: <a href="{{ url_for('tenant_public', slug='kolay-vitrin') }}" style="color: var(--accent-bright);">/i/kolay-vitrin</a></span>
              <span style="font-size: 0.82rem; color: var(--muted);">Örnek aktif panel: <a href="{{ url_for('tenant_panel', slug='kolay-vitrin') }}" style="color: var(--accent-bright);">/i/kolay-vitrin/panel</a> (Şifre: <code>kolay1234</code>)</span>
              <span style="font-size: 0.82rem; color: var(--muted);">Süper Admin IBAN Onay: <a href="{{ url_for('superadmin_panel') }}" style="color: #fcd34d;">/admin</a></span>
            </div>
          </form>
        </div>
      </div>
    </section>
  </main>

  <footer>
    <div class="container" style="display: contents;">
      <span>© 2026 KOLAY Otomasyon Mikro-SaaS</span>
      <span>
        <a href="#anasayfa">Anasayfa</a> •
        <a href="{{ url_for('tenant_public', slug='kolay-vitrin') }}">Örnek Vitrin</a> •
        <a href="{{ url_for('tenant_panel', slug='kolay-vitrin') }}">Örnek Panel</a> •
        <a href="{{ url_for('superadmin_panel') }}">Admin Onay</a>
      </span>
    </div>
  </footer>

  <div id="serviceModal" class="modal-backdrop" onclick="if(event.target.id==='serviceModal')closeServiceModal()">
    <div class="modal-box">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span id="modalTag" class="card-tag" style="margin-bottom:0;">Modül</span>
        <button type="button" onclick="closeServiceModal()" style="background:none;border:1px solid rgba(255,255,255,0.2);color:#fff;width:32px;height:32px;border-radius:8px;cursor:pointer;">✕</button>
      </div>
      <img id="modalImg" src="" alt="" class="modal-img" onerror="this.style.display='none'" />
      <h3 id="modalTitle">Başlık</h3>
      <p id="modalDesc" style="color:#d1d5db;font-size:0.92rem;margin-top:8px;"></p>
      <ul id="modalFeatures" class="modal-list"></ul>
      <div style="display:flex;gap:10px;justify-content:flex-end;">
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
    body { background:#080d0b; color:#f8fafc; font-family:Inter,system-ui,sans-serif; padding:28px 18px; }
    .wrap { max-width:680px; margin:0 auto; display:grid; gap:18px; }
    .card { background:#121d18; border:1px solid rgba(245,158,11,0.35); border-radius:18px; padding:24px; display:grid; gap:14px; }
    .iban { font-family:monospace; font-size:1rem; font-weight:800; color:#fcd34d; background:#09100d; padding:10px 12px; border-radius:10px; border:1px solid rgba(245,158,11,0.3); }
    input { width:100%; padding:10px 12px; border-radius:10px; border:1px solid rgba(16,185,129,0.25); background:#0f1714; color:#f8fafc; }
    button, a.btn { text-decoration:none; padding:11px 16px; border-radius:10px; font-weight:800; font-size:0.9rem; border:none; cursor:pointer; display:inline-flex; align-items:center; justify-content:center; }
    .btn-gold { background:linear-gradient(135deg,#fbbf24,#f59e0b); color:#1f1300; }
    .btn-ghost { background:#0f1714; color:#34d399; border:1px solid rgba(16,185,129,0.3); }
    .ok { padding:12px; border-radius:10px; background:rgba(16,185,129,0.16); color:#a7f3d0; font-size:0.88rem; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div style="font-size:0.78rem;color:#fbbf24;font-weight:800;">HESAP DURUMU: ÖDEME ONAYI BEKLENİYOR</div>
      <h1 style="font-size:1.35rem;">{{ tenant.business_name }}</h1>
      <p style="color:#9ca3af;font-size:0.9rem;">
        Hesabın açıldı (<code>/i/{{ tenant.slug }}</code>). Sistemin aktif olarak çalışması için aşağıdaki IBAN'a ödemeyi yapıp
        bildirim gönderebilirsin; admin panelinden <strong>"Ödeme Alındı &amp; Onayla"</strong> yapıldığında hesabın açılır.
      </p>

      {% if notified %}
      <div class="ok">Ödeme bildirimin kaydedildi! Admin onayından sonra hesabın otomatik aktif olacak.</div>
      {% elif tenant.payment_requested %}
      <div class="ok">Ödeme bildiriminiz iletilmiş durumda ({{ tenant.payment_note or 'Not girilmedi' }}). Onay bekleniyor.</div>
      {% endif %}

      <div style="font-size:0.86rem;color:#e5e7eb;display:grid;gap:4px;">
        <div><strong>Alıcı:</strong> {{ iban_holder }}</div>
        <div><strong>Banka:</strong> {{ iban_bank }}</div>
        <div><strong>Paket:</strong> {{ tenant.plan|upper }} ({{ price_pro if tenant.plan == 'pro' else price_starter }})</div>
      </div>
      <div class="iban">{{ iban_number }}</div>

      <form method="POST" action="{{ url_for('notify_iban_payment', slug=tenant.slug) }}" style="display:grid;gap:10px;">
        <label style="font-size:0.84rem;color:#d1d5db;">Gönderen Adı / Dekont Notu</label>
        <input type="text" name="payment_note" value="{{ tenant.payment_note or '' }}" placeholder="Örn: Ahmet Yılmaz - FAST ile gönderildi" required />
        <button type="submit" class="btn-gold">Ödeme Yaptım / Onaya Bildir</button>
      </form>

      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <a class="btn btn-ghost" href="{{ url_for('index') }}">← Ana Sayfa</a>
        <a class="btn btn-ghost" href="https://wa.me/{{ wa_number }}?text={{ ('Merhaba, ' + tenant.business_name + ' (' + tenant.slug + ') icin IBAN odemesi yaptim, onay rica ederim.') | urlencode }}" target="_blank" rel="noopener noreferrer">WhatsApp'tan Yaz</a>
      </div>
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
  <title>{{ tenant.business_name }} — KOLAY Otomasyon</title>
  <style>
    body { background:#080d0b; color:#f8fafc; font-family:Inter,system-ui,sans-serif; padding:28px 18px 50px; }
    .wrap { max-width:920px; margin:0 auto; display:grid; gap:20px; }
    .top { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; border-bottom:1px solid rgba(16,185,129,0.22); padding-bottom:16px; }
    .btn { text-decoration:none; padding:9px 14px; border-radius:10px; font-weight:700; font-size:0.88rem; border:1px solid rgba(16,185,129,0.28); background:#121d18; color:#34d399; }
    .btn-main { background:linear-gradient(135deg,#34d399,#10b981); color:#04130d; border:none; }
    .card { background:#121d18; border:1px solid rgba(16,185,129,0.22); border-radius:16px; padding:22px; display:grid; gap:14px; }
    .row-2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    label { display:block; font-size:0.84rem; color:#d1d5db; margin-bottom:6px; font-weight:600; }
    input, select, textarea { width:100%; padding:10px 12px; border-radius:10px; border:1px solid rgba(16,185,129,0.22); background:#0f1714; color:#f8fafc; }
    .ok { padding:12px 14px; border-radius:10px; background:rgba(16,185,129,0.16); border:1px solid rgba(16,185,129,0.4); color:#a7f3d0; font-weight:600; }
    .badge { font-size:0.75rem; color:#34d399; background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.28); padding:4px 10px; border-radius:999px; font-weight:700; display:inline-block; margin-bottom:6px; }
    @media (max-width:720px) { .row-2 { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <div class="badge">MODÜL: {{ mod_label }} • /i/{{ tenant.slug }}</div>
        <h1 style="font-size:1.5rem;">{{ tenant.business_name }}</h1>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <a class="btn" href="{{ url_for('index') }}">← Ana Sayfa</a>
        <a class="btn btn-main" href="{{ url_for('tenant_panel', slug=tenant.slug) }}">İşletme Paneli</a>
      </div>
    </div>

    {% if sent %}
    <div class="ok">Kaydınız <strong>{{ tenant.business_name }}</strong> paneline başarıyla iletildi!</div>
    {% endif %}

    <form class="card" method="POST">
      <h2 style="font-size:1.14rem;">{{ form_title }}</h2>

      {% if tenant.module_type == 'kafe-randevu' %}
        <div class="row-2">
          <div><label>Ad Soyad</label><input type="text" name="name" placeholder="Adınız Soyadınız" required /></div>
          <div><label>Telefon</label><input type="text" name="phone" placeholder="05xx xxx xx xx" required /></div>
        </div>
        <div class="row-2">
          <div>
            <label>Kişi Sayısı</label>
            <select name="guest_count">
              <option value="2 Kişilik Masa">2 Kişilik Masa</option>
              <option value="4 Kişilik Masa">4 Kişilik Masa</option>
              <option value="6 Kişilik Masa">6 Kişilik Masa</option>
              <option value="8+ Kişilik Grup">8+ Kişilik Grup</option>
            </select>
          </div>
          <div><label>Tercih Edilen Saat / Tarih</label><input type="text" name="slot_time" placeholder="Örn: Bugün 20:30 veya Cuma 19:00" required /></div>
        </div>
        <div><label>Masa Tercihi / Özel Not</label><textarea name="message" rows="3" placeholder="Bahçe / cam kenarı veya özel notunuz..." required></textarea></div>

      {% elif tenant.module_type == 'berber-randevu' %}
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

      {% elif tenant.module_type == 'masa-qr' %}
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

      {% else %}
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
      {% endif %}

      <button type="submit" class="btn btn-main" style="cursor:pointer;">Gönder</button>
    </form>
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
    body { min-height:100vh; display:grid; place-items:center; background:#080d0b; color:#f8fafc; font-family:Inter,system-ui,sans-serif; padding:20px; }
    .box { width:100%; max-width:400px; background:#121d18; border:1px solid rgba(16,185,129,0.25); border-radius:18px; padding:24px; display:grid; gap:14px; }
    label { display:block; font-size:0.84rem; margin-bottom:6px; color:#d1d5db; }
    input { width:100%; padding:10px 12px; border-radius:10px; border:1px solid rgba(16,185,129,0.25); background:#0f1714; color:#f8fafc; }
    button { padding:11px; border-radius:10px; border:none; background:linear-gradient(135deg,#34d399,#10b981); color:#04130d; font-weight:800; cursor:pointer; }
    .err { padding:10px; border-radius:10px; background:rgba(239,68,68,0.16); color:#fca5a5; font-size:0.86rem; }
    a { color:#34d399; text-decoration:none; font-size:0.86rem; }
  </style>
</head>
<body>
  <form class="box" method="POST">
    <div>
      <h1 style="font-size:1.25rem;">{{ tenant.business_name }}</h1>
      <p style="color:#9ca3af;font-size:0.85rem;">İşletme paneli girişi (/i/{{ tenant.slug }}/panel)</p>
    </div>
    {% if error %}<div class="err">{{ error }}</div>{% endif %}
    <div><label>Şifre</label><input type="password" name="password" required /></div>
    <button type="submit">Giriş Yap</button>
    <a href="{{ url_for('tenant_public', slug=tenant.slug) }}">← İşletme Sayfasına Dön</a>
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
    body { background:var(--bg); color:var(--text); padding:24px 18px 48px; }
    .wrap { max-width:1080px; margin:0 auto; display:grid; gap:20px; }
    .top { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; border-bottom:1px solid var(--border); padding-bottom:16px; }
    .btn { text-decoration:none; padding:9px 14px; border-radius:10px; font-weight:700; font-size:0.86rem; border:1px solid var(--border); background:var(--card); color:var(--bright); cursor:pointer; display:inline-flex; align-items:center; gap:6px; }
    .btn-wa { background:rgba(34,197,94,0.16); border-color:rgba(34,197,94,0.45); color:#86efac; }
    .btn-del { background:rgba(239,68,68,0.14); border-color:rgba(239,68,68,0.35); color:#fca5a5; }
    .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; }
    .stat { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:14px 16px; }
    .stat span { font-size:0.78rem; color:var(--muted); display:block; }
    .stat strong { font-size:1.45rem; color:var(--bright); }
    .card { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:18px; display:grid; gap:12px; }
    .msg { background:var(--soft); padding:12px; border-radius:10px; font-size:0.92rem; }
    input, select { padding:8px 10px; border-radius:8px; border:1px solid var(--border); background:var(--soft); color:var(--text); }
    .row-3 { display:grid; grid-template-columns:1fr 1fr auto; gap:10px; align-items:end; }
    @media (max-width:760px) { .row-3 { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <h1>{{ tenant.business_name }} — Talep Paneli</h1>
        <p style="color:var(--muted);font-size:0.86rem;">Slug: <code>{{ tenant.slug }}</code> • Plan: <code>{{ tenant.plan|upper }}</code> • Durum: <strong style="color:var(--bright);">AKTİF</strong></p>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <a class="btn" href="{{ url_for('tenant_public', slug=tenant.slug) }}">Müşteri Linki</a>
        <form method="POST" action="{{ url_for('tenant_logout', slug=tenant.slug) }}"><button type="submit" class="btn btn-del">Çıkış</button></form>
      </div>
    </div>

    <form class="card" method="POST" action="{{ url_for('tenant_update_settings', slug=tenant.slug) }}">
      <div style="font-size:0.85rem;font-weight:800;color:var(--bright);">İŞLETME AYARLARI</div>
      <div class="row-3">
        <div>
          <label style="display:block;font-size:0.8rem;color:var(--muted);margin-bottom:4px;">WhatsApp Numarası</label>
          <input type="text" name="whatsapp_number" value="{{ tenant.whatsapp_number or '' }}" placeholder="05xx xxx xx xx" />
        </div>
        <div>
          <label style="display:block;font-size:0.8rem;color:var(--muted);margin-bottom:4px;">Aktif Modül</label>
          <select name="module_type">
            <option value="genel" {% if tenant.module_type=='genel' %}selected{% endif %}>Genel Talep</option>
            <option value="kafe-randevu" {% if tenant.module_type=='kafe-randevu' %}selected{% endif %}>Kafe Randevu</option>
            <option value="berber-randevu" {% if tenant.module_type=='berber-randevu' %}selected{% endif %}>Berber Randevu</option>
            <option value="masa-qr" {% if tenant.module_type=='masa-qr' %}selected{% endif %}>Masa QR</option>
          </select>
        </div>
        <button type="submit" class="btn">Ayarları Kaydet</button>
      </div>
    </form>

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
        <form method="POST" action="{{ url_for('tenant_update_ticket', slug=tenant.slug, ticket_id=t.id) }}" style="display:flex;gap:8px;align-items:center;">
          <select name="status">
            <option value="Yeni" {% if t.status=='Yeni' %}selected{% endif %}>Yeni</option>
            <option value="İnceleniyor" {% if t.status=='İnceleniyor' %}selected{% endif %}>İnceleniyor</option>
            <option value="Tamamlandı" {% if t.status=='Tamamlandı' %}selected{% endif %}>Tamamlandı</option>
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
    body { min-height:100vh; display:grid; place-items:center; background:#080d0b; color:#f8fafc; font-family:Inter,system-ui,sans-serif; padding:20px; }
    .box { width:100%; max-width:400px; background:#121d18; border:1px solid rgba(16,185,129,0.25); border-radius:18px; padding:24px; display:grid; gap:14px; }
    label { display:block; font-size:0.84rem; margin-bottom:6px; color:#d1d5db; }
    input { width:100%; padding:10px 12px; border-radius:10px; border:1px solid rgba(16,185,129,0.25); background:#0f1714; color:#f8fafc; }
    button { padding:11px; border-radius:10px; border:none; background:linear-gradient(135deg,#34d399,#10b981); color:#04130d; font-weight:800; cursor:pointer; }
  </style>
</head>
<body>
  <form class="box" method="POST">
    <h1 style="font-size:1.25rem;">Süper Admin Girişi</h1>
    {% if error %}<div style="color:#fca5a5;font-size:0.86rem;">{{ error }}</div>{% endif %}
    <div><label>Kullanıcı Adı</label><input type="text" name="username" required /></div>
    <div><label>Şifre</label><input type="password" name="password" required /></div>
    <button type="submit">Giriş Yap</button>
    <a href="{{ url_for('index') }}" style="color:#34d399;text-decoration:none;font-size:0.86rem;">← Ana Sayfa</a>
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
    body { background:var(--bg); color:var(--text); padding:24px 18px 48px; }
    .wrap { max-width:1140px; margin:0 auto; display:grid; gap:20px; }
    .top { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; border-bottom:1px solid var(--border); padding-bottom:16px; }
    .btn { text-decoration:none; padding:8px 13px; border-radius:9px; font-weight:700; font-size:0.84rem; border:1px solid var(--border); background:var(--card); color:var(--bright); cursor:pointer; }
    .btn-approve { background:linear-gradient(135deg,#34d399,#10b981); color:#04130d; border:none; font-weight:800; }
    .btn-suspend { background:rgba(239,68,68,0.15); border-color:rgba(239,68,68,0.4); color:#fca5a5; }
    .card { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:18px; display:grid; gap:10px; }
    .card.pending { border-color:rgba(245,158,11,0.48); }
    .badge-on { padding:3px 9px; border-radius:999px; font-size:0.75rem; font-weight:800; background:rgba(16,185,129,0.16); color:#6ee7b7; }
    .badge-off { padding:3px 9px; border-radius:999px; font-size:0.75rem; font-weight:800; background:rgba(245,158,11,0.18); color:#fcd34d; }
    select { padding:7px 10px; border-radius:8px; border:1px solid var(--border); background:var(--soft); color:var(--text); }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <h1>Süper Admin — IBAN Ödeme Onayı</h1>
        <p style="color:var(--muted);font-size:0.86rem;">Toplam {{ tenants|length }} işletme • IBAN: <code>{{ iban_number }}</code></p>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <a class="btn" href="{{ url_for('index') }}">← Vitrin</a>
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
            {{ tn.owner_email }} • Paket: <strong>{{ tn.plan|upper }}</strong> • Modül: <code>{{ tn.module_type }}</code> • Talep: {{ tn.ticket_count }}
            {% if tn.payment_note %} • Not: <span style="color:#fcd34d;">{{ tn.payment_note }}</span>{% endif %}
          </div>
        </div>

        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <a class="btn" href="{{ url_for('tenant_public', slug=tn.slug) }}">Vitrin</a>
          <a class="btn" href="{{ url_for('tenant_panel', slug=tn.slug) }}">Panel</a>

          {% if not tn.is_active %}
          <form method="POST" action="{{ url_for('superadmin_approve_tenant', tenant_id=tn.id) }}">
            <button type="submit" class="btn btn-approve">Ödeme Alındı &amp; Onayla</button>
          </form>
          {% else %}
          <form method="POST" action="{{ url_for('superadmin_suspend_tenant', tenant_id=tn.id) }}">
            <button type="submit" class="btn btn-suspend">Askıya Al</button>
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
    module_type = request.form.get("module_type", "genel").strip()

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

    if not tenant["is_active"]:
        notified = request.args.get("notified") == "1"
        return render_template_string(
            TENANT_PENDING_HTML,
            tenant=tenant,
            notified=notified,
            iban_holder=IBAN_HOLDER,
            iban_bank=IBAN_BANK,
            iban_number=IBAN_NUMBER,
            price_starter=PLAN_PRICE_STARTER,
            price_pro=PLAN_PRICE_PRO,
            wa_number=WHATSAPP_NUMBER,
        )

    mod_type = tenant.get("module_type") or "genel"
    mod_meta = {
        "kafe-randevu": ("Kafe & Restoran Masa Randevu", "Masa Rezervasyon Talebi"),
        "berber-randevu": ("Berber & Kuaför Saat Randevu", "Randevu Talebi Oluştur"),
        "masa-qr": ("Masa QR Sipariş & Garson Çağır", "Masa İsteği Gönder"),
        "genel": ("Genel Talep Formu", "Talep / Randevu / Sipariş Bırak"),
    }
    mod_label, form_title = mod_meta.get(mod_type, mod_meta["genel"])

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        raw_service = request.form.get("service", "").strip()
        slot_time = request.form.get("slot_time", "").strip()
        guest_count = request.form.get("guest_count", "").strip()
        raw_message = request.form.get("message", "").strip()

        if mod_type == "kafe-randevu":
            service = f"Masa Randevu ({guest_count or 'Masa'})"
            parts = []
            if guest_count:
                parts.append(f"Kişi: {guest_count}")
            if slot_time:
                parts.append(f"Saat: {slot_time}")
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
        return redirect(url_for("tenant_public", slug=slug, sent="1"))

    sent = request.args.get("sent") == "1"
    return render_template_string(
        TENANT_PUBLIC_HTML,
        tenant=tenant,
        services=SERVICES_DATA,
        mod_label=mod_label,
        form_title=form_title,
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
    if not tenant["is_active"]:
        notified = request.args.get("notified") == "1"
        return render_template_string(
            TENANT_PENDING_HTML,
            tenant=tenant,
            notified=notified,
            iban_holder=IBAN_HOLDER,
            iban_bank=IBAN_BANK,
            iban_number=IBAN_NUMBER,
            price_starter=PLAN_PRICE_STARTER,
            price_pro=PLAN_PRICE_PRO,
            wa_number=WHATSAPP_NUMBER,
        )

    tickets = load_tickets(tenant["id"])
    yeni_count = sum(1 for t in tickets if (t.get("status") or "Yeni") == "Yeni")
    tamam_count = sum(1 for t in tickets if t.get("status") == "Tamamlandı")
    return render_template_string(
        TENANT_PANEL_HTML,
        tenant=tenant,
        tickets=tickets,
        yeni_count=yeni_count,
        tamam_count=tamam_count,
    )


@app.route("/i/<slug>/panel/settings", methods=["POST"])
@tenant_login_required
def tenant_update_settings(slug):
    tenant = get_tenant_by_slug(slug)
    wa_num = request.form.get("whatsapp_number", "").strip()
    mod = request.form.get("module_type", "genel").strip()
    if mod not in {"genel", "kafe-randevu", "berber-randevu", "masa-qr"}:
        mod = "genel"
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tenants SET whatsapp_number = %s, module_type = %s WHERE id = %s",
                (wa_num, mod, tenant["id"]),
            )
    return redirect(url_for("tenant_panel", slug=slug))


@app.route("/i/<slug>/panel/update/<ticket_id>", methods=["POST"])
@tenant_login_required
def tenant_update_ticket(slug, ticket_id):
    tenant = get_tenant_by_slug(slug)
    new_status = request.form.get("status", "Yeni").strip()
    if new_status not in {"Yeni", "İnceleniyor", "Tamamlandı"}:
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
