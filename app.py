import functools
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

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

DEFAULT_DATABASE_URL = (
    "postgresql://postgres:kolayvitrinsaas@db.wpthfxzdhwinkamyrpyo.supabase.co:5432/postgres"
)
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL).strip()

SUPERADMIN_USERNAME = os.environ.get("SUPERADMIN_USERNAME", "rootadmin")
SUPERADMIN_PASSWORD = os.environ.get("SUPERADMIN_PASSWORD", "adminroot")
WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "905418007395")

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


def get_db():
    parsed = urlparse(DATABASE_URL)
    sslmode = "require" if "supabase.co" in (parsed.hostname or "") or "pooler.supabase.com" in (parsed.hostname or "") else "prefer"
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
                        plan TEXT NOT NULL DEFAULT 'free',
                        whatsapp_number TEXT DEFAULT '',
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW()
                    );
                    """
                )
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
                        INSERT INTO tenants (slug, business_name, owner_email, password_hash, plan, whatsapp_number, is_active)
                        VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                        RETURNING id
                        """,
                        (
                            "kolay-vitrin",
                            "KOLAY Otomasyon Ana Vitrin",
                            "iletisim@kolayotomasyon.local",
                            generate_password_hash("kolay1234"),
                            "pro",
                            WHATSAPP_NUMBER,
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
                ORDER BY t.id DESC
                """
            )
            return cur.fetchall()


def create_tenant(business_name, owner_email, password, raw_slug="", plan="free", whatsapp_number=""):
    base_slug = slugify(raw_slug or business_name)
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
                INSERT INTO tenants (slug, business_name, owner_email, password_hash, plan, whatsapp_number, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                RETURNING *
                """,
                (
                    candidate,
                    business_name.strip(),
                    owner_email.strip().lower(),
                    generate_password_hash(password),
                    plan if plan in {"free", "pro"} else "free",
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
            return cur.fetchall()


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
      --bg: #080d0b;
      --bg-soft: #0f1714;
      --card: rgba(17, 27, 23, 0.9);
      --card-hover: rgba(23, 37, 31, 0.97);
      --text: #f8fafc;
      --muted: #9ca3af;
      --accent: #10b981;
      --accent-bright: #34d399;
      --accent-2: #f59e0b;
      --border: rgba(16, 185, 129, 0.2);
      --glow: rgba(16, 185, 129, 0.18);
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: "Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    html { scroll-behavior: smooth; }

    body {
      background:
        radial-gradient(circle at 12% 8%, rgba(16, 185, 129, 0.15), transparent 36%),
        radial-gradient(circle at 88% 16%, rgba(245, 158, 11, 0.11), transparent 38%),
        var(--bg);
      color: var(--text);
      line-height: 1.6;
      overflow-x: hidden;
    }

    .container { max-width: 1180px; margin: 0 auto; padding: 0 22px; }
    .wp-icon { width: 18px; height: 18px; flex-shrink: 0; display: inline-block; }

    .navbar {
      position: sticky; top: 0; z-index: 40;
      backdrop-filter: blur(14px);
      background: rgba(8, 13, 11, 0.84);
      border-bottom: 1px solid var(--border);
    }

    .nav-inner {
      display: flex; align-items: center; justify-content: space-between;
      min-height: 72px; padding: 10px 0; gap: 16px; flex-wrap: wrap;
    }

    .brand {
      display: inline-flex; align-items: center; gap: 11px;
      font-weight: 800; font-size: 1.04rem; color: var(--text); text-decoration: none;
    }

    .brand-logo-img { height: 40px; width: auto; max-width: 58px; object-fit: contain; border-radius: 10px; display: block; }
    .brand-badge {
      width: 32px; height: 32px; border-radius: 10px; display: grid; place-items: center;
      font-weight: 900; font-size: 0.95rem; color: #04130d;
      background: linear-gradient(135deg, var(--accent-bright), var(--accent-2));
    }
    .brand-text small { display: block; font-size: 0.72rem; font-weight: 600; color: var(--accent-bright); }

    .nav-links { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .nav-btn {
      color: var(--muted); text-decoration: none; font-size: 0.9rem; font-weight: 600;
      padding: 8px 14px; border-radius: 10px; border: 1px solid transparent;
      transition: all 0.2s ease; display: inline-flex; align-items: center; gap: 6px;
    }
    .nav-btn:hover, .nav-btn.active {
      color: var(--text); background: rgba(16, 185, 129, 0.12); border-color: rgba(16, 185, 129, 0.32);
    }
    .nav-cta { color: #04130d; background: linear-gradient(135deg, var(--accent-bright), var(--accent)); font-weight: 800; }
    .nav-wa { color: #dcfce7; background: rgba(34, 197, 94, 0.16); border: 1px solid rgba(34, 197, 94, 0.42); font-weight: 700; }

    .reveal { opacity: 0; transform: translateY(18px); transition: opacity 0.6s ease, transform 0.6s ease; }
    .reveal.visible { opacity: 1; transform: translateY(0); }

    .hero { padding: 62px 0 42px; display: grid; grid-template-columns: 1.25fr 0.75fr; gap: 28px; align-items: center; }
    .badge {
      display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: 999px;
      font-size: 0.82rem; font-weight: 700; color: var(--accent-bright);
      background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.28); margin-bottom: 16px;
    }
    .hero h1 { font-size: clamp(2rem, 4.2vw, 3.15rem); line-height: 1.14; margin-bottom: 16px; }
    .hero h1 span { background: linear-gradient(135deg, var(--accent-bright), var(--accent-2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .hero p { color: var(--muted); font-size: 1.02rem; max-width: 630px; margin-bottom: 24px; }
    .hero-actions { display: flex; gap: 12px; flex-wrap: wrap; }

    .btn-primary, .btn-secondary, .btn-wa, .btn-sm, .btn-amber-sm {
      text-decoration: none; padding: 11px 18px; border-radius: 11px; font-weight: 700; font-size: 0.9rem;
      transition: transform 0.2s ease, box-shadow 0.2s ease; display: inline-flex; align-items: center; gap: 8px; cursor: pointer;
    }
    .btn-primary { background: linear-gradient(135deg, var(--accent-bright), var(--accent)); color: #04130d; border: none; }
    .btn-secondary { background: var(--card); color: var(--text); border: 1px solid var(--border); }
    .btn-wa { background: linear-gradient(135deg, #22c55e, #16a34a); color: #052e16; border: none; }
    .btn-sm { padding: 8px 12px; font-size: 0.8rem; border-radius: 9px; background: rgba(16, 185, 129, 0.14); color: var(--accent-bright); border: 1px solid rgba(16, 185, 129, 0.35); }
    .btn-amber-sm { padding: 8px 12px; font-size: 0.8rem; border-radius: 9px; background: rgba(245, 158, 11, 0.15); color: #fcd34d; border: 1px solid rgba(245, 158, 11, 0.38); font-weight: 700; }

    .hero-panel {
      background: linear-gradient(160deg, rgba(19, 32, 27, 0.94), rgba(10, 17, 14, 0.94));
      border: 1px solid var(--border); border-radius: 20px; padding: 22px;
    }
    .panel-title { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-2); margin-bottom: 12px; font-weight: 800; }
    .mini-list { list-style: none; display: grid; gap: 10px; }
    .mini-list li {
      display: flex; justify-content: space-between; align-items: center; padding: 10px 13px; border-radius: 12px;
      background: rgba(8, 13, 11, 0.65); border: 1px solid rgba(16, 185, 129, 0.14); font-size: 0.9rem; gap: 8px;
    }

    .pill { font-size: 0.73rem; padding: 3px 9px; border-radius: 999px; background: rgba(16, 185, 129, 0.16); color: var(--accent-bright); font-weight: 700; border: 1px solid rgba(16, 185, 129, 0.3); }
    .pill-amber { font-size: 0.73rem; padding: 3px 9px; border-radius: 999px; background: rgba(245, 158, 11, 0.16); color: #fcd34d; font-weight: 700; border: 1px solid rgba(245, 158, 11, 0.36); }
    .pill-blue { font-size: 0.73rem; padding: 3px 9px; border-radius: 999px; background: rgba(56, 189, 248, 0.15); color: #7dd3fc; font-weight: 700; border: 1px solid rgba(56, 189, 248, 0.34); }

    section.block { padding: 54px 0; }
    .section-head { margin-bottom: 22px; }
    .section-head span { color: var(--accent-2); font-size: 0.82rem; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; }
    .section-head h2 { font-size: clamp(1.55rem, 3vw, 2.2rem); margin-top: 6px; margin-bottom: 8px; }
    .section-head p { color: var(--muted); max-width: 760px; }

    .demo-tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
    .demo-tab {
      background: var(--card); color: var(--muted); border: 1px solid var(--border);
      padding: 9px 14px; border-radius: 11px; font-size: 0.86rem; font-weight: 700; cursor: pointer;
    }
    .demo-tab.active { color: #04130d; background: linear-gradient(135deg, var(--accent-bright), var(--accent)); border-color: transparent; }

    .sim-frame { background: #0c1411; border: 1px solid rgba(16, 185, 129, 0.28); border-radius: 18px; overflow: hidden; }
    .sim-topbar { background: #070c0a; border-bottom: 1px solid rgba(16, 185, 129, 0.16); padding: 10px 16px; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
    .sim-dots { display: inline-flex; gap: 6px; align-items: center; }
    .sim-dot { width: 10px; height: 10px; border-radius: 50%; }
    .sim-header-strip { background: #0d1613; border-bottom: 1px solid rgba(16, 185, 129, 0.16); padding: 14px 18px; display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
    .sim-title-group { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .sim-subpill { font-size: 0.76rem; font-weight: 700; color: var(--accent-bright); background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.28); padding: 3px 10px; border-radius: 8px; }
    .sim-kpi-row { display: flex; gap: 10px; flex-wrap: wrap; }
    .sim-kpi { background: #080e0c; border: 1px solid rgba(16, 185, 129, 0.16); border-radius: 10px; padding: 7px 12px; min-width: 116px; }
    .sim-kpi span { display: block; font-size: 0.7rem; color: var(--muted); }
    .sim-kpi strong { font-size: 0.92rem; }
    .sim-kpi.ok strong { color: var(--accent-bright); }
    .sim-kpi.warn strong { color: #fbbf24; }

    .sim-grid { padding: 18px; display: grid; grid-template-columns: 0.96fr 1.14fr; gap: 18px; align-items: start; }
    .sim-card { background: #0e1814; border: 1px solid rgba(16, 185, 129, 0.18); border-radius: 14px; padding: 16px; display: grid; gap: 14px; }
    .sim-card-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; padding-bottom: 10px; border-bottom: 1px solid rgba(16, 185, 129, 0.12); }
    .sim-card-head h3 { font-size: 0.84rem; letter-spacing: 0.04em; text-transform: uppercase; color: #d1fae5; }
    .sim-highlight { background: linear-gradient(145deg, rgba(16, 185, 129, 0.12), rgba(8, 14, 12, 0.92)); border: 1px solid rgba(16, 185, 129, 0.34); border-radius: 13px; padding: 14px; display: grid; gap: 10px; }
    .sim-bar { width: 100%; height: 8px; border-radius: 999px; background: rgba(255, 255, 255, 0.08); overflow: hidden; }
    .sim-bar-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--accent), var(--accent-bright)); }
    .sim-3col { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .sim-mini-box { background: #080e0c; border: 1px solid rgba(16, 185, 129, 0.14); border-radius: 10px; padding: 9px 10px; }
    .sim-mini-box small { display: block; font-size: 0.71rem; color: var(--muted); }
    .sim-filters { display: flex; gap: 7px; flex-wrap: wrap; align-items: center; }
    .sim-chip { padding: 5px 11px; border-radius: 999px; font-size: 0.76rem; font-weight: 700; background: #080e0c; color: var(--muted); border: 1px solid rgba(16, 185, 129, 0.18); cursor: pointer; }
    .sim-chip.active { background: rgba(16, 185, 129, 0.18); color: var(--accent-bright); border-color: rgba(16, 185, 129, 0.45); }
    .sim-rows { display: grid; gap: 8px; }
    .sim-row { background: #09100d; border: 1px solid rgba(16, 185, 129, 0.14); border-radius: 11px; padding: 11px 13px; display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
    .sim-row strong { display: block; font-size: 0.87rem; }
    .sim-row small { color: var(--muted); font-size: 0.77rem; }
    .table-grid, .slot-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .table-chip { padding: 10px; border-radius: 10px; border: 1px solid rgba(16, 185, 129, 0.2); background: #09100d; cursor: pointer; text-align: left; }
    .table-chip strong { display: block; font-size: 0.84rem; color: var(--text); }
    .table-chip span { font-size: 0.73rem; color: var(--muted); }
    .table-chip.free { border-color: rgba(16, 185, 129, 0.45); background: rgba(16, 185, 129, 0.11); }
    .table-chip.busy { border-color: rgba(245, 158, 11, 0.48); background: rgba(245, 158, 11, 0.12); }
    .slot-btn { padding: 9px; border-radius: 9px; border: 1px solid rgba(16, 185, 129, 0.25); background: #09100d; color: var(--text); font-size: 0.81rem; font-weight: 700; cursor: pointer; }
    .slot-btn.booked { background: rgba(239, 68, 68, 0.14); border-color: rgba(239, 68, 68, 0.36); color: #fca5a5; }
    .slot-btn.selected { background: rgba(16, 185, 129, 0.22); border-color: var(--accent-bright); color: #a7f3d0; }
    .sim-log { background: #060a08; border: 1px solid rgba(16, 185, 129, 0.16); border-radius: 10px; padding: 11px 12px; font-family: monospace; font-size: 0.77rem; color: #a7f3d0; max-height: 120px; overflow-y: auto; display: grid; gap: 4px; }
    .sim-footer { background: #080d0b; border-top: 1px solid rgba(16, 185, 129, 0.16); padding: 12px 18px; display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }

    .ref-shot-box { margin-top: 14px; background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 14px; display: none; }
    .ref-shot-box.open { display: block; }
    .ref-shot-box img { width: 100%; max-height: 360px; object-fit: contain; border-radius: 10px; background: #060a08; display: block; }

    .services-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 18px; }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 18px; overflow: hidden; display: flex; flex-direction: column; justify-content: space-between; cursor: pointer; transition: transform 0.22s ease, border-color 0.22s ease; }
    .card:hover { transform: translateY(-4px); border-color: rgba(16, 185, 129, 0.48); }
    .card-thumb { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; display: block; border-bottom: 1px solid rgba(16, 185, 129, 0.16); }
    .card-body { padding: 18px 20px 12px; }
    .card-tag { display: inline-block; font-size: 0.76rem; font-weight: 700; color: var(--accent-bright); background: rgba(16, 185, 129, 0.12); padding: 4px 10px; border-radius: 8px; margin-bottom: 8px; }
    .card h3 { font-size: 1.12rem; margin-bottom: 6px; }
    .card p { color: var(--muted); font-size: 0.92rem; }
    .card-footer { display: flex; align-items: center; justify-content: space-between; padding: 12px 20px 16px; border-top: 1px solid rgba(156, 163, 175, 0.12); }
    .detail-link { background: transparent; border: none; color: var(--accent-2); font-weight: 700; font-size: 0.9rem; cursor: pointer; }

    .saas-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; align-items: start; }
    .saas-card { background: var(--card); border: 1px solid var(--border); border-radius: 18px; padding: 24px; display: grid; gap: 14px; }
    .row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    label { display: block; font-size: 0.84rem; color: #d1d5db; margin-bottom: 6px; font-weight: 600; }
    input, select, textarea { width: 100%; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--border); background: var(--bg-soft); color: var(--text); font-size: 0.92rem; }
    .submit-btn { padding: 12px 18px; border-radius: 11px; border: none; cursor: pointer; font-weight: 800; font-size: 0.94rem; color: #04130d; background: linear-gradient(135deg, var(--accent-bright), var(--accent-2)); }
    .alert-ok { padding: 12px 14px; border-radius: 10px; background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); color: #a7f3d0; font-size: 0.9rem; font-weight: 600; }
    .alert-err { padding: 12px 14px; border-radius: 10px; background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); color: #fca5a5; font-size: 0.9rem; font-weight: 600; }

    .modal-backdrop { position: fixed; inset: 0; z-index: 90; background: rgba(4, 8, 6, 0.78); backdrop-filter: blur(8px); display: none; align-items: center; justify-content: center; padding: 20px; }
    .modal-backdrop.open { display: flex; }
    .modal-box { width: 100%; max-width: 600px; max-height: 90vh; overflow-y: auto; background: #101915; border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 22px; padding: 26px; }
    .modal-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 14px; }
    .modal-img { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 14px; margin-bottom: 16px; }
    .modal-close { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); color: var(--text); width: 34px; height: 34px; border-radius: 10px; cursor: pointer; }
    .modal-list { list-style: none; display: grid; gap: 8px; margin: 14px 0 20px; }
    .modal-list li { padding: 9px 12px; border-radius: 10px; background: rgba(8, 13, 11, 0.72); border: 1px solid rgba(16, 185, 129, 0.16); font-size: 0.9rem; }
    .modal-actions { display: flex; gap: 10px; justify-content: flex-end; flex-wrap: wrap; }

    footer { border-top: 1px solid var(--border); padding: 24px 0; margin-top: 28px; color: var(--muted); font-size: 0.88rem; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
    footer a { color: var(--muted); text-decoration: none; }

    @media (max-width: 920px) {
      .hero, .sim-grid, .saas-grid, .row-2, .sim-3col { grid-template-columns: 1fr; }
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
        <a href="#canli-demo" class="nav-btn">Canlı Demo</a>
        <a href="#hizmetler" class="nav-btn">Modüller</a>
        <a href="#saas-basla" class="nav-btn nav-cta">İşletme Aç</a>
        <a href="{{ url_for('superadmin_panel') }}" class="nav-btn">Admin</a>
        <a href="https://wa.me/{{ wa_number }}?text={{ 'Merhaba KOLAY Otomasyon, mikro-SaaS altyapiniz hakkinda bilgi almak istiyorum.' | urlencode }}" target="_blank" rel="noopener noreferrer" class="nav-btn nav-wa" aria-label="WhatsApp">
          <svg class="wp-icon"><use href="#icon-whatsapp"></use></svg>
          <span>WhatsApp</span>
        </a>
      </nav>
    </div>
  </header>

  <main>
    <section id="anasayfa" class="hero">
      <div class="container" style="display: contents;">
        <div class="reveal">
          <div class="badge">Supabase Çok Kiracılı Mikro-SaaS</div>
          <h1>İşletmen İçin <span>Kendi Alanın ve Panelinle</span> Hazır Sistemler</h1>
          <p>
            Kafe-restoran masa planı, berber-kuaför randevu, masa QR sipariş/garson çağır ve saha/web/kasa akışlarını
            her işletmeye özel sayfa ve izole panel ile saniyeler içinde ayağa kaldır.
          </p>
          <div class="hero-actions">
            <a href="#saas-basla" class="btn-primary">İşletme Sayfası Oluştur</a>
            <a href="#canli-demo" class="btn-secondary">Canlı Simülasyonu Dene</a>
            <a href="https://wa.me/{{ wa_number }}?text={{ 'Merhaba KOLAY Otomasyon, hizli teklif almak istiyorum.' | urlencode }}" target="_blank" rel="noopener noreferrer" class="btn-wa" aria-label="WhatsApp">
              <svg class="wp-icon"><use href="#icon-whatsapp"></use></svg>
              <span>WhatsApp</span>
            </a>
          </div>
        </div>

        <aside class="hero-panel reveal">
          <div class="panel-title">Örnek Aktif İşletme Alanı</div>
          <ul class="mini-list">
            <li><span>Vitrin / Talep Linki</span><span class="pill">/i/kolay-vitrin</span></li>
            <li><span>İşletme Yönetim Paneli</span><span class="pill">/i/kolay-vitrin/panel</span></li>
            <li><span>Veritabanı Altyapısı</span><span class="pill-amber">Supabase PostgreSQL</span></li>
            <li><span>Platform Yönetimi</span><span class="pill-blue">/admin</span></li>
          </ul>
        </aside>
      </div>
    </section>

    <section id="canli-demo" class="block">
      <div class="container">
        <div class="section-head reveal">
          <span>Birebir Sistem Simülasyonu</span>
          <h2>Kontrol Panellerini Canlı Kullan</h2>
          <p>Sekmeler arasında geçiş yaparak işletme senaryolarını, sayaçları ve sistem loglarını canlı test edebilirsin.</p>
        </div>

        <div class="demo-tabs reveal" role="tablist">
          <button type="button" class="demo-tab active" data-demo="mobil-otomasyon" onclick="switchDemo('mobil-otomasyon', this)">Mobil &amp; Saha</button>
          <button type="button" class="demo-tab" data-demo="web-otomasyon" onclick="switchDemo('web-otomasyon', this)">Web &amp; Botlar</button>
          <button type="button" class="demo-tab" data-demo="masaustu-otomasyon" onclick="switchDemo('masaustu-otomasyon', this)">Masaüstü &amp; Barkod</button>
          <button type="button" class="demo-tab" data-demo="kafe-restoran-randevu" onclick="switchDemo('kafe-restoran-randevu', this)">Kafe &amp; Restoran</button>
          <button type="button" class="demo-tab" data-demo="berber-kuafor-randevu" onclick="switchDemo('berber-kuafor-randevu', this)">Berber &amp; Kuaför</button>
          <button type="button" class="demo-tab" data-demo="masa-qr-garson" onclick="switchDemo('masa-qr-garson', this)">Masa QR &amp; Garson</button>
        </div>

        <div class="sim-frame reveal">
          <div class="sim-topbar">
            <div class="sim-dots">
              <span class="sim-dot" style="background: #ef4444;"></span>
              <span class="sim-dot" style="background: #f59e0b;"></span>
              <span class="sim-dot" style="background: #10b981;"></span>
              <span id="simWinLabel" style="font-size: 0.81rem; color: var(--muted); font-weight: 600; margin-left: 8px;">KOLAY Otomasyon</span>
            </div>
            <span class="pill">BİREBİR SİMÜLASYON</span>
          </div>

          <div id="simHeaderStrip" class="sim-header-strip"></div>
          <div id="simGrid" class="sim-grid"></div>

          <div class="sim-footer">
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
              <a href="#saas-basla" class="btn-primary">Bu Modülle İşletme Aç</a>
              <button type="button" class="btn-secondary" onclick="toggleRefShot()">Görsel Ekranını Göster / Gizle</button>
              <a id="demoWaLink" href="https://wa.me/{{ wa_number }}" target="_blank" rel="noopener noreferrer" class="btn-sm" aria-label="WhatsApp">
                <svg class="wp-icon"><use href="#icon-whatsapp"></use></svg>
                <span>WhatsApp</span>
              </a>
            </div>
            <span id="simFooterMeta" style="font-size: 0.8rem; color: var(--muted);">Hazır</span>
          </div>
        </div>

        <div id="refShotBox" class="ref-shot-box">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; gap: 10px; flex-wrap: wrap;">
            <strong id="refShotTitle" style="font-size: 0.9rem; color: var(--accent-bright);">Sistem Görseli</strong>
            <button type="button" class="btn-sm" onclick="toggleRefShot()">Kapat</button>
          </div>
          <img id="refShotImg" src="/images/mobilsaha.jpg" alt="Sistem Görseli" onerror="this.style.display='none'" />
        </div>
      </div>
    </section>

    <section id="hizmetler" class="block">
      <div class="container">
        <div class="section-head reveal">
          <span>Modüller</span>
          <h2>SaaS Paketlerine Dahil Sistemler</h2>
          <p>Her modüle tıklayarak detaylarını inceleyebilirsin.</p>
        </div>

        <div class="services-grid">
          {% for srv in services %}
          <article class="card reveal" onclick="openServiceModal('{{ srv.id }}')">
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
        <div class="section-head reveal">
          <span>Mikro-SaaS Başlangıç</span>
          <h2>Yeni İşletme Alanı Aç veya Panelinle Devam Et</h2>
          <p>Yeni bir işletme oluşturduğunda Supabase üzerinde sana özel <code>/i/slug</code> vitrin sayfası ve <code>/i/slug/panel</code> yönetim ekranı açılır.</p>
        </div>

        {% if created_tenant %}
        <div class="alert-ok" style="margin-bottom: 18px;">
          <strong>{{ created_tenant.business_name }}</strong> oluşturuldu!
          Vitrin: <a href="{{ url_for('tenant_public', slug=created_tenant.slug) }}" style="color:#fff;text-decoration:underline;">/i/{{ created_tenant.slug }}</a> •
          Panel: <a href="{{ url_for('tenant_panel', slug=created_tenant.slug) }}" style="color:#fff;text-decoration:underline;">/i/{{ created_tenant.slug }}/panel</a>
        </div>
        {% endif %}

        {% if saas_error %}
        <div class="alert-err" style="margin-bottom: 18px;">{{ saas_error }}</div>
        {% endif %}

        <div class="saas-grid">
          <form class="saas-card reveal" method="POST" action="{{ url_for('register_tenant') }}">
            <div>
              <h3 style="font-size: 1.15rem; margin-bottom: 4px;">Yeni İşletme Kaydı</h3>
              <p style="color: var(--muted); font-size: 0.88rem;">Kendi slug adresin ve işletme panel şifrenle anında başla.</p>
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
                <label for="password">Panel Şifresi</label>
                <input id="password" type="password" name="password" placeholder="En az 6 karakter" required />
              </div>
            </div>

            <div>
              <label for="plan">Başlangıç Planı</label>
              <select id="plan" name="plan">
                <option value="free">Free (Başlangıç)</option>
                <option value="pro">Pro (Tam Modül)</option>
              </select>
            </div>

            <button type="submit" class="submit-btn">İşletme Alanımı Oluştur</button>
          </form>

          <form class="saas-card reveal" method="POST" action="{{ url_for('tenant_quick_login') }}">
            <div>
              <h3 style="font-size: 1.15rem; margin-bottom: 4px;">Mevcut İşletme Paneline Giriş</h3>
              <p style="color: var(--muted); font-size: 0.88rem;">Kayıtlı işletme slug'ı ve şifrenle doğrudan kendi talep paneline git.</p>
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

            <div style="font-size: 0.82rem; color: var(--muted); border-top: 1px solid var(--border); padding-top: 12px;">
              Demo alan: <code>kolay-vitrin</code> • Şifre: <code>kolay1234</code> • Süper Admin: <a href="{{ url_for('superadmin_panel') }}" style="color: var(--accent-bright);">/admin</a>
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
        <a href="{{ url_for('tenant_panel', slug='kolay-vitrin') }}">Örnek İşletme Paneli</a> •
        <a href="{{ url_for('superadmin_panel') }}">Süper Admin</a>
      </span>
    </div>
  </footer>

  <div id="serviceModal" class="modal-backdrop" onclick="if(event.target.id==='serviceModal')closeServiceModal()">
    <div class="modal-box">
      <div class="modal-top">
        <span id="modalTag" class="card-tag" style="margin-bottom: 0;">Modül</span>
        <button type="button" class="modal-close" onclick="closeServiceModal()">✕</button>
      </div>
      <img id="modalImg" src="" alt="" class="modal-img" onerror="this.style.display='none'" />
      <h3 id="modalTitle">Başlık</h3>
      <p id="modalDesc" style="color:#d1d5db;font-size:0.94rem;margin-top:8px;"></p>
      <ul id="modalFeatures" class="modal-list"></ul>
      <div class="modal-actions">
        <button type="button" class="btn-secondary" onclick="closeServiceModal()">Kapat</button>
        <a href="#saas-basla" class="btn-primary" onclick="closeServiceModal()">İşletme Alanı Aç</a>
      </div>
    </div>
  </div>

  <script>
    const SERVICES = {{ services | tojson }};
    const WA_NUMBER = "{{ wa_number }}";
    let currentDemoId = "mobil-otomasyon";

    const sim = {
      mobil: {
        courier: "Kurye #04 • Ahmet Demir", status: "Teslimat Yolunda", eta: "8 dk", done: 14, total: 20,
        activeStaff: 18, totalStaff: 24, gpsPct: 98.6, filterActive: false,
        tasks: [
          { title: "Sipariş #8690123004567 — Kadıköy Dağıtım", sub: "12.5 km • Kurye #04", badge: "YOLDA", cls: "pill", active: true },
          { title: "Sipariş #8690123007896 — Üsküdar Teslimatı", sub: "3.2 km • Kurye #02", badge: "TESLİM EDİLDİ", cls: "pill", active: false },
          { title: "Sipariş #8690123001234 — Beşiktaş Acil Servis", sub: "6.8 km • Kurye #07", badge: "GECİKME", cls: "pill-amber", active: true },
        ],
        logs: ["[14:14:02] [GPS] Kadıköy rotası güncellendi", "[14:14:15] [PUSH] Tahmini varış 8 dk bildirimi gönderildi"]
      },
      web: {
        botTitle: "BOT #02 • Form Kaydı -> Telegram & WhatsApp", botSub: "Anlık Tetikleme • Webhook • Mesaj Botu",
        successRate: 99.6, leads: 4128, sent: 18450, queue: 14, onlyCrit: false,
        flows: [
          { title: "WhatsApp Otomatik Karşılama Botu", sub: "850 Mesaj/dk • 0.4s", badge: "BAŞARILI", cls: "pill", crit: false },
          { title: "Telegram Form Bildirim Botu", sub: "1,426 Bildirim • 0.2s", badge: "AKTİF", cls: "pill", crit: false },
          { title: "Webhook Kuyruğu — Sipariş", sub: "3 İstek Bekliyor", badge: "KRİTİK", cls: "pill-amber", crit: true },
        ],
        logs: ["[21:15:01] [WEBHOOK] Yeni form kaydı alındı", "[21:15:03] [TELEGRAM] 200 OK yanıt döndü"]
      },
      masaustu: {
        barcode: "8690504012345", product: "Çaykur Rize Turist Çay 500g", sales: 1428, stockCount: 24850, critCount: 2,
        cartItems: 2, cartTotal: 130.0, onlyCrit: false,
        items: [
          { title: "Çaykur Rize Turist Çay 500g", sub: "Stok: 85 Adet • 85.00 TL", badge: "STOKTA", cls: "pill", crit: false },
          { title: "Eker Yoğurt 1kg", sub: "Stok: 3 Adet • 45.00 TL", badge: "KRİTİK", cls: "pill-amber", crit: true },
          { title: "Sırma Su 1.5L", sub: "Stok: 0 Adet • 7.50 TL", badge: "STOKTA YOK", cls: "pill-amber", crit: true },
        ],
        logs: ["[12:42:01] [BARCODE] Okuyucu hazır", "[12:42:08] [POS] Yerel senkronizasyon aktif"]
      },
      kafe: {
        guests: 4, time: "19:30", guestName: "Murat Yılmaz", pending: 4, onlyFree: false,
        tables: [
          { name: "Masa 01", cap: 4, busy: true, info: "18:30 - 20:30 • Ahmet B." },
          { name: "Masa 02", cap: 2, busy: false, info: "Müsait (2 Kişilik)" },
          { name: "Masa 03", cap: 6, busy: true, info: "20:00 • Murat Y." },
          { name: "Masa 04", cap: 4, busy: true, info: "19:30 - 21:30 • Caner S." },
          { name: "Masa 05", cap: 2, busy: false, info: "Müsait (2 Kişilik)" },
          { name: "Masa 06", cap: 8, busy: false, info: "Müsait (8 Kişilik)" },
        ],
        logs: ["[18:45:02] [REZERVASYON] Masa planı senkronize", "[18:45:19] [ONAY] Saat ve kişi kontrolü aktif"]
      },
      berber: {
        client: "Murat Demir", service: "Saç Kesim & Sakal (45 dk)", chair: "Koltuk 1 • Berber Serkan",
        elapsed: 35, totalMin: 45, selectedSlot: 1,
        slots: [
          { time: "13:00", booked: true, info: "Dolu" },
          { time: "13:45", booked: false, info: "Müsait" },
          { time: "14:30", booked: false, info: "Müsait" },
          { time: "15:15", booked: true, info: "Dolu" },
          { time: "16:00", booked: false, info: "Müsait" },
          { time: "16:45", booked: false, info: "Müsait" },
        ],
        logs: ["[13:40:12] [ZAMAN] Koltuk 1 sayacı 35/45 dk", "[13:41:20] [ÇAKIŞMA] Çifte randevu koruması aktif"]
      },
      qr: {
        table: "Masa 05", ordersCount: 64, callsCount: 18, billsCount: 11,
        feed: [
          { title: "Masa 05 — 2x Türk Kahvesi", sub: "QR Menü Siparişi", badge: "SERVİS HAZIR", cls: "pill" },
          { title: "Masa 08 — Garson Çağrı Talebi", sub: "Bölüm: Teras", badge: "GARSON BEKLİYOR", cls: "pill-amber" },
          { title: "Masa 12 — Hesap İsteme Talebi", sub: "Masa QR", badge: "HESAP HAZIRLANIYOR", cls: "pill-blue" },
        ],
        logs: ["[20:10:05] [QR-SCAN] Masa 05 oturumu açıldı", "[20:10:18] [GARSON] Anlık çağrı kanalı aktif"]
      }
    };

    function nowStr() {
      const d = new Date();
      return `[${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}:${String(d.getSeconds()).padStart(2,"0")}]`;
    }
    function pushSimLog(key, line) {
      sim[key].logs.unshift(`${nowStr()} ${line}`);
      sim[key].logs = sim[key].logs.slice(0, 5);
    }
    function renderSimLog(key) {
      return `<div><div style="font-size:0.73rem;font-weight:800;color:var(--muted);margin-bottom:6px;">CANLI LOG</div><div class="sim-log">${sim[key].logs.map(x => `<div>${x}</div>`).join("")}</div></div>`;
    }

    function switchDemo(demoId, btnEl) {
      currentDemoId = demoId;
      document.querySelectorAll(".demo-tab").forEach(b => b.classList.remove("active"));
      if (btnEl) btnEl.classList.add("active");
      const srv = SERVICES.find(s => s.id === demoId) || SERVICES[0];
      document.getElementById("simWinLabel").textContent = `${srv.tag} — ${srv.title}`;
      document.getElementById("refShotTitle").textContent = `${srv.tag} — ${srv.title}`;
      const img = document.getElementById("refShotImg");
      if (img && srv.image) { img.style.display = "block"; img.src = `/images/${srv.image}`; }
      document.getElementById("demoWaLink").href = `https://wa.me/${WA_NUMBER}?text=${encodeURIComponent("Merhaba KOLAY Otomasyon, " + srv.tag + " modulu hakkinda bilgi almak istiyorum.")}`;
      renderSim();
    }

    function toggleRefShot() { document.getElementById("refShotBox").classList.toggle("open"); }

    function renderSim() {
      const head = document.getElementById("simHeaderStrip");
      const grid = document.getElementById("simGrid");
      const footer = document.getElementById("simFooterMeta");
      if (!head || !grid) return;

      if (currentDemoId === "mobil-otomasyon") {
        const m = sim.mobil;
        const pct = Math.min(100, Math.round((m.done / m.total) * 100));
        const rows = m.filterActive ? m.tasks.filter(t => t.active) : m.tasks;
        head.innerHTML = `<div class="sim-title-group"><strong>Mobil &amp; Saha</strong><span class="sim-subpill">SAHA KONTROL</span></div><div class="sim-kpi-row"><div class="sim-kpi ok"><span>Saha Ekibi</span><strong>${m.activeStaff}/${m.totalStaff}</strong></div><div class="sim-kpi"><span>Görev</span><strong>${m.done}/${m.total}</strong></div><div class="sim-kpi warn"><span>ETA</span><strong>${m.eta}</strong></div><div class="sim-kpi ok"><span>GPS</span><strong>%${m.gpsPct}</strong></div></div>`;
        grid.innerHTML = `<div class="sim-card"><div class="sim-card-head"><h3>01 • Rota</h3><span class="pill">${m.status}</span></div><div class="sim-highlight"><strong>${m.courier}</strong><div style="font-size:0.8rem;color:var(--muted);">${m.status} • ${m.eta}</div><div class="sim-bar"><div class="sim-bar-fill" style="width:${pct}%;"></div></div></div><div class="sim-filters"><button type="button" class="btn-sm" onclick="sim.mobil.eta='12 dk';pushSimLog('mobil','Yola cikildi');renderSim()">Yola Çıktı</button><button type="button" class="btn-amber-sm" onclick="if(sim.mobil.done<sim.mobil.total)sim.mobil.done++;pushSimLog('mobil','Teslimat tamamlandi');renderSim()">Teslimat Tamamla</button><button type="button" class="btn-amber-sm" onclick="sim.mobil.eta='16 dk';pushSimLog('mobil','Gecikme senaryosu tetiklendi');renderSim()">Gecikme Senaryosu</button></div></div><div class="sim-card"><div class="sim-card-head"><h3>02 • Görevler</h3><div class="sim-filters"><button type="button" class="sim-chip ${!m.filterActive?'active':''}" onclick="sim.mobil.filterActive=false;renderSim()">Tümü</button><button type="button" class="sim-chip ${m.filterActive?'active':''}" onclick="sim.mobil.filterActive=true;renderSim()">Aktif</button></div></div><div class="sim-rows">${rows.map(r=>`<div class="sim-row"><div><strong>${r.title}</strong><small>${r.sub}</small></div><span class="${r.cls}">${r.badge}</span></div>`).join("")}</div>${renderSimLog("mobil")}</div>`;
        footer.textContent = `Rota: ${m.done}/${m.total} • ETA: ${m.eta}`;
      } else if (currentDemoId === "web-otomasyon") {
        const w = sim.web;
        const rows = w.onlyCrit ? w.flows.filter(f => f.crit) : w.flows;
        head.innerHTML = `<div class="sim-title-group"><strong>Web &amp; Botlar</strong><span class="sim-subpill">WEBHOOK &amp; BOT</span></div><div class="sim-kpi-row"><div class="sim-kpi ok"><span>Başarı</span><strong>%${w.successRate.toFixed(1)}</strong></div><div class="sim-kpi"><span>Form</span><strong>${w.leads}</strong></div><div class="sim-kpi ok"><span>Bildirim</span><strong>${w.sent}</strong></div><div class="sim-kpi warn"><span>Kuyruk</span><strong>${w.queue}</strong></div></div>`;
        grid.innerHTML = `<div class="sim-card"><div class="sim-card-head"><h3>01 • Bot İstasyonu</h3><span class="pill">AKTİF</span></div><div class="sim-highlight"><strong>${w.botTitle}</strong><div style="font-size:0.8rem;color:var(--muted);">${w.botSub}</div><div class="sim-bar"><div class="sim-bar-fill" style="width:${w.successRate}%;"></div></div></div><div class="sim-filters"><button type="button" class="btn-sm" onclick="sim.web.leads++;sim.web.sent++;pushSimLog('web','Form tetiklendi');renderSim()">Form Tetikle</button><button type="button" class="btn-amber-sm" onclick="sim.web.queue+=5;pushSimLog('web','Kritik webhook kuyrugu +5');renderSim()">Kritik Webhook</button><button type="button" class="btn-sm" onclick="sim.web.queue=0;pushSimLog('web','Kuyruk temizlendi');renderSim()">Kuyruğu Temizle</button></div></div><div class="sim-card"><div class="sim-card-head"><h3>02 • Akışlar</h3><div class="sim-filters"><button type="button" class="sim-chip ${!w.onlyCrit?'active':''}" onclick="sim.web.onlyCrit=false;renderSim()">Tümü</button><button type="button" class="sim-chip ${w.onlyCrit?'active':''}" onclick="sim.web.onlyCrit=true;renderSim()">Kritik</button></div></div><div class="sim-rows">${rows.map(r=>`<div class="sim-row"><div><strong>${r.title}</strong><small>${r.sub}</small></div><span class="${r.cls}">${r.badge}</span></div>`).join("")}</div>${renderSimLog("web")}</div>`;
        footer.textContent = `Başarı: %${w.successRate.toFixed(1)} • Kuyruk: ${w.queue}`;
      } else if (currentDemoId === "masaustu-otomasyon") {
        const d = sim.masaustu;
        const rows = d.onlyCrit ? d.items.filter(i => i.crit) : d.items;
        head.innerHTML = `<div class="sim-title-group"><strong>Masaüstü &amp; Barkod</strong><span class="sim-subpill">POS &amp; STOK</span></div><div class="sim-kpi-row"><div class="sim-kpi ok"><span>Satış</span><strong>${d.sales}</strong></div><div class="sim-kpi"><span>Stok</span><strong>${d.stockCount}</strong></div><div class="sim-kpi warn"><span>Kritik</span><strong>${d.critCount}</strong></div></div>`;
        grid.innerHTML = `<div class="sim-card"><div class="sim-card-head"><h3>01 • Kasa</h3><span class="pill">HAZIR</span></div><div class="sim-highlight"><div style="font-size:1.25rem;font-weight:800;">${d.barcode}</div><div style="font-size:0.84rem;color:var(--muted);">${d.product}</div></div><div class="sim-row"><strong>Sepet (${d.cartItems})</strong><strong>${d.cartTotal.toFixed(2)} TL</strong></div><div class="sim-filters"><button type="button" class="btn-sm" onclick="sim.masaustu.cartItems++;sim.masaustu.cartTotal+=85;pushSimLog('masaustu','+85 TL barkod eklendi');renderSim()">Barkod +85 TL</button><button type="button" class="btn-amber-sm" onclick="if(sim.masaustu.cartTotal>0){sim.masaustu.sales++;sim.masaustu.cartTotal=0;sim.masaustu.cartItems=0;pushSimLog('masaustu','Satis tamamlandi');renderSim()}">Satışı Tamamla</button><button type="button" class="btn-sm" onclick="sim.masaustu.stockCount+=50;pushSimLog('masaustu','+50 stok girisi');renderSim()">+50 Stok</button></div></div><div class="sim-card"><div class="sim-card-head"><h3>02 • Envanter</h3><div class="sim-filters"><button type="button" class="sim-chip ${!d.onlyCrit?'active':''}" onclick="sim.masaustu.onlyCrit=false;renderSim()">Tümü</button><button type="button" class="sim-chip ${d.onlyCrit?'active':''}" onclick="sim.masaustu.onlyCrit=true;renderSim()">Kritik</button></div></div><div class="sim-rows">${rows.map(r=>`<div class="sim-row"><div><strong>${r.title}</strong><small>${r.sub}</small></div><span class="${r.cls}">${r.badge}</span></div>`).join("")}</div>${renderSimLog("masaustu")}</div>`;
        footer.textContent = `Sepet: ${d.cartTotal.toFixed(2)} TL • Satış: ${d.sales}`;
      } else if (currentDemoId === "kafe-restoran-randevu") {
        const k = sim.kafe;
        const freeCount = k.tables.filter(t => !t.busy).length;
        const shown = k.onlyFree ? k.tables.filter(t => !t.busy) : k.tables;
        head.innerHTML = `<div class="sim-title-group"><strong>Kafe &amp; Restoran</strong><span class="sim-subpill">MASA PLANI</span></div><div class="sim-kpi-row"><div class="sim-kpi ok"><span>Boş Masa</span><strong>${freeCount}/${k.tables.length}</strong></div><div class="sim-kpi warn"><span>Bekleyen</span><strong>${k.pending}</strong></div></div>`;
        grid.innerHTML = `<div class="sim-card"><div class="sim-card-head"><h3>01 • Rezervasyon</h3><span class="pill">AKTİF</span></div><div class="row-2"><div><label>Kişi</label><div style="display:flex;gap:8px;align-items:center;"><button type="button" class="btn-secondary" style="padding:6px 10px;" onclick="if(sim.kafe.guests>1){sim.kafe.guests--;renderSim()}">-</button><strong>${k.guests}</strong><button type="button" class="btn-secondary" style="padding:6px 10px;" onclick="if(sim.kafe.guests<10){sim.kafe.guests++;renderSim()}">+</button></div></div><div><label>Misafir</label><input type="text" value="${k.guestName}" onchange="sim.kafe.guestName=this.value|| 'Misafir'" /></div></div><div class="sim-filters"><button type="button" class="btn-primary" onclick="const idx=sim.kafe.tables.findIndex(t=>!t.busy);if(idx!==-1){sim.kafe.tables[idx].busy=true;sim.kafe.tables[idx].info=sim.kafe.guestName;pushSimLog('kafe',sim.kafe.tables[idx].name+' ayrildi');renderSim()}">Boş Masaya Ekle</button><button type="button" class="btn-sm" onclick="sim.kafe.tables.forEach(t=>t.busy=false);pushSimLog('kafe','Masalar bosaltildi');renderSim()">Masaları Boşalt</button></div></div><div class="sim-card"><div class="sim-card-head"><h3>02 • Masalar</h3><div class="sim-filters"><button type="button" class="sim-chip ${!k.onlyFree?'active':''}" onclick="sim.kafe.onlyFree=false;renderSim()">Tümü</button><button type="button" class="sim-chip ${k.onlyFree?'active':''}" onclick="sim.kafe.onlyFree=true;renderSim()">Boş</button></div></div><div class="table-grid">${shown.map(t=>{const idx=k.tables.indexOf(t);return `<button type="button" class="table-chip ${t.busy?'busy':'free'}" onclick="sim.kafe.tables[${idx}].busy=!sim.kafe.tables[${idx}].busy;pushSimLog('kafe',sim.kafe.tables[${idx}].name+' degisti');renderSim()"><strong>${t.name} • ${t.cap}K</strong><span>${t.busy?'DOLU':'BOŞ'}</span></button>`;}).join("")}</div>${renderSimLog("kafe")}</div>`;
        footer.textContent = `Boş Masa: ${freeCount}/${k.tables.length}`;
      } else if (currentDemoId === "berber-kuafor-randevu") {
        const b = sim.berber;
        const pct = Math.min(100, Math.round((b.elapsed / b.totalMin) * 100));
        const activeSlot = b.slots[b.selectedSlot];
        head.innerHTML = `<div class="sim-title-group"><strong>Berber &amp; Kuaför</strong><span class="sim-subpill">SAAT YÖNETİMİ</span></div><div class="sim-kpi-row"><div class="sim-kpi ok"><span>Süre</span><strong>${b.elapsed}/${b.totalMin} dk</strong></div><div class="sim-kpi warn"><span>Çakışma</span><strong>AKTİF</strong></div></div>`;
        grid.innerHTML = `<div class="sim-card"><div class="sim-card-head"><h3>01 • Koltuk</h3><span class="pill">CANLI</span></div><div class="sim-highlight"><strong>${b.client}</strong><div style="font-size:0.8rem;color:var(--muted);">${b.service}</div><div class="sim-bar"><div class="sim-bar-fill" style="width:${pct}%;"></div></div></div><div class="sim-filters"><button type="button" class="btn-sm" onclick="sim.berber.elapsed=(sim.berber.elapsed+10)%(sim.berber.totalMin+1);renderSim()">+10 dk</button><button type="button" class="btn-amber-sm" onclick="if(activeSlot){activeSlot.booked=!activeSlot.booked;pushSimLog('berber',activeSlot.time+' guncellendi');renderSim()}">Slot Durumu Değiştir</button></div></div><div class="sim-card"><div class="sim-card-head"><h3>02 • Saatler</h3><span class="pill-amber">${activeSlot?activeSlot.time:'-'}</span></div><div class="slot-grid">${b.slots.map((s,idx)=>`<button type="button" class="slot-btn ${s.booked?'booked':(b.selectedSlot===idx?'selected':'')}" onclick="sim.berber.selectedSlot=${idx};renderSim()">${s.time}</button>`).join("")}</div>${renderSimLog("berber")}</div>`;
        footer.textContent = `Seçili Saat: ${activeSlot?activeSlot.time:'-'}`;
      } else {
        const q = sim.qr;
        head.innerHTML = `<div class="sim-title-group"><strong>Masa QR &amp; Garson</strong><span class="sim-subpill">ANLIK ÇAĞRI</span></div><div class="sim-kpi-row"><div class="sim-kpi ok"><span>Sipariş</span><strong>${q.ordersCount}</strong></div><div class="sim-kpi warn"><span>Garson</span><strong>${q.callsCount}</strong></div><div class="sim-kpi"><span>Hesap</span><strong>${q.billsCount}</strong></div></div>`;
        grid.innerHTML = `<div class="sim-card"><div class="sim-card-head"><h3>01 • QR Konsol</h3><span class="pill">QR AKTİF</span></div><div><label>Masa</label><select onchange="sim.qr.table=this.value"><option value="Masa 05">Masa 05</option><option value="Masa 08">Masa 08</option><option value="Masa 12">Masa 12</option></select></div><div class="sim-filters"><button type="button" class="btn-amber-sm" onclick="sim.qr.callsCount++;sim.qr.feed.unshift({title:sim.qr.table+' — Garson Çağrısı',sub:'Anlık Bildirim',badge:'GARSON BEKLİYOR',cls:'pill-amber'});sim.qr.feed=sim.qr.feed.slice(0,3);pushSimLog('qr',sim.qr.table+' garson cagirdi');renderSim()">Garson Çağır</button><button type="button" class="btn-sm" onclick="sim.qr.ordersCount++;sim.qr.feed.unshift({title:sim.qr.table+' — Yeni QR Sipariş',sub:'Bar/Mutfak',badge:'SERVİS HAZIR',cls:'pill'});sim.qr.feed=sim.qr.feed.slice(0,3);pushSimLog('qr',sim.qr.table+' siparis gonderdi');renderSim()">Sipariş Gönder</button><button type="button" class="btn-sm" onclick="if(sim.qr.feed[0]){sim.qr.feed[0].badge='TAMAMLANDI';sim.qr.feed[0].cls='pill';renderSim()}">Üst Çağrıyı Kapat</button></div></div><div class="sim-card"><div class="sim-card-head"><h3>02 • Canlı Akış</h3><span class="pill">CANLI</span></div><div class="sim-rows">${q.feed.map(f=>`<div class="sim-row"><div><strong>${f.title}</strong><small>${f.sub}</small></div><span class="${f.cls}">${f.badge}</span></div>`).join("")}</div>${renderSimLog("qr")}</div>`;
        footer.textContent = `Masa: ${q.table} • Çağrı: ${q.callsCount}`;
      }
    }

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

    const obs = new IntersectionObserver(entries => {
      entries.forEach(e => { if (e.isIntersecting) e.target.classList.add("visible"); });
    }, { threshold: 0.1 });
    document.querySelectorAll(".reveal").forEach(el => obs.observe(el));

    window.addEventListener("load", () => {
      switchDemo("mobil-otomasyon", document.querySelector('.demo-tab[data-demo="mobil-otomasyon"]'));
      document.querySelectorAll(".reveal").forEach(el => {
        if (el.getBoundingClientRect().top < window.innerHeight * 0.95) el.classList.add("visible");
      });
    });
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
  <title>{{ tenant.business_name }} — KOLAY Otomasyon</title>
  <style>
    :root { --bg:#080d0b; --card:#121d18; --soft:#0f1714; --text:#f8fafc; --muted:#9ca3af; --accent:#10b981; --bright:#34d399; --amber:#f59e0b; --border:rgba(16,185,129,0.22); }
    * { box-sizing:border-box; margin:0; padding:0; font-family:Inter,system-ui,sans-serif; }
    body { background:var(--bg); color:var(--text); padding:28px 18px 50px; }
    .wrap { max-width:960px; margin:0 auto; display:grid; gap:20px; }
    .top { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; border-bottom:1px solid var(--border); padding-bottom:16px; }
    .btn { text-decoration:none; padding:9px 14px; border-radius:10px; font-weight:700; font-size:0.88rem; border:1px solid var(--border); background:var(--card); color:var(--bright); }
    .btn-main { background:linear-gradient(135deg,var(--bright),var(--accent)); color:#04130d; border:none; }
    .card { background:var(--card); border:1px solid var(--border); border-radius:16px; padding:22px; display:grid; gap:14px; }
    label { display:block; font-size:0.84rem; color:#d1d5db; margin-bottom:6px; font-weight:600; }
    input, select, textarea { width:100%; padding:10px 12px; border-radius:10px; border:1px solid var(--border); background:var(--soft); color:var(--text); }
    .ok { padding:12px 14px; border-radius:10px; background:rgba(16,185,129,0.16); border:1px solid rgba(16,185,129,0.4); color:#a7f3d0; font-weight:600; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <div style="font-size:0.78rem;color:var(--amber);font-weight:800;">İŞLETME SAYFASI • /i/{{ tenant.slug }}</div>
        <h1 style="font-size:1.5rem;">{{ tenant.business_name }}</h1>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <a class="btn" href="{{ url_for('index') }}">← Ana SaaS</a>
        <a class="btn btn-main" href="{{ url_for('tenant_panel', slug=tenant.slug) }}">İşletme Paneli</a>
      </div>
    </div>

    {% if sent %}
    <div class="ok">Talebiniz <strong>{{ tenant.business_name }}</strong> paneline başarıyla iletildi!</div>
    {% endif %}

    <form class="card" method="POST">
      <h2 style="font-size:1.12rem;">Talep / Randevu / Sipariş Bırak</h2>
      <div><label>Ad Soyad</label><input type="text" name="name" required /></div>
      <div><label>Telefon</label><input type="text" name="phone" required /></div>
      <div>
        <label>Konu / Hizmet</label>
        <select name="service">
          {% for srv in services %}
          <option value="{{ srv.tag }} - {{ srv.title }}">{{ srv.tag }} — {{ srv.title }}</option>
          {% endfor %}
        </select>
      </div>
      <div><label>Mesaj / Not</label><textarea name="message" rows="4" required></textarea></div>
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
    <a href="{{ url_for('tenant_public', slug=tenant.slug) }}">← İşletme Vitrinine Dön</a>
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
    .btn { text-decoration:none; padding:9px 14px; border-radius:10px; font-weight:700; font-size:0.86rem; border:1px solid var(--border); background:var(--card); color:var(--bright); cursor:pointer; }
    .btn-del { background:rgba(239,68,68,0.14); border-color:rgba(239,68,68,0.35); color:#fca5a5; }
    .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; }
    .stat { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:14px 16px; }
    .stat span { font-size:0.78rem; color:var(--muted); display:block; }
    .stat strong { font-size:1.5rem; color:var(--bright); }
    .card { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:18px; display:grid; gap:10px; }
    .msg { background:var(--soft); padding:12px; border-radius:10px; font-size:0.92rem; }
    select { padding:8px 10px; border-radius:8px; border:1px solid var(--border); background:var(--soft); color:var(--text); }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <h1>{{ tenant.business_name }} — Talep Paneli</h1>
        <p style="color:var(--muted);font-size:0.86rem;">Slug: <code>{{ tenant.slug }}</code> • Plan: <code>{{ tenant.plan|upper }}</code> • Supabase PostgreSQL</p>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <a class="btn" href="{{ url_for('tenant_public', slug=tenant.slug) }}">Vitrin Linki</a>
        <form method="POST" action="{{ url_for('tenant_logout', slug=tenant.slug) }}"><button type="submit" class="btn btn-del">Çıkış</button></form>
      </div>
    </div>

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
      <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;">
        <form method="POST" action="{{ url_for('tenant_update_ticket', slug=tenant.slug, ticket_id=t.id) }}" style="display:flex;gap:8px;">
          <select name="status">
            <option value="Yeni" {% if t.status=='Yeni' %}selected{% endif %}>Yeni</option>
            <option value="İnceleniyor" {% if t.status=='İnceleniyor' %}selected{% endif %}>İnceleniyor</option>
            <option value="Tamamlandı" {% if t.status=='Tamamlandı' %}selected{% endif %}>Tamamlandı</option>
          </select>
          <button type="submit" class="btn">Güncelle</button>
        </form>
        <form method="POST" action="{{ url_for('tenant_delete_ticket', slug=tenant.slug, ticket_id=t.id) }}" onsubmit="return confirm('Silinsin mi?');">
          <button type="submit" class="btn btn-del">Sil</button>
        </form>
      </div>
    </div>
    {% else %}
    <div class="card" style="text-align:center;color:var(--muted);">Bu işletmeye ait henüz kayıt yok.</div>
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
  <title>Süper Admin — İşletme Yönetimi</title>
  <style>
    :root { --bg:#080d0b; --card:#121d18; --soft:#0f1714; --text:#f8fafc; --muted:#9ca3af; --accent:#10b981; --bright:#34d399; --amber:#f59e0b; --border:rgba(16,185,129,0.22); }
    * { box-sizing:border-box; margin:0; padding:0; font-family:Inter,system-ui,sans-serif; }
    body { background:var(--bg); color:var(--text); padding:24px 18px 48px; }
    .wrap { max-width:1120px; margin:0 auto; display:grid; gap:20px; }
    .top { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; border-bottom:1px solid var(--border); padding-bottom:16px; }
    .btn { text-decoration:none; padding:8px 13px; border-radius:9px; font-weight:700; font-size:0.84rem; border:1px solid var(--border); background:var(--card); color:var(--bright); cursor:pointer; }
    .card { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:18px; display:grid; gap:12px; }
    select { padding:7px 10px; border-radius:8px; border:1px solid var(--border); background:var(--soft); color:var(--text); }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <h1>Süper Admin — Tüm İşletmeler</h1>
        <p style="color:var(--muted);font-size:0.86rem;">Toplam {{ tenants|length }} kayıtlı işletme</p>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <a class="btn" href="{{ url_for('index') }}">← Vitrin</a>
        <form method="POST" action="{{ url_for('superadmin_logout') }}"><button type="submit" class="btn">Çıkış</button></form>
      </div>
    </div>

    {% for tn in tenants %}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
        <div>
          <strong>{{ tn.business_name }}</strong> • <code>/i/{{ tn.slug }}</code>
          <div style="font-size:0.82rem;color:var(--muted);">{{ tn.owner_email }} • Talep Sayısı: {{ tn.ticket_count }}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <a class="btn" href="{{ url_for('tenant_public', slug=tn.slug) }}">Vitrin</a>
          <a class="btn" href="{{ url_for('tenant_panel', slug=tn.slug) }}">Panel</a>
          <form method="POST" action="{{ url_for('superadmin_tenant_plan', tenant_id=tn.id) }}" style="display:flex;gap:6px;">
            <select name="plan">
              <option value="free" {% if tn.plan=='free' %}selected{% endif %}>FREE</option>
              <option value="pro" {% if tn.plan=='pro' %}selected{% endif %}>PRO</option>
            </select>
            <button type="submit" class="btn">Kaydet</button>
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
        created_tenant=created_tenant,
        saas_error=saas_error,
    )


@app.route("/saas/register", methods=["POST"])
def register_tenant():
    business_name = request.form.get("business_name", "").strip()
    raw_slug = request.form.get("slug", "").strip()
    owner_email = request.form.get("owner_email", "").strip()
    password = request.form.get("password", "").strip()
    plan = request.form.get("plan", "free").strip()

    if not business_name or not owner_email or len(password) < 4:
        return redirect(url_for("index", err="İşletme adı, e-posta ve en az 4 karakter şifre zorunlu.") + "#saas-basla")

    try:
        tenant = create_tenant(business_name, owner_email, password, raw_slug=raw_slug, plan=plan)
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


@app.route("/i/<slug>", methods=["GET", "POST"])
def tenant_public(slug):
    tenant = get_tenant_by_slug(slug)
    if not tenant or not tenant["is_active"]:
        abort(404)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        service = request.form.get("service", "").strip()
        message = request.form.get("message", "").strip()
        if name and message:
            add_ticket(tenant["id"], name, phone, service, message)
        return redirect(url_for("tenant_public", slug=slug, sent="1"))

    sent = request.args.get("sent") == "1"
    return render_template_string(TENANT_PUBLIC_HTML, tenant=tenant, services=SERVICES_DATA, sent=sent)


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
    return render_template_string(SUPERADMIN_HTML, tenants=tenants)


@app.route("/admin/tenant/<int:tenant_id>/plan", methods=["POST"])
@superadmin_required
def superadmin_tenant_plan(tenant_id):
    plan = request.form.get("plan", "free").strip()
    if plan not in {"free", "pro"}:
        plan = "free"
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET plan = %s WHERE id = %s", (plan, tenant_id))
    return redirect(url_for("superadmin_panel"))


if __name__ == "__main__":
    app.run(debug=True)
