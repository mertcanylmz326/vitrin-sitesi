import functools
import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
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
DB_FILE = BASE_DIR / "tickets.db"
LEGACY_JSON_FILE = BASE_DIR / "tickets.json"

ADMIN_USERNAME = "rootadmin"
ADMIN_PASSWORD = "adminroot"
WHATSAPP_NUMBER = "905418007395"

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


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT,
                service TEXT,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Yeni',
                created_at TEXT NOT NULL
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) AS cnt FROM tickets").fetchone()["cnt"]
        if count == 0 and LEGACY_JSON_FILE.exists():
            try:
                raw = json.loads(LEGACY_JSON_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    for item in reversed(raw):
                        if isinstance(item, dict) and item.get("name") and item.get("message"):
                            t_id = str(item.get("id") or uuid.uuid4().hex[:8])
                            conn.execute(
                                """
                                INSERT OR IGNORE INTO tickets (id, name, phone, service, message, status, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    t_id,
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


def load_tickets():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, phone, service, message, status, created_at FROM tickets ORDER BY rowid DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def add_ticket(name, phone, service, message):
    ticket_id = uuid.uuid4().hex[:8]
    created_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO tickets (id, name, phone, service, message, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'Yeni', ?)
            """,
            (ticket_id, name, phone, service, message, created_at),
        )


def update_ticket_status(ticket_id, new_status):
    with get_db() as conn:
        conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (new_status, ticket_id))


def delete_ticket_by_id(ticket_id):
    with get_db() as conn:
        conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))


def login_required(view_func):
    @functools.wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("panel_auth"):
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapped


init_db()

INDEX_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>KOLAY Otomasyon ve Web Sistemleri</title>
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
      --wa: #22c55e;
      --border: rgba(16, 185, 129, 0.2);
      --glow: rgba(16, 185, 129, 0.18);
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: "Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    html {
      scroll-behavior: smooth;
    }

    body {
      background:
        radial-gradient(circle at 12% 8%, rgba(16, 185, 129, 0.15), transparent 36%),
        radial-gradient(circle at 88% 16%, rgba(245, 158, 11, 0.11), transparent 38%),
        var(--bg);
      color: var(--text);
      line-height: 1.6;
      overflow-x: hidden;
    }

    .container {
      max-width: 1180px;
      margin: 0 auto;
      padding: 0 22px;
    }

    .wp-icon {
      width: 18px;
      height: 18px;
      flex-shrink: 0;
      display: inline-block;
    }

    .wp-icon-lg {
      width: 24px;
      height: 24px;
      flex-shrink: 0;
      display: inline-block;
    }

    .navbar {
      position: sticky;
      top: 0;
      z-index: 40;
      backdrop-filter: blur(14px);
      background: rgba(8, 13, 11, 0.84);
      border-bottom: 1px solid var(--border);
    }

    .nav-inner {
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-height: 72px;
      padding: 10px 0;
      gap: 16px;
      flex-wrap: wrap;
    }

    .brand {
      display: inline-flex;
      align-items: center;
      gap: 11px;
      font-weight: 800;
      font-size: 1.04rem;
      letter-spacing: 0.2px;
      color: var(--text);
      text-decoration: none;
    }

    .brand-logo-img {
      height: 40px;
      width: auto;
      max-width: 58px;
      object-fit: contain;
      border-radius: 10px;
      display: block;
    }

    .brand-badge {
      width: 32px;
      height: 32px;
      border-radius: 10px;
      display: grid;
      place-items: center;
      font-weight: 900;
      font-size: 0.95rem;
      color: #04130d;
      background: linear-gradient(135deg, var(--accent-bright), var(--accent-2));
      box-shadow: 0 0 18px rgba(16, 185, 129, 0.35);
    }

    .brand-text small {
      display: block;
      font-size: 0.72rem;
      font-weight: 600;
      color: var(--accent-bright);
      letter-spacing: 0.4px;
    }

    .nav-links {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    .nav-btn {
      color: var(--muted);
      text-decoration: none;
      font-size: 0.92rem;
      font-weight: 600;
      padding: 9px 15px;
      border-radius: 10px;
      border: 1px solid transparent;
      transition: all 0.24s ease;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }

    .nav-btn:hover,
    .nav-btn.active {
      color: var(--text);
      background: rgba(16, 185, 129, 0.12);
      border-color: rgba(16, 185, 129, 0.32);
      transform: translateY(-1px);
    }

    .nav-cta {
      color: #04130d;
      background: linear-gradient(135deg, var(--accent-bright), var(--accent));
      font-weight: 800;
    }

    .nav-cta:hover {
      color: #04130d;
      box-shadow: 0 8px 24px rgba(16, 185, 129, 0.3);
    }

    .nav-wa {
      color: #dcfce7;
      background: rgba(34, 197, 94, 0.16);
      border: 1px solid rgba(34, 197, 94, 0.42);
      font-weight: 700;
    }

    .nav-wa:hover {
      color: #ffffff;
      background: rgba(34, 197, 94, 0.28);
      border-color: rgba(34, 197, 94, 0.68);
      box-shadow: 0 8px 22px rgba(34, 197, 94, 0.22);
    }

    .reveal {
      opacity: 0;
      transform: translateY(20px);
      transition: opacity 0.65s cubic-bezier(0.22, 1, 0.36, 1), transform 0.65s cubic-bezier(0.22, 1, 0.36, 1);
    }

    .reveal.visible {
      opacity: 1;
      transform: translateY(0);
    }

    .hero {
      padding: 68px 0 46px;
      display: grid;
      grid-template-columns: 1.25fr 0.75fr;
      gap: 28px;
      align-items: center;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 0.82rem;
      font-weight: 700;
      color: var(--accent-bright);
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.28);
      margin-bottom: 18px;
    }

    .hero h1 {
      font-size: clamp(2.05rem, 4.3vw, 3.25rem);
      line-height: 1.14;
      letter-spacing: -0.02em;
      margin-bottom: 18px;
    }

    .hero h1 span {
      background: linear-gradient(135deg, var(--accent-bright), var(--accent-2));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .hero p {
      color: var(--muted);
      font-size: 1.03rem;
      max-width: 630px;
      margin-bottom: 26px;
    }

    .hero-actions {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }

    .btn-primary,
    .btn-secondary,
    .btn-wa,
    .btn-sm {
      text-decoration: none;
      padding: 12px 19px;
      border-radius: 11px;
      font-weight: 700;
      font-size: 0.92rem;
      transition: transform 0.22s ease, box-shadow 0.22s ease, background 0.22s ease;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
    }

    .btn-primary {
      background: linear-gradient(135deg, var(--accent-bright), var(--accent));
      color: #04130d;
      border: none;
      box-shadow: 0 10px 26px rgba(16, 185, 129, 0.22);
    }

    .btn-primary:hover {
      transform: translateY(-2px);
      box-shadow: 0 14px 30px rgba(16, 185, 129, 0.34);
    }

    .btn-secondary {
      background: var(--card);
      color: var(--text);
      border: 1px solid var(--border);
    }

    .btn-secondary:hover {
      transform: translateY(-2px);
      background: var(--card-hover);
      border-color: rgba(16, 185, 129, 0.42);
    }

    .btn-wa {
      background: linear-gradient(135deg, #22c55e, #16a34a);
      color: #052e16;
      border: none;
      box-shadow: 0 10px 24px rgba(34, 197, 94, 0.24);
    }

    .btn-wa:hover {
      transform: translateY(-2px);
      box-shadow: 0 14px 28px rgba(34, 197, 94, 0.36);
    }

    .btn-sm {
      padding: 8px 12px;
      font-size: 0.8rem;
      border-radius: 9px;
      background: rgba(16, 185, 129, 0.14);
      color: var(--accent-bright);
      border: 1px solid rgba(16, 185, 129, 0.35);
    }

    .btn-sm:hover {
      background: rgba(16, 185, 129, 0.24);
    }

    .btn-amber-sm {
      padding: 8px 12px;
      font-size: 0.8rem;
      border-radius: 9px;
      background: rgba(245, 158, 11, 0.15);
      color: #fcd34d;
      border: 1px solid rgba(245, 158, 11, 0.38);
      font-weight: 700;
      cursor: pointer;
    }

    .btn-amber-sm:hover {
      background: rgba(245, 158, 11, 0.25);
    }

    .hero-panel {
      background: linear-gradient(160deg, rgba(19, 32, 27, 0.94), rgba(10, 17, 14, 0.94));
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 24px;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.42);
      animation: floatCard 5s ease-in-out infinite;
    }

    @keyframes floatCard {
      0%, 100% { transform: translateY(0px); }
      50% { transform: translateY(-6px); }
    }

    .panel-title {
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--accent-2);
      margin-bottom: 14px;
      font-weight: 800;
    }

    .mini-list {
      list-style: none;
      display: grid;
      gap: 10px;
    }

    .mini-list li {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 11px 14px;
      border-radius: 12px;
      background: rgba(8, 13, 11, 0.65);
      border: 1px solid rgba(16, 185, 129, 0.14);
      font-size: 0.91rem;
      gap: 8px;
    }

    .pill {
      font-size: 0.73rem;
      padding: 3px 9px;
      border-radius: 999px;
      background: rgba(16, 185, 129, 0.16);
      color: var(--accent-bright);
      font-weight: 700;
      white-space: nowrap;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }

    .pill-amber {
      font-size: 0.73rem;
      padding: 3px 9px;
      border-radius: 999px;
      background: rgba(245, 158, 11, 0.16);
      color: #fcd34d;
      font-weight: 700;
      white-space: nowrap;
      border: 1px solid rgba(245, 158, 11, 0.36);
    }

    .pill-blue {
      font-size: 0.73rem;
      padding: 3px 9px;
      border-radius: 999px;
      background: rgba(56, 189, 248, 0.15);
      color: #7dd3fc;
      font-weight: 700;
      white-space: nowrap;
      border: 1px solid rgba(56, 189, 248, 0.34);
    }

    section.block {
      padding: 60px 0;
    }

    .section-head {
      margin-bottom: 24px;
    }

    .section-head span {
      color: var(--accent-2);
      font-size: 0.82rem;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .section-head h2 {
      font-size: clamp(1.6rem, 3vw, 2.25rem);
      margin-top: 6px;
      margin-bottom: 10px;
    }

    .section-head p {
      color: var(--muted);
      max-width: 760px;
    }

    .demo-tabs {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 16px;
    }

    .demo-tab {
      background: var(--card);
      color: var(--muted);
      border: 1px solid var(--border);
      padding: 10px 15px;
      border-radius: 11px;
      font-size: 0.88rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.2s ease;
    }

    .demo-tab:hover {
      color: var(--text);
      border-color: rgba(16, 185, 129, 0.45);
      background: var(--card-hover);
    }

    .demo-tab.active {
      color: #04130d;
      background: linear-gradient(135deg, var(--accent-bright), var(--accent));
      border-color: transparent;
      box-shadow: 0 8px 22px rgba(16, 185, 129, 0.25);
    }

    .sim-frame {
      background: #0c1411;
      border: 1px solid rgba(16, 185, 129, 0.28);
      border-radius: 18px;
      overflow: hidden;
      box-shadow: 0 28px 68px rgba(0, 0, 0, 0.56);
    }

    .sim-topbar {
      background: #070c0a;
      border-bottom: 1px solid rgba(16, 185, 129, 0.16);
      padding: 10px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }

    .sim-dots {
      display: inline-flex;
      gap: 6px;
      align-items: center;
    }

    .sim-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
    }

    .sim-header-strip {
      background: #0d1613;
      border-bottom: 1px solid rgba(16, 185, 129, 0.16);
      padding: 14px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      flex-wrap: wrap;
    }

    .sim-title-group {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    .sim-title-group strong {
      font-size: 1.08rem;
      color: var(--text);
    }

    .sim-subpill {
      font-size: 0.76rem;
      font-weight: 700;
      color: var(--accent-bright);
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.28);
      padding: 3px 10px;
      border-radius: 8px;
    }

    .sim-kpi-row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }

    .sim-kpi {
      background: #080e0c;
      border: 1px solid rgba(16, 185, 129, 0.16);
      border-radius: 10px;
      padding: 7px 12px;
      min-width: 118px;
    }

    .sim-kpi span {
      display: block;
      font-size: 0.7rem;
      color: var(--muted);
    }

    .sim-kpi strong {
      font-size: 0.94rem;
      color: var(--text);
    }

    .sim-kpi.ok strong {
      color: var(--accent-bright);
    }

    .sim-kpi.warn strong {
      color: #fbbf24;
    }

    .sim-grid {
      padding: 18px;
      display: grid;
      grid-template-columns: 0.96fr 1.14fr;
      gap: 18px;
      align-items: start;
    }

    .sim-card {
      background: #0e1814;
      border: 1px solid rgba(16, 185, 129, 0.18);
      border-radius: 14px;
      padding: 16px;
      display: grid;
      gap: 14px;
    }

    .sim-card-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      padding-bottom: 10px;
      border-bottom: 1px solid rgba(16, 185, 129, 0.12);
    }

    .sim-card-head h3 {
      font-size: 0.86rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: #d1fae5;
    }

    .sim-highlight {
      background: linear-gradient(145deg, rgba(16, 185, 129, 0.12), rgba(8, 14, 12, 0.92));
      border: 1px solid rgba(16, 185, 129, 0.34);
      border-radius: 13px;
      padding: 15px;
      display: grid;
      gap: 10px;
    }

    .sim-bar {
      width: 100%;
      height: 8px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.08);
      overflow: hidden;
    }

    .sim-bar-fill {
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--accent), var(--accent-bright));
      transition: width 0.3s ease;
    }

    .sim-3col {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }

    .sim-mini-box {
      background: #080e0c;
      border: 1px solid rgba(16, 185, 129, 0.14);
      border-radius: 10px;
      padding: 9px 10px;
    }

    .sim-mini-box small {
      display: block;
      font-size: 0.71rem;
      color: var(--muted);
    }

    .sim-mini-box strong {
      font-size: 0.86rem;
      color: var(--text);
    }

    .sim-filters {
      display: flex;
      gap: 7px;
      flex-wrap: wrap;
      align-items: center;
    }

    .sim-chip {
      padding: 5px 11px;
      border-radius: 999px;
      font-size: 0.76rem;
      font-weight: 700;
      background: #080e0c;
      color: var(--muted);
      border: 1px solid rgba(16, 185, 129, 0.18);
      cursor: pointer;
    }

    .sim-chip.active {
      background: rgba(16, 185, 129, 0.18);
      color: var(--accent-bright);
      border-color: rgba(16, 185, 129, 0.45);
    }

    .sim-rows {
      display: grid;
      gap: 8px;
    }

    .sim-row {
      background: #09100d;
      border: 1px solid rgba(16, 185, 129, 0.14);
      border-radius: 11px;
      padding: 11px 13px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    .sim-row strong {
      display: block;
      font-size: 0.87rem;
      color: var(--text);
    }

    .sim-row small {
      color: var(--muted);
      font-size: 0.77rem;
    }

    .table-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }

    .table-chip {
      padding: 10px;
      border-radius: 10px;
      border: 1px solid rgba(16, 185, 129, 0.2);
      background: #09100d;
      cursor: pointer;
      text-align: left;
      transition: transform 0.15s ease;
    }

    .table-chip:hover {
      transform: translateY(-1px);
    }

    .table-chip strong {
      display: block;
      font-size: 0.84rem;
      color: var(--text);
    }

    .table-chip span {
      font-size: 0.73rem;
      color: var(--muted);
    }

    .table-chip.free {
      border-color: rgba(16, 185, 129, 0.45);
      background: rgba(16, 185, 129, 0.11);
    }

    .table-chip.busy {
      border-color: rgba(245, 158, 11, 0.48);
      background: rgba(245, 158, 11, 0.12);
    }

    .slot-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }

    .slot-btn {
      padding: 9px;
      border-radius: 9px;
      border: 1px solid rgba(16, 185, 129, 0.25);
      background: #09100d;
      color: var(--text);
      font-size: 0.81rem;
      font-weight: 700;
      cursor: pointer;
    }

    .slot-btn.booked {
      background: rgba(239, 68, 68, 0.14);
      border-color: rgba(239, 68, 68, 0.36);
      color: #fca5a5;
    }

    .slot-btn.selected {
      background: rgba(16, 185, 129, 0.22);
      border-color: var(--accent-bright);
      color: #a7f3d0;
    }

    .sim-log {
      background: #060a08;
      border: 1px solid rgba(16, 185, 129, 0.16);
      border-radius: 10px;
      padding: 11px 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.77rem;
      color: #a7f3d0;
      max-height: 128px;
      overflow-y: auto;
      display: grid;
      gap: 4px;
    }

    .sim-footer {
      background: #080d0b;
      border-top: 1px solid rgba(16, 185, 129, 0.16);
      padding: 12px 18px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }

    .ref-shot-box {
      margin-top: 14px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
      display: none;
    }

    .ref-shot-box.open {
      display: block;
    }

    .ref-shot-box img {
      width: 100%;
      max-height: 360px;
      object-fit: contain;
      border-radius: 10px;
      background: #060a08;
      display: block;
    }

    .services-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 18px;
    }

    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 18px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      cursor: pointer;
      transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease, background 0.25s ease;
    }

    .card:hover {
      transform: translateY(-5px);
      background: var(--card-hover);
      border-color: rgba(16, 185, 129, 0.48);
      box-shadow: 0 18px 40px var(--glow);
    }

    .card-thumb {
      width: 100%;
      aspect-ratio: 16 / 9;
      object-fit: cover;
      display: block;
      border-bottom: 1px solid rgba(16, 185, 129, 0.16);
      background: var(--bg-soft);
    }

    .card-body {
      padding: 20px 22px 14px;
    }

    .card-tag {
      display: inline-block;
      font-size: 0.76rem;
      font-weight: 700;
      color: var(--accent-bright);
      background: rgba(16, 185, 129, 0.12);
      padding: 4px 10px;
      border-radius: 8px;
      margin-bottom: 10px;
    }

    .card h3 {
      font-size: 1.14rem;
      margin-bottom: 8px;
    }

    .card p {
      color: var(--muted);
      font-size: 0.93rem;
    }

    .card-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 22px 18px;
      margin-top: 8px;
      border-top: 1px solid rgba(156, 163, 175, 0.12);
    }

    .detail-link {
      background: transparent;
      border: none;
      color: var(--accent-2);
      font-weight: 700;
      font-size: 0.9rem;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: transform 0.2s ease, color 0.2s ease;
    }

    .card:hover .detail-link {
      color: #fbbf24;
      transform: translateX(3px);
    }

    .modal-backdrop {
      position: fixed;
      inset: 0;
      z-index: 90;
      background: rgba(4, 8, 6, 0.78);
      backdrop-filter: blur(8px);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 20px;
      animation: fadeIn 0.2s ease;
    }

    .modal-backdrop.open {
      display: flex;
    }

    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }

    .modal-box {
      width: 100%;
      max-width: 600px;
      max-height: 90vh;
      overflow-y: auto;
      background: #101915;
      border: 1px solid rgba(16, 185, 129, 0.35);
      border-radius: 22px;
      padding: 26px;
      box-shadow: 0 28px 70px rgba(0, 0, 0, 0.6);
      transform: scale(0.96);
      animation: popIn 0.22s ease forwards;
    }

    @keyframes popIn {
      to { transform: scale(1); }
    }

    .modal-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 14px;
    }

    .modal-img {
      width: 100%;
      aspect-ratio: 16 / 9;
      object-fit: cover;
      border-radius: 14px;
      border: 1px solid rgba(16, 185, 129, 0.22);
      margin-bottom: 16px;
      display: block;
    }

    .modal-close {
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.12);
      color: var(--text);
      width: 34px;
      height: 34px;
      border-radius: 10px;
      font-size: 1.1rem;
      cursor: pointer;
    }

    .modal-close:hover {
      background: rgba(239, 68, 68, 0.18);
      border-color: rgba(239, 68, 68, 0.4);
    }

    .modal-box h3 {
      font-size: 1.38rem;
      margin-bottom: 10px;
    }

    .modal-desc {
      color: #d1d5db;
      font-size: 0.96rem;
      margin-bottom: 18px;
    }

    .modal-list {
      list-style: none;
      display: grid;
      gap: 9px;
      margin-bottom: 22px;
    }

    .modal-list li {
      padding: 10px 13px;
      border-radius: 10px;
      background: rgba(8, 13, 11, 0.72);
      border: 1px solid rgba(16, 185, 129, 0.16);
      font-size: 0.91rem;
      color: #e5e7eb;
    }

    .modal-list li::before {
      content: "✓ ";
      color: var(--accent-bright);
      font-weight: 800;
      margin-right: 6px;
    }

    .modal-actions {
      display: flex;
      gap: 10px;
      justify-content: flex-end;
      flex-wrap: wrap;
    }

    .contact-wrap {
      display: grid;
      grid-template-columns: 0.9fr 1.1fr;
      gap: 24px;
      align-items: start;
    }

    .contact-info {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 24px;
      display: grid;
      gap: 14px;
    }

    .info-item {
      padding: 14px;
      border-radius: 12px;
      background: var(--bg-soft);
      border: 1px solid rgba(16, 185, 129, 0.12);
    }

    .info-item strong {
      display: block;
      font-size: 0.92rem;
      margin-bottom: 4px;
      color: var(--accent-bright);
    }

    .info-item span {
      color: var(--muted);
      font-size: 0.88rem;
    }

    .wa-box {
      padding: 18px;
      border-radius: 14px;
      background: rgba(34, 197, 94, 0.08);
      border: 1px solid rgba(34, 197, 94, 0.3);
      display: grid;
      gap: 10px;
    }

    .wa-head {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .wa-head strong {
      color: #86efac;
      font-size: 1rem;
    }

    .contact-form {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 26px;
      display: grid;
      gap: 14px;
    }

    .alert-ok {
      padding: 12px 14px;
      border-radius: 10px;
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.4);
      color: #a7f3d0;
      font-size: 0.9rem;
      font-weight: 600;
    }

    .row-2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }

    label {
      display: block;
      font-size: 0.85rem;
      color: #d1d5db;
      margin-bottom: 6px;
      font-weight: 600;
    }

    input,
    select,
    textarea {
      width: 100%;
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--bg-soft);
      color: var(--text);
      font-size: 0.92rem;
      transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }

    input:focus,
    select:focus,
    textarea:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.18);
    }

    .submit-btn {
      padding: 13px 18px;
      border-radius: 11px;
      border: none;
      cursor: pointer;
      font-weight: 800;
      font-size: 0.96rem;
      color: #04130d;
      background: linear-gradient(135deg, var(--accent-bright), var(--accent-2));
      transition: transform 0.2s ease, box-shadow 0.2s ease;
    }

    .submit-btn:hover {
      transform: translateY(-2px);
      box-shadow: 0 12px 26px rgba(16, 185, 129, 0.28);
    }

    footer {
      border-top: 1px solid var(--border);
      padding: 26px 0;
      margin-top: 30px;
      color: var(--muted);
      font-size: 0.88rem;
      display: flex;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
    }

    footer a {
      color: var(--muted);
      text-decoration: none;
    }

    footer a:hover {
      color: var(--accent-bright);
    }

    @media (max-width: 920px) {
      .hero,
      .sim-grid,
      .contact-wrap,
      .row-2,
      .sim-3col {
        grid-template-columns: 1fr;
      }

      .hero {
        padding-top: 46px;
      }
    }
  </style>
</head>
<body>
  <svg style="display:none;" aria-hidden="true">
    <symbol id="icon-whatsapp" viewBox="0 0 24 24">
      <path fill="currentColor" d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.45 1.32 4.95L2.05 22l5.25-1.38c1.45.79 3.08 1.21 4.74 1.21 5.46 0 9.91-4.45 9.91-9.91S17.5 2 12.04 2zm5.82 14.05c-.24.68-1.41 1.3-1.95 1.38-.5.08-1.14.11-1.84-.11-.42-.13-.97-.31-1.67-.61-2.94-1.27-4.86-4.23-5.01-4.43-.15-.2-1.19-1.58-1.19-3.02 0-1.44.75-2.15 1.02-2.44.27-.29.59-.37.79-.37.2 0 .4.01.57.01.18 0 .43-.07.67.51.24.59.83 2.03.9 2.18.07.15.12.32.02.52-.1.2-.15.32-.3.5-.15.17-.31.39-.45.52-.15.15-.3.31-.13.61.17.3.77 1.27 1.65 2.06 1.14 1.02 2.1 1.34 2.4 1.49.3.15.48.12.66-.07.18-.2.76-.89.96-1.19.2-.3.41-.25.69-.15.28.1 1.78.84 2.08.99.3.15.5.22.58.35.07.12.07.72-.17 1.4z"/>
    </symbol>
  </svg>

  <header class="navbar">
    <div class="container nav-inner">
      <a href="#anasayfa" class="brand">
        <img
          src="/images/logo.png"
          alt="KOLAY Otomasyon ve Web Sistemleri Logosu"
          class="brand-logo-img"
          onerror="if(!this.dataset.fb){this.dataset.fb='1';this.src='/logo.png';}else{this.style.display='none';document.getElementById('fallbackBadge').style.display='grid';}"
        />
        <span id="fallbackBadge" class="brand-badge" style="display: none;">K</span>
        <span class="brand-text">
          KOLAY
          <small>Otomasyon ve Web Sistemleri</small>
        </span>
      </a>
      <nav class="nav-links">
        <a href="#anasayfa" class="nav-btn active">Anasayfa</a>
        <a href="#canli-demo" class="nav-btn">Canlı Demo</a>
        <a href="#hizmetler" class="nav-btn">Hizmetler</a>
        <a href="#iletisim" class="nav-btn nav-cta">İletişim</a>
        <a href="https://wa.me/{{ wa_number }}?text={{ 'Merhaba KOLAY Otomasyon, sistemleriniz hakkında bilgi almak istiyorum.' | urlencode }}" target="_blank" rel="noopener noreferrer" class="nav-btn nav-wa" aria-label="WhatsApp">
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
          <div class="badge">KOLAY Otomasyon ve Web Sistemleri</div>
          <h1>İşletmen İçin <span>Hızlı, Akıllı ve Kolay</span> Dijital Sistemler</h1>
          <p>
            Mobil, web ve masaüstü otomasyonlardan kafe-restoran randevu ve masa QR sipariş/garson çağır sistemlerine,
            berber-kuaför randevu altyapısına kadar tüm operasyonunu hızlandıran pratik yazılımlar geliştiriyoruz.
          </p>
          <div class="hero-actions">
            <a href="#canli-demo" class="btn-primary">Simülasyonu Dene</a>
            <a href="https://wa.me/{{ wa_number }}?text={{ 'Merhaba KOLAY Otomasyon, hızlı teklif almak istiyorum.' | urlencode }}" target="_blank" rel="noopener noreferrer" class="btn-wa" aria-label="WhatsApp">
              <svg class="wp-icon"><use href="#icon-whatsapp"></use></svg>
              <span>WhatsApp</span>
            </a>
            <a href="#iletisim" class="btn-secondary">Talep Formu</a>
          </div>
        </div>

        <aside class="hero-panel reveal">
          <div class="panel-title">Öne Çıkan Çözümlerimiz</div>
          <ul class="mini-list">
            <li><span>Mobil, Web &amp; Masaüstü Otomasyon</span><span class="pill">Özel Yazılım</span></li>
            <li><span>Kafe &amp; Restoran Randevu Sistemi</span><span class="pill">Masa Planı</span></li>
            <li><span>Berber &amp; Kuaför Randevu Sistemi</span><span class="pill">Saat/Koltuk</span></li>
            <li><span>Masa QR Sipariş &amp; Garson Çağır</span><span class="pill">Anlık Bildirim</span></li>
          </ul>
        </aside>
      </div>
    </section>

    <section id="canli-demo" class="block">
      <div class="container">
        <div class="section-head reveal">
          <span>Birebir Sistem Simülasyonu</span>
          <h2>Görsellerdeki Kontrol Panellerini Canlı Kullan</h2>
          <p>
            Her sekmede panel yerleşimini, durum etiketlerini, sayaçları, senaryo tetikleyicilerini ve canlı sistem loglarını birebir etkileşimli simülasyon olarak çalıştırabilirsin.
          </p>
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
              <span id="simWinLabel" style="font-size: 0.81rem; color: var(--muted); font-weight: 600; margin-left: 8px;">KOLAY Otomasyon • Simülasyon</span>
            </div>
            <span class="pill">BİREBİR SİMÜLASYON</span>
          </div>

          <div id="simHeaderStrip" class="sim-header-strip"></div>

          <div id="simGrid" class="sim-grid"></div>

          <div class="sim-footer">
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
              <button type="button" class="btn-primary" onclick="applyDemoServiceToForm()">Bu Sistemi Formda Seç</button>
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
          <span>Hizmetler</span>
          <h2>İhtiyacına Uygun Sistemi Seç ve İncele</h2>
          <p>
            Herhangi bir hizmet kartına tıklayarak sistem arayüzünü, özelliklerini ve işletmene sağlayacağı avantajları detay penceresinde inceleyebilirsin.
          </p>
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
              <span style="font-size: 0.8rem; color: var(--muted);">Özellikleri incele</span>
              <button type="button" class="detail-link">Detayları Gör →</button>
            </div>
          </article>
          {% endfor %}
        </div>
      </div>
    </section>

    <section id="iletisim" class="block">
      <div class="container">
        <div class="section-head reveal">
          <span>İletişim</span>
          <h2>KOLAY Otomasyon İle Projeni Başlat</h2>
          <p>
            İster WhatsApp hattımızdan doğrudan yaz ister formu doldur; talebin veritabanına kaydedilsin.
          </p>
        </div>

        <div class="contact-wrap">
          <div class="contact-info reveal">
            <div class="wa-box">
              <div class="wa-head">
                <svg class="wp-icon-lg" style="color: #22c55e;"><use href="#icon-whatsapp"></use></svg>
                <strong>WhatsApp İletişim</strong>
              </div>
              <span style="color: #d1fae5; font-size: 0.88rem;">Aklındaki sistemi tek mesajla sorabilir, hızlı teklif alabilirsin.</span>
              <a href="https://wa.me/{{ wa_number }}?text={{ 'Merhaba KOLAY Otomasyon, işletmem için sistem hakkında bilgi almak istiyorum.' | urlencode }}" target="_blank" rel="noopener noreferrer" class="btn-wa" style="justify-content: center; margin-top: 4px;" aria-label="WhatsApp">
                <svg class="wp-icon"><use href="#icon-whatsapp"></use></svg>
                <span>WhatsApp Sohbetini Aç</span>
              </a>
            </div>

            <div class="info-item">
              <strong>İşletmeye Özel Kurulum</strong>
              <span>Hazır kalıplar yerine işletmenin günlük akışına birebir oturan sade arayüzler.</span>
            </div>

            <div class="info-item">
              <strong>Mobil, Web ve Masaüstü Uyum</strong>
              <span>Telefon, tablet, kasa bilgisayarı ve tarayıcıdan kesintisiz kullanım.</span>
            </div>
          </div>

          <form class="contact-form reveal" method="POST" action="{{ url_for('index') }}">
            {% if sent %}
            <div class="alert-ok">Talebin başarıyla alındı ve veritabanına kaydedildi!</div>
            {% endif %}

            <div class="row-2">
              <div>
                <label for="name">Ad Soyad / İşletme Adı</label>
                <input id="name" type="text" name="name" placeholder="Örn: Yılmaz Kafe / Mertcan" required />
              </div>
              <div>
                <label for="phone">Telefon veya İletişim</label>
                <input id="phone" type="text" name="phone" placeholder="05xx xxx xx xx" required />
              </div>
            </div>

            <div>
              <label for="service">İlgilendiğin Sistem</label>
              <select id="service" name="service">
                {% for srv in services %}
                <option value="{{ srv.tag }} - {{ srv.title }}">{{ srv.tag }} — {{ srv.title }}</option>
                {% endfor %}
                <option value="Özel Otomasyon / Diğer">Özel Otomasyon / Diğer Sistem Talebi</option>
              </select>
            </div>

            <div>
              <label for="message">Detay / Not</label>
              <textarea id="message" name="message" rows="4" placeholder="İşletmeni ve istediğin özellikleri kısaca yaz..." required></textarea>
            </div>

            <button type="submit" class="submit-btn">Talebi Gönder</button>
          </form>
        </div>
      </div>
    </section>
  </main>

  <footer>
    <div class="container" style="display: contents;">
      <span>© 2026 KOLAY Otomasyon ve Web Sistemleri</span>
      <span><a href="#anasayfa">Anasayfa</a> • <a href="#canli-demo">Canlı Demo</a> • <a href="#hizmetler">Hizmetler</a> • <a href="#iletisim">İletişim</a> • <a href="{{ url_for('panel') }}">Yönetim Girişi</a></span>
    </div>
  </footer>

  <div id="serviceModal" class="modal-backdrop" onclick="closeModalOnBackdrop(event)">
    <div class="modal-box" role="dialog" aria-modal="true">
      <div class="modal-top">
        <span id="modalTag" class="card-tag" style="margin-bottom: 0;">Hizmet</span>
        <button type="button" class="modal-close" onclick="closeServiceModal()" aria-label="Kapat">✕</button>
      </div>
      <img id="modalImg" src="" alt="" class="modal-img" onerror="this.style.display='none'" />
      <h3 id="modalTitle">Sistem Başlığı</h3>
      <p id="modalDesc" class="modal-desc"></p>
      <ul id="modalFeatures" class="modal-list"></ul>
      <div class="modal-actions">
        <button type="button" class="btn-secondary" onclick="closeServiceModal()">Kapat</button>
        <a id="modalWaBtn" href="https://wa.me/{{ wa_number }}" target="_blank" rel="noopener noreferrer" class="btn-wa" aria-label="WhatsApp">
          <svg class="wp-icon"><use href="#icon-whatsapp"></use></svg>
          <span>WhatsApp</span>
        </a>
        <button type="button" class="btn-primary" onclick="selectServiceAndScroll()">Formda Seç ve Teklif Al</button>
      </div>
    </div>
  </div>

  <script>
    const SERVICES = {{ services | tojson }};
    const WA_NUMBER = "{{ wa_number }}";
    let activeServiceOption = "";
    let currentDemoId = "mobil-otomasyon";

    const sim = {
      mobil: {
        courier: "Kurye #04 • Ahmet Demir",
        status: "Teslimat Yolunda",
        eta: "8 dk",
        done: 14,
        total: 20,
        activeStaff: 18,
        totalStaff: 24,
        gpsPct: 98.6,
        filterActive: false,
        tasks: [
          { title: "Sipariş #8690123004567 — Kadıköy Dağıtım", sub: "12.5 km • Kurye #04 (Ahmet Demir)", badge: "YOLDA", cls: "pill", active: true },
          { title: "Sipariş #8690123007896 — Üsküdar Teslimatı", sub: "3.2 km • Kurye #02 (Mehmet K.)", badge: "TESLİM EDİLDİ", cls: "pill", active: false },
          { title: "Sipariş #8690123001234 — Beşiktaş Acil Servis", sub: "6.8 km • Kurye #07 (Ayşe Y.)", badge: "GECİKME", cls: "pill-amber", active: true },
        ],
        logs: [
          "[14:14:02] [GPS] Kurye #04 (Ahmet Demir) konumu güncellendi: Kadıköy (1.2 km kaldı)",
          "[14:14:15] [PUSH] Müşteri cihazına 'Kuryeniz yola çıktı - Tahmini 8 dk' bildirimi iletildi",
          "[14:14:25] [CHECK-IN] Saha rotası doğrulandı ve sunucu ile senkronize edildi"
        ]
      },
      web: {
        botTitle: "BOT #02 • Form Kaydı -> Telegram & WhatsApp",
        botSub: "Anlık Tetikleme: Form Kaydı • Webhook • Mesaj Botu",
        successRate: 99.6,
        leads: 4128,
        sent: 18450,
        queue: 14,
        onlyCrit: false,
        flows: [
          { title: "WhatsApp Otomatik Karşılama & Destek Botu", sub: "850 Mesaj / dk • Yanıt Süresi: 0.4s", badge: "BAŞARILI", cls: "pill", crit: false },
          { title: "Telegram Leads & Form Bildirim Botu", sub: "1,426 Bildirim • Yanıt Süresi: 0.2s", badge: "AKTİF", cls: "pill", crit: false },
          { title: "Webhook Tetikleyici — Sipariş & Ödeme", sub: "3 İstek Bekliyor • Yeniden Deneme Aktif", badge: "KRİTİK", cls: "pill-amber", crit: true },
        ],
        logs: [
          "[21:15:01] [WEBHOOK] Landing sayfasından yeni form kaydı alındı (ID: #4129)",
          "[21:15:03] [TELEGRAM] 'Satış Bildirimleri' grubuna anlık mesaj gönderildi (200 OK)",
          "[21:15:04] [WHATSAPP] Müşteriye otomatik karşılama ve özet mesajı iletildi"
        ]
      },
      masaustu: {
        barcode: "8690504012345",
        product: "Çaykur Rize Turist Çay 500g",
        sales: 1428,
        stockCount: 24850,
        critCount: 2,
        cartItems: 2,
        cartTotal: 130.0,
        onlyCrit: false,
        items: [
          { title: "Çaykur Rize Turist Çay 500g", sub: "Stok: 85 Adet • Birim: 85.00 TL • Barkod: 8690504012345", badge: "STOKTA", cls: "pill", crit: false },
          { title: "Eker Yoğurt 1kg", sub: "Stok: 3 Adet • Birim: 45.00 TL • Minimum Eşik: 10 Adet", badge: "KRİTİK", cls: "pill-amber", crit: true },
          { title: "Sırma Doğal Kaynak Suyu 1.5L", sub: "Stok: 0 Adet • Birim: 7.50 TL • Sipariş Önerilir", badge: "STOKTA YOK", cls: "pill-amber", crit: true },
        ],
        logs: [
          "[12:42:01] [BARCODE] COM3 barkod okuyucu hazır • 8690504012345 doğrulandı",
          "[12:42:08] [POS] Sepete ürün eklendi • Yerel kasa senkronizasyonu (12 ms)",
          "[12:42:15] [STOK] Kritik stok seviyesi izleniyor • Fiş yazıcı çevrimiçi"
        ]
      },
      kafe: {
        guests: 4,
        time: "19:30",
        guestName: "Murat Yılmaz",
        pending: 4,
        onlyFree: false,
        tables: [
          { name: "Masa 01", cap: 4, busy: true, info: "18:30 - 20:30 • Ahmet B." },
          { name: "Masa 02", cap: 2, busy: false, info: "Müsait (2 Kişilik)" },
          { name: "Masa 03", cap: 6, busy: true, info: "20:00 • Murat Y." },
          { name: "Masa 04", cap: 4, busy: true, info: "19:30 - 21:30 • Caner S." },
          { name: "Masa 05", cap: 2, busy: false, info: "Müsait (2 Kişilik)" },
          { name: "Masa 06", cap: 8, busy: false, info: "Müsait (8 Kişilik)" },
        ],
        logs: [
          "[18:45:02] [REZERVASYON] Masa planı güncellendi • 24 masa anlık izleniyor",
          "[18:45:19] [ONAY] Kişi sayısı ve saat bazlı masa uygunluğu kontrol edildi",
          "[18:45:40] [LOG] Günlük doluluk ve masa rezervasyon akışı senkronize"
        ]
      },
      berber: {
        client: "Murat Demir",
        service: "Saç Kesim & Sakal + Bakım (45 dk)",
        chair: "Koltuk 1 • Berber Serkan",
        elapsed: 35,
        totalMin: 45,
        selectedSlot: 1,
        slots: [
          { time: "13:00", booked: true, info: "Berber Serkan • Dolu" },
          { time: "13:45", booked: false, info: "Müsait Slot" },
          { time: "14:30", booked: false, info: "Müsait Slot" },
          { time: "15:15", booked: true, info: "Stilist Elif • Dolu" },
          { time: "16:00", booked: false, info: "Müsait Slot" },
          { time: "16:45", booked: false, info: "Müsait Slot" },
        ],
        logs: [
          "[13:40:12] [ZAMAN] Koltuk 1 işlem sayacı aktif (35 / 45 dk • Kalan: 10 dk)",
          "[13:41:20] [ÇAKIŞMA] Dolu saatlerde çifte randevu engelleme aktif",
          "[13:42:05] [TAKVİM] Usta/koltuk bazlı randevu çizelgesi güncel"
        ]
      },
      qr: {
        table: "Masa 05",
        ordersCount: 64,
        callsCount: 18,
        billsCount: 11,
        feed: [
          { title: "Masa 05 — 2x Türk Kahvesi, 1x Cheesecake", sub: "QR Menü Siparişi • Bar & Servis Ekranı", badge: "SERVİS HAZIR", cls: "pill" },
          { title: "Masa 08 — Garson Çağrı Talebi", sub: "Bölüm: Teras • Tek Dokunuş Bildirim", badge: "GARSON BEKLİYOR", cls: "pill-amber" },
          { title: "Masa 12 — Hesap İsteme Talebi", sub: "Masa QR • Kasa Ekranında Görüntülendi", badge: "HESAP HAZIRLANIYOR", cls: "pill-blue" },
        ],
        logs: [
          "[20:10:05] [QR-SCAN] Masa 05 QR menü oturumu tarayıcıdan başlatıldı",
          "[20:10:18] [GARSON] Tek dokunuşla garson çağrı ve hesap kanalı dinlemede",
          "[20:10:31] [KASA] Masa siparişleri anlık olarak kasa/bar ekranına aktarılıyor"
        ]
      }
    };

    function nowStr() {
      const d = new Date();
      return `[${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}:${String(d.getSeconds()).padStart(2,"0")}]`;
    }

    function pushSimLog(key, line) {
      sim[key].logs.unshift(`${nowStr()} ${line}`);
      sim[key].logs = sim[key].logs.slice(0, 6);
    }

    function renderSimLog(key) {
      return `
        <div>
          <div style="font-size: 0.74rem; font-weight: 800; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px;">Canlı Sistem Logları</div>
          <div class="sim-log">${sim[key].logs.map((x) => `<div>${x}</div>`).join("")}</div>
        </div>
      `;
    }

    function switchDemo(demoId, btnEl) {
      currentDemoId = demoId;
      document.querySelectorAll(".demo-tab").forEach((b) => b.classList.remove("active"));
      if (btnEl) btnEl.classList.add("active");

      const srv = SERVICES.find((s) => s.id === demoId) || SERVICES[0];
      document.getElementById("simWinLabel").textContent = `${srv.tag} — ${srv.title}`;
      document.getElementById("refShotTitle").textContent = `${srv.tag} — ${srv.title}`;
      const img = document.getElementById("refShotImg");
      if (img && srv.image) {
        img.style.display = "block";
        img.src = `/images/${srv.image}`;
      }

      const waMsg = encodeURIComponent(`Merhaba KOLAY Otomasyon, "${srv.tag} - ${srv.title}" simülasyonunu inceledim, bilgi almak istiyorum.`);
      document.getElementById("demoWaLink").href = `https://wa.me/${WA_NUMBER}?text=${waMsg}`;

      renderSim();
    }

    function toggleRefShot() {
      document.getElementById("refShotBox").classList.toggle("open");
    }

    function renderSim() {
      const head = document.getElementById("simHeaderStrip");
      const grid = document.getElementById("simGrid");
      const footer = document.getElementById("simFooterMeta");
      if (!head || !grid) return;

      if (currentDemoId === "mobil-otomasyon") {
        const m = sim.mobil;
        const pct = Math.min(100, Math.round((m.done / m.total) * 100));
        const rows = m.filterActive ? m.tasks.filter((t) => t.active) : m.tasks;

        head.innerHTML = `
          <div class="sim-title-group">
            <strong>Mobil Uygulama &amp; Saha Akışları</strong>
            <span class="sim-subpill">SAHA &amp; MOBİL KONTROL</span>
          </div>
          <div class="sim-kpi-row">
            <div class="sim-kpi ok"><span>Aktif Saha Ekibi</span><strong>${m.activeStaff} / ${m.totalStaff} Sahada</strong></div>
            <div class="sim-kpi"><span>Tamamlanan Görev</span><strong>${m.done} / ${m.total}</strong></div>
            <div class="sim-kpi warn"><span>Tahmini Varış</span><strong>${m.eta}</strong></div>
            <div class="sim-kpi ok"><span>GPS Sinyali</span><strong>%${m.gpsPct} Bağlı</strong></div>
          </div>
        `;

        grid.innerHTML = `
          <div class="sim-card">
            <div class="sim-card-head">
              <h3>01 • Aktif Saha Personeli &amp; Rota</h3>
              <span class="pill">${m.status}</span>
            </div>
            <div class="sim-highlight">
              <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;">
                <div>
                  <strong style="font-size: 1rem;">${m.courier}</strong>
                  <div style="font-size: 0.8rem; color: var(--muted);">Durum: ${m.status} • Tahmini Varış: ${m.eta}</div>
                </div>
                <span class="pill">GPS AKTİF</span>
              </div>
              <div class="sim-bar"><div class="sim-bar-fill" style="width: ${pct}%;"></div></div>
              <div style="display: flex; justify-content: space-between; font-size: 0.77rem; color: var(--muted);">
                <span>Günlük Rota İlerlemesi</span>
                <span>${pct}% (${m.done}/${m.total})</span>
              </div>
            </div>
            <div class="sim-3col">
              <div class="sim-mini-box"><small>Araç / Plaka</small><strong>34 ABC 123</strong></div>
              <div class="sim-mini-box"><small>Cihaz Pil</small><strong>%88 Şarjda</strong></div>
              <div class="sim-mini-box"><small>Bölge</small><strong>Kadıköy / İst</strong></div>
            </div>
            <div class="sim-filters">
              <button type="button" class="btn-sm" onclick="mobilSetStatus('Yola Çıktı', '12 dk')">Yola Çıktı</button>
              <button type="button" class="btn-sm" onclick="mobilSetStatus('Teslimat Yolunda', '8 dk')">Sonraki Durak</button>
              <button type="button" class="btn-amber-sm" onclick="mobilFinishTask()">Teslimat Tamamla</button>
              <button type="button" class="btn-amber-sm" onclick="mobilScenarioDelay()">Trafik Gecikme Senaryosu</button>
              <button type="button" class="btn-sm" onclick="mobilReset()">Senaryoyu Sıfırla</button>
            </div>
          </div>

          <div class="sim-card">
            <div class="sim-card-head">
              <h3>02 • Saha Görevleri, Teslimatlar &amp; Canlı Loglar</h3>
              <div class="sim-filters">
                <button type="button" class="sim-chip ${!m.filterActive ? "active" : ""}" onclick="mobilFilter(false)">Tümü (${m.tasks.length})</button>
                <button type="button" class="sim-chip ${m.filterActive ? "active" : ""}" onclick="mobilFilter(true)">Aktif (${m.tasks.filter(t => t.active).length})</button>
              </div>
            </div>
            <div class="sim-rows">
              ${rows.map((r) => `
                <div class="sim-row">
                  <div>
                    <strong>${r.title}</strong>
                    <small>${r.sub}</small>
                  </div>
                  <span class="${r.cls}">${r.badge}</span>
                </div>
              `).join("")}
            </div>
            ${renderSimLog("mobil")}
          </div>
        `;
        footer.textContent = `Saha Durumu: ${m.status} • Tamamlanan: ${m.done}/${m.total}`;
      } else if (currentDemoId === "web-otomasyon") {
        const w = sim.web;
        const rows = w.onlyCrit ? w.flows.filter((f) => f.crit) : w.flows;

        head.innerHTML = `
          <div class="sim-title-group">
            <strong>Web Otomasyon</strong>
            <span class="sim-subpill">Web Panelleri, Formlar &amp; Botlar</span>
          </div>
          <div class="sim-kpi-row">
            <div class="sim-kpi ok"><span>Başarı Oranı</span><strong>%${w.successRate.toFixed(1)} Kararlı</strong></div>
            <div class="sim-kpi"><span>Bugünkü Form Kaydı</span><strong>${w.leads.toLocaleString("tr-TR")}</strong></div>
            <div class="sim-kpi ok"><span>Gönderilen Bildirim</span><strong>${w.sent.toLocaleString("tr-TR")}</strong></div>
            <div class="sim-kpi warn"><span>Aktif Kuyruk</span><strong>${w.queue} İşlem</strong></div>
          </div>
        `;

        grid.innerHTML = `
          <div class="sim-card">
            <div class="sim-card-head">
              <h3>01 • Form ve Bot Otomasyon İstasyonu</h3>
              <span class="pill">BOTLAR AKTİF</span>
            </div>
            <div class="sim-highlight">
              <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;">
                <div>
                  <strong style="font-size: 0.98rem;">${w.botTitle}</strong>
                  <div style="font-size: 0.8rem; color: var(--muted);">${w.botSub}</div>
                </div>
                <span class="pill">%${w.successRate.toFixed(1)}</span>
              </div>
              <div class="sim-bar"><div class="sim-bar-fill" style="width: ${w.successRate}%;"></div></div>
            </div>
            <div class="sim-3col">
              <div class="sim-mini-box"><small>Telegram Bot</small><strong>Çevrimiçi</strong></div>
              <div class="sim-mini-box"><small>WhatsApp API</small><strong>Aktif (0.4s)</strong></div>
              <div class="sim-mini-box"><small>Web Form</small><strong>Dinlemede</strong></div>
            </div>
            <div class="sim-filters">
              <button type="button" class="btn-sm" onclick="webRun('Web Formu -> Telegram Bildirim Botu')">Form Tetikle</button>
              <button type="button" class="btn-sm" onclick="webRun('WhatsApp Otomatik Mesaj Gönderimi')">WhatsApp Bot Çalıştır</button>
              <button type="button" class="btn-amber-sm" onclick="webQueueStep()">Kuyruğu İşle</button>
              <button type="button" class="btn-amber-sm" onclick="webScenarioSpike()">Kritik Webhook Senaryosu</button>
              <button type="button" class="btn-sm" onclick="webFlushCritical()">Kritikleri Temizle</button>
            </div>
          </div>

          <div class="sim-card">
            <div class="sim-card-head">
              <h3>02 • Web Panelleri, Formlar &amp; Bot Görevleri</h3>
              <div class="sim-filters">
                <button type="button" class="sim-chip ${!w.onlyCrit ? "active" : ""}" onclick="webFilter(false)">Tüm Akışlar (${w.flows.length})</button>
                <button type="button" class="sim-chip ${w.onlyCrit ? "active" : ""}" onclick="webFilter(true)">Kritik (${w.flows.filter(f => f.crit).length})</button>
              </div>
            </div>
            <div class="sim-rows">
              ${rows.map((r) => `
                <div class="sim-row">
                  <div>
                    <strong>${r.title}</strong>
                    <small>${r.sub}</small>
                  </div>
                  <span class="${r.cls}">${r.badge}</span>
                </div>
              `).join("")}
            </div>
            ${renderSimLog("web")}
          </div>
        `;
        footer.textContent = `Başarı: %${w.successRate.toFixed(1)} • Bildirim: ${w.sent.toLocaleString("tr-TR")} • Kuyruk: ${w.queue}`;
      } else if (currentDemoId === "masaustu-otomasyon") {
        const d = sim.masaustu;
        const rows = d.onlyCrit ? d.items.filter((i) => i.crit) : d.items;

        head.innerHTML = `
          <div class="sim-title-group">
            <strong>Masaüstü Otomasyon</strong>
            <span class="sim-subpill">Kasa, Barkod &amp; Yerel Programlar</span>
          </div>
          <div class="sim-kpi-row">
            <div class="sim-kpi ok"><span>Toplam Satış / İşlem</span><strong>${d.sales.toLocaleString("tr-TR")}</strong></div>
            <div class="sim-kpi"><span>Toplam Stok</span><strong>${d.stockCount.toLocaleString("tr-TR")} Adet</strong></div>
            <div class="sim-kpi warn"><span>Kritik Stok</span><strong>${d.critCount} Ürün</strong></div>
            <div class="sim-kpi ok"><span>Yazıcı &amp; POS</span><strong>Çevrimiçi</strong></div>
          </div>
        `;

        grid.innerHTML = `
          <div class="sim-card">
            <div class="sim-card-head">
              <h3>01 • Barkod Okutma İstasyonu &amp; Kasa</h3>
              <span class="pill">OKUYUCU HAZIR</span>
            </div>
            <div class="sim-highlight">
              <div style="font-size: 0.75rem; color: var(--accent-bright); font-weight: 700;">SON OKUTULAN BARKOD</div>
              <div style="font-size: 1.32rem; font-weight: 800; letter-spacing: 0.08em;">${d.barcode}</div>
              <div style="font-size: 0.84rem; color: var(--muted);">Ürün: ${d.product}</div>
            </div>
            <div class="sim-row">
              <div>
                <strong>Aktif Kasa Sepeti (${d.cartItems} Kalem)</strong>
                <small>Fiş / Fatura yazdırmaya hazır</small>
              </div>
              <strong style="color: var(--accent-bright); font-size: 1rem;">${d.cartTotal.toFixed(2)} TL</strong>
            </div>
            <div class="sim-filters">
              <button type="button" class="btn-sm" onclick="posAdd('8690504012345', 'Çaykur Rize Turist Çay 500g', 85)">Barkod +85 TL</button>
              <button type="button" class="btn-sm" onclick="posAdd('8690504099112', 'Eker Yoğurt 1kg', 45)">Barkod +45 TL</button>
              <button type="button" class="btn-amber-sm" onclick="posFinish()">Satışı Tamamla</button>
              <button type="button" class="btn-sm" onclick="posRestock()">İrsaliye +50 Stok</button>
              <button type="button" class="btn-amber-sm" onclick="posClearCart()">Sepeti Temizle</button>
            </div>
          </div>

          <div class="sim-card">
            <div class="sim-card-head">
              <h3>02 • Ürün Envanteri, Kritik Stok &amp; Loglar</h3>
              <div class="sim-filters">
                <button type="button" class="sim-chip ${!d.onlyCrit ? "active" : ""}" onclick="posFilter(false)">Tüm Ürünler</button>
                <button type="button" class="sim-chip ${d.onlyCrit ? "active" : ""}" onclick="posFilter(true)">Kritik / Stokta Yok</button>
              </div>
            </div>
            <div class="sim-rows">
              ${rows.map((r) => `
                <div class="sim-row">
                  <div>
                    <strong>${r.title}</strong>
                    <small>${r.sub}</small>
                  </div>
                  <span class="${r.cls}">${r.badge}</span>
                </div>
              `).join("")}
            </div>
            ${renderSimLog("masaustu")}
          </div>
        `;
        footer.textContent = `Sepet: ${d.cartTotal.toFixed(2)} TL • Toplam Satış: ${d.sales.toLocaleString("tr-TR")}`;
      } else if (currentDemoId === "kafe-restoran-randevu") {
        const k = sim.kafe;
        const freeCount = k.tables.filter((t) => !t.busy).length;
        const shown = k.onlyFree ? k.tables.filter((t) => !t.busy) : k.tables;

        head.innerHTML = `
          <div class="sim-title-group">
            <strong>Kafe &amp; Restoran</strong>
            <span class="sim-subpill">Masa &amp; Kişi Bazlı Randevu Sistemi</span>
          </div>
          <div class="sim-kpi-row">
            <div class="sim-kpi"><span>Toplam Masa</span><strong>24 Masa (${24 - freeCount * 4} Dolu)</strong></div>
            <div class="sim-kpi ok"><span>Müsait Demo Masa</span><strong>${freeCount} / ${k.tables.length} Boş</strong></div>
            <div class="sim-kpi warn"><span>Onay Bekleyen</span><strong>${k.pending} Rezervasyon</strong></div>
            <div class="sim-kpi ok"><span>Anlık Doluluk</span><strong>%62 Aktif</strong></div>
          </div>
        `;

        grid.innerHTML = `
          <div class="sim-card">
            <div class="sim-card-head">
              <h3>01 • Yeni Masa &amp; Kişi Bazlı Randevu</h3>
              <span class="pill">SİSTEM ÇEVRİMİÇİ</span>
            </div>
            <div class="row-2">
              <div>
                <label>Kişi Sayısı</label>
                <div style="display: flex; gap: 8px; align-items: center;">
                  <button type="button" class="btn-secondary" style="padding: 7px 11px;" onclick="kafeStepGuests(-1)">-</button>
                  <strong style="font-size: 0.96rem;">${k.guests} Kişi</strong>
                  <button type="button" class="btn-secondary" style="padding: 7px 11px;" onclick="kafeStepGuests(1)">+</button>
                </div>
              </div>
              <div>
                <label>Saat Dilimi</label>
                <select onchange="kafeSetTime(this.value)">
                  <option value="19:30" ${k.time === "19:30" ? "selected" : ""}>19:30</option>
                  <option value="20:30" ${k.time === "20:30" ? "selected" : ""}>20:30</option>
                  <option value="21:30" ${k.time === "21:30" ? "selected" : ""}>21:30</option>
                </select>
              </div>
            </div>
            <div>
              <label>Misafir Adı</label>
              <input type="text" value="${k.guestName}" onchange="kafeSetGuest(this.value)" />
            </div>
            <div class="sim-filters">
              <button type="button" class="btn-primary" onclick="kafeReserve()">Uygun Boş Masaya Rezervasyon Ekle</button>
              <button type="button" class="btn-amber-sm" onclick="kafeVipScenario()">VIP Grup (6 Kişi) Senaryosu</button>
              <button type="button" class="btn-sm" onclick="kafeFreeAll()">Masaları Boşalt</button>
            </div>
          </div>

          <div class="sim-card">
            <div class="sim-card-head">
              <h3>02 • Canlı Masa Yerleşimi &amp; Saatlik Akış</h3>
              <div class="sim-filters">
                <button type="button" class="sim-chip ${!k.onlyFree ? "active" : ""}" onclick="kafeFilter(false)">Tüm Masalar</button>
                <button type="button" class="sim-chip ${k.onlyFree ? "active" : ""}" onclick="kafeFilter(true)">Boş Masalar (${freeCount})</button>
              </div>
            </div>
            <div class="table-grid">
              ${shown.map((t) => {
                const idx = k.tables.indexOf(t);
                return `
                  <button type="button" class="table-chip ${t.busy ? "busy" : "free"}" onclick="kafeToggleTable(${idx})">
                    <strong>${t.name} • ${t.cap} Kişi</strong>
                    <span>${t.busy ? "DOLU • " + t.info : "BOŞ • Tıkla Ayırt"}</span>
                  </button>
                `;
              }).join("")}
            </div>
            ${renderSimLog("kafe")}
          </div>
        `;
        footer.textContent = `Misafir: ${k.guestName} (${k.guests} Kişi • ${k.time}) • Boş Masa: ${freeCount}`;
      } else if (currentDemoId === "berber-kuafor-randevu") {
        const b = sim.berber;
        const pct = Math.min(100, Math.round((b.elapsed / b.totalMin) * 100));
        const activeSlot = b.slots[b.selectedSlot];

        head.innerHTML = `
          <div class="sim-title-group">
            <strong>Berber &amp; Kuaför</strong>
            <span class="sim-subpill">Salon Randevu &amp; Saat Yönetimi</span>
          </div>
          <div class="sim-kpi-row">
            <div class="sim-kpi"><span>Toplam Randevu</span><strong>48 Randevu</strong></div>
            <div class="sim-kpi ok"><span>Aktif Koltuk</span><strong>4 / 5 Dolu</strong></div>
            <div class="sim-kpi warn"><span>Çakışma Koruması</span><strong>AKTİF</strong></div>
            <div class="sim-kpi ok"><span>Salon Modu</span><strong>Gün Işığı POS</strong></div>
          </div>
        `;

        grid.innerHTML = `
          <div class="sim-card">
            <div class="sim-card-head">
              <h3>01 • Koltuk Süre Durumu &amp; Hızlı Randevu</h3>
              <span class="pill">SALON ÇEVRİMİÇİ</span>
            </div>
            <div class="sim-highlight">
              <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;">
                <div>
                  <strong>${b.client}</strong>
                  <div style="font-size: 0.8rem; color: var(--muted);">${b.service} • ${b.chair}</div>
                </div>
                <span class="pill">${b.elapsed} / ${b.totalMin} dk</span>
              </div>
              <div class="sim-bar"><div class="sim-bar-fill" style="width: ${pct}%;"></div></div>
            </div>
            <div class="sim-filters">
              <button type="button" class="btn-sm" onclick="berberStepMin(10)">+10 dk İşlem İlerlet</button>
              <button type="button" class="btn-amber-sm" onclick="berberConfirmSlot()">Seçili Saati (${activeSlot ? activeSlot.time : "-"}) Ayırt</button>
              <button type="button" class="btn-sm" onclick="berberReleaseSlot()">Seçili Saati Boşa Çıkar</button>
              <button type="button" class="btn-amber-sm" onclick="berberAddPackage()">+15 dk Bakım Paketi</button>
            </div>
          </div>

          <div class="sim-card">
            <div class="sim-card-head">
              <h3>02 • Saat Slotları, Çakışma Kontrolü &amp; Loglar</h3>
              <span class="pill-amber">Seçili: ${activeSlot ? activeSlot.time : "-"}</span>
            </div>
            <div class="slot-grid">
              ${b.slots.map((s, idx) => {
                const cls = s.booked ? "slot-btn booked" : (b.selectedSlot === idx ? "slot-btn selected" : "slot-btn");
                return `<button type="button" class="${cls}" onclick="berberPickSlot(${idx})">${s.time} ${s.booked ? "• Dolu" : ""}</button>`;
              }).join("")}
            </div>
            ${renderSimLog("berber")}
          </div>
        `;
        footer.textContent = `Koltuk Süresi: ${b.elapsed}/${b.totalMin} dk • Seçili Saat: ${activeSlot ? activeSlot.time : "-"}`;
      } else if (currentDemoId === "masa-qr-garson") {
        const q = sim.qr;

        head.innerHTML = `
          <div class="sim-title-group">
            <strong>Masa QR &amp; Garson</strong>
            <span class="sim-subpill">QR Sipariş &amp; Garson Çağır Sistemi</span>
          </div>
          <div class="sim-kpi-row">
            <div class="sim-kpi ok"><span>QR Sipariş</span><strong>${q.ordersCount} Adet</strong></div>
            <div class="sim-kpi warn"><span>Garson Çağrısı</span><strong>${q.callsCount} Çağrı</strong></div>
            <div class="sim-kpi"><span>Hesap Talebi</span><strong>${q.billsCount} Masa</strong></div>
            <div class="sim-kpi ok"><span>Aktif QR Masa</span><strong>${q.table}</strong></div>
          </div>
        `;

        grid.innerHTML = `
          <div class="sim-card">
            <div class="sim-card-head">
              <h3>01 • Müşteri QR Masa Konsolu</h3>
              <span class="pill">QR AKTİF</span>
            </div>
            <div>
              <label>Masa Seçimi</label>
              <select onchange="qrSetTable(this.value)">
                <option value="Masa 05" ${q.table === "Masa 05" ? "selected" : ""}>Masa 05 (Salon)</option>
                <option value="Masa 08" ${q.table === "Masa 08" ? "selected" : ""}>Masa 08 (Teras)</option>
                <option value="Masa 12" ${q.table === "Masa 12" ? "selected" : ""}>Masa 12 (Bahçe)</option>
              </select>
            </div>
            <div class="sim-filters">
              <button type="button" class="btn-amber-sm" onclick="qrAction('call', 'Garson Çağrı Talebi', 'Bölüm: Salon • Tek Dokunuş Bildirim')">Garson Çağır</button>
              <button type="button" class="btn-sm" onclick="qrAction('bill', 'Hesap İsteme Talebi', 'Masa QR • Kasa Ekranında Görüntülendi')">Hesap İste</button>
              <button type="button" class="btn-sm" onclick="qrAction('order', 'QR Menüden Yeni Sipariş Gönderildi', 'Mutfak & Bar Ekranına Düşürüldü')">Sipariş Gönder</button>
              <button type="button" class="btn-amber-sm" onclick="qrResolveTop()">Üst Çağrıyı Kapat</button>
            </div>
            <div class="sim-3col">
              <div class="sim-mini-box"><small>Uygulama</small><strong>Gerekmez</strong></div>
              <div class="sim-mini-box"><small>Bildirim</small><strong>Anlık Sesli</strong></div>
              <div class="sim-mini-box"><small>Masa Kodu</small><strong>QR-OK</strong></div>
            </div>
          </div>

          <div class="sim-card">
            <div class="sim-card-head">
              <h3>02 • Canlı Masa Sipariş &amp; Çağrı Akışı</h3>
              <span class="pill">ANLIK AKIŞ</span>
            </div>
            <div class="sim-rows">
              ${q.feed.map((f) => `
                <div class="sim-row">
                  <div>
                    <strong>${f.title}</strong>
                    <small>${f.sub}</small>
                  </div>
                  <span class="${f.cls}">${f.badge}</span>
                </div>
              `).join("")}
            </div>
            ${renderSimLog("qr")}
          </div>
        `;
        footer.textContent = `Aktif Masa: ${q.table} • QR Sipariş: ${q.ordersCount} • Garson Çağrısı: ${q.callsCount}`;
      }
    }

    function mobilSetStatus(st, eta) {
      sim.mobil.status = st;
      sim.mobil.eta = eta;
      pushSimLog("mobil", `[DURUM] ${sim.mobil.courier} -> '${st}' (Tahmini varış: ${eta})`);
      renderSim();
    }

    function mobilFinishTask() {
      if (sim.mobil.done < sim.mobil.total) sim.mobil.done += 1;
      sim.mobil.status = "Teslimat Tamamlandı";
      pushSimLog("mobil", `[DELIVERY] Teslimat onaylandı (${sim.mobil.done}/${sim.mobil.total})`);
      renderSim();
    }

    function mobilScenarioDelay() {
      sim.mobil.status = "Trafik Gecikmesi (Rota Güncellendi)";
      sim.mobil.eta = "16 dk";
      sim.mobil.gpsPct = 97.4;
      sim.mobil.tasks.unshift({
        title: `Sipariş #8690123009911 — Alternatif Sahil Rotası`,
        sub: "4.1 km • Kurye #04 (Ahmet Demir)",
        badge: "ROTA GÜNCELLENDİ",
        cls: "pill-amber",
        active: true
      });
      sim.mobil.tasks = sim.mobil.tasks.slice(0, 4);
      pushSimLog("mobil", `[SENARYO] Köprü trafiği algılandı; alternatif rota ve 16 dk ETA bildirimi gönderildi`);
      renderSim();
    }

    function mobilReset() {
      sim.mobil.status = "Teslimat Yolunda";
      sim.mobil.eta = "8 dk";
      sim.mobil.done = 14;
      sim.mobil.gpsPct = 98.6;
      pushSimLog("mobil", `[SİSTEM] Saha simülasyonu varsayılan duruma sıfırlandı`);
      renderSim();
    }

    function mobilFilter(actOnly) {
      sim.mobil.filterActive = actOnly;
      renderSim();
    }

    function webRun(label) {
      sim.web.leads += 1;
      sim.web.sent += 1;
      pushSimLog("web", `[BOT] ${label} çalıştırıldı • Toplam bildirim: ${sim.web.sent.toLocaleString("tr-TR")}`);
      renderSim();
    }

    function webQueueStep() {
      if (sim.web.queue > 0) sim.web.queue -= 1;
      pushSimLog("web", `[QUEUE] Bekleyen istek tamamlandı • Kalan kuyruk: ${sim.web.queue}`);
      renderSim();
    }

    function webScenarioSpike() {
      sim.web.queue += 6;
      sim.web.successRate = Math.max(95.0, Number((sim.web.successRate - 0.4).toFixed(1)));
      sim.web.flows.unshift({
        title: "Harici CRM Webhook — Yoğun Form Kuyruğu",
        sub: "6 Yeni İstek • Otomatik Tekrar Deneme Aktif",
        badge: "KRİTİK",
        cls: "pill-amber",
        crit: true
      });
      sim.web.flows = sim.web.flows.slice(0, 4);
      pushSimLog("web", `[SENARYO] Ani form yükü oluştu; kuyruk +6 arttı (${sim.web.queue} işlem)`);
      renderSim();
    }

    function webFlushCritical() {
      sim.web.flows = sim.web.flows.map((f) => f.crit ? { ...f, badge: "ÇÖZÜLDÜ", cls: "pill", crit: false } : f);
      sim.web.queue = 0;
      sim.web.successRate = 99.6;
      pushSimLog("web", `[AKSIYON] Kritik webhook kuyruğu temizlendi ve sistem %99.6 kararlılığa döndü`);
      renderSim();
    }

    function webFilter(critOnly) {
      sim.web.onlyCrit = critOnly;
      renderSim();
    }

    function posAdd(code, prod, price) {
      sim.masaustu.barcode = code;
      sim.masaustu.product = prod;
      sim.masaustu.cartItems += 1;
      sim.masaustu.cartTotal += price;
      pushSimLog("masaustu", `[READ] Barkod ${code} (${prod}) okutuldu • +${price.toFixed(2)} TL`);
      renderSim();
    }

    function posFinish() {
      if (sim.masaustu.cartTotal > 0) {
        sim.masaustu.sales += 1;
        pushSimLog("masaustu", `[FİŞ] ${sim.masaustu.cartTotal.toFixed(2)} TL satış tamamlandı ve stok güncellendi`);
        sim.masaustu.cartTotal = 0;
        sim.masaustu.cartItems = 0;
      } else {
        pushSimLog("masaustu", `[POS] Sepet boş • Yeni barkod okutulabilir`);
      }
      renderSim();
    }

    function posRestock() {
      sim.masaustu.stockCount += 50;
      sim.masaustu.critCount = Math.max(0, sim.masaustu.critCount - 1);
      pushSimLog("masaustu", `[İRSALİYE] Depoya +50 adet ürün girişi yapıldı • Toplam stok: ${sim.masaustu.stockCount.toLocaleString("tr-TR")}`);
      renderSim();
    }

    function posClearCart() {
      sim.masaustu.cartTotal = 0;
      sim.masaustu.cartItems = 0;
      pushSimLog("masaustu", `[POS] Aktif kasa sepeti temizlendi`);
      renderSim();
    }

    function posFilter(critOnly) {
      sim.masaustu.onlyCrit = critOnly;
      renderSim();
    }

    function kafeStepGuests(d) {
      const n = sim.kafe.guests + d;
      if (n >= 1 && n <= 10) {
        sim.kafe.guests = n;
        renderSim();
      }
    }

    function kafeSetTime(val) {
      sim.kafe.time = val;
      renderSim();
    }

    function kafeSetGuest(val) {
      sim.kafe.guestName = val.trim() || "Misafir";
      renderSim();
    }

    function kafeToggleTable(idx) {
      const t = sim.kafe.tables[idx];
      t.busy = !t.busy;
      t.info = t.busy ? `${sim.kafe.time} • ${sim.kafe.guestName}` : `Müsait (${t.cap} Kişilik)`;
      pushSimLog("kafe", `[MASA] ${t.name} -> '${t.busy ? "DOLU / REZERVE" : "BOŞ / MÜSAİT"}' olarak güncellendi`);
      renderSim();
    }

    function kafeReserve() {
      const idx = sim.kafe.tables.findIndex((t) => !t.busy && t.cap >= sim.kafe.guests);
      const target = idx !== -1 ? idx : sim.kafe.tables.findIndex((t) => !t.busy);
      if (target === -1) {
        pushSimLog("kafe", `[UYARI] Demo listesindeki tüm masalar dolu`);
        renderSim();
        return;
      }
      sim.kafe.tables[target].busy = true;
      sim.kafe.tables[target].info = `${sim.kafe.time} • ${sim.kafe.guestName} (${sim.kafe.guests} Kişi)`;
      pushSimLog("kafe", `[ONAY] ${sim.kafe.tables[target].name} (${sim.kafe.guestName}, ${sim.kafe.guests} kişi, ${sim.kafe.time}) ayrıldı`);
      renderSim();
    }

    function kafeVipScenario() {
      sim.kafe.guests = 6;
      sim.kafe.time = "20:30";
      sim.kafe.guestName = "VIP Grup (Zeynep K.)";
      kafeReserve();
    }

    function kafeFreeAll() {
      sim.kafe.tables.forEach((t) => {
        t.busy = false;
        t.info = `Müsait (${t.cap} Kişilik)`;
      });
      pushSimLog("kafe", `[SALON] Tüm demo masalar yeni seans için boşaltıldı`);
      renderSim();
    }

    function kafeFilter(freeOnly) {
      sim.kafe.onlyFree = freeOnly;
      renderSim();
    }

    function berberPickSlot(idx) {
      sim.berber.selectedSlot = idx;
      const s = sim.berber.slots[idx];
      if (s.booked) {
        pushSimLog("berber", `[ÇAKIŞMA] ${s.time} slotu dolu (${s.info}) • Başka saat seçin`);
      } else {
        pushSimLog("berber", `[SLOT] ${s.time} müsait saati seçildi`);
      }
      renderSim();
    }

    function berberStepMin(mins) {
      sim.berber.elapsed = (sim.berber.elapsed + mins) % (sim.berber.totalMin + 1);
      pushSimLog("berber", `[ZAMAN] Koltuk süresi: ${sim.berber.elapsed} / ${sim.berber.totalMin} dk`);
      renderSim();
    }

    function berberConfirmSlot() {
      const s = sim.berber.slots[sim.berber.selectedSlot];
      if (!s) return;
      if (s.booked) {
        pushSimLog("berber", `[ENGELLENDİ] ${s.time} saati dolu, çakışma önlendi`);
      } else {
        s.booked = true;
        s.info = "Randevu Onaylandı";
        pushSimLog("berber", `[RANDEVU] ${s.time} slotu için randevu kaydedildi`);
      }
      renderSim();
    }

    function berberReleaseSlot() {
      const s = sim.berber.slots[sim.berber.selectedSlot];
      if (!s) return;
      s.booked = false;
      s.info = "Müsait Slot";
      pushSimLog("berber", `[İPTAL] ${s.time} saati iptal edilip tekrar müsait duruma açıldı`);
      renderSim();
    }

    function berberAddPackage() {
      sim.berber.totalMin += 15;
      sim.berber.service = `Saç Kesim & Sakal + Keratin Bakım (${sim.berber.totalMin} dk)`;
      pushSimLog("berber", `[PAKET] +15 dk bakım eklendi • Yeni toplam süre: ${sim.berber.totalMin} dk`);
      renderSim();
    }

    function qrSetTable(val) {
      sim.qr.table = val;
      pushSimLog("qr", `[QR] Aktif masa ${val} olarak değiştirildi`);
      renderSim();
    }

    function qrAction(kind, label, sub) {
      if (kind === "call") sim.qr.callsCount += 1;
      if (kind === "bill") sim.qr.billsCount += 1;
      if (kind === "order") sim.qr.ordersCount += 1;
      sim.qr.feed.unshift({
        title: `${sim.qr.table} — ${label}`,
        sub: sub,
        badge: kind === "order" ? "SERVİS HAZIR" : (kind === "bill" ? "HESAP HAZIRLANIYOR" : "GARSON BEKLİYOR"),
        cls: kind === "order" ? "pill" : (kind === "bill" ? "pill-blue" : "pill-amber")
      });
      sim.qr.feed = sim.qr.feed.slice(0, 3);
      pushSimLog("qr", `[${sim.qr.table}] ${label}`);
      renderSim();
    }

    function qrResolveTop() {
      if (sim.qr.feed.length > 0) {
        const topTitle = sim.qr.feed[0].title;
        sim.qr.feed[0] = {
          ...sim.qr.feed[0],
          badge: "TAMAMLANDI",
          cls: "pill"
        };
        pushSimLog("qr", `[TAMAM] '${topTitle}' talebi personel tarafından kapatıldı`);
      }
      renderSim();
    }

    function applyDemoServiceToForm() {
      const srv = SERVICES.find((s) => s.id === currentDemoId);
      const selectEl = document.getElementById("service");
      if (srv && selectEl) {
        selectEl.value = `${srv.tag} - ${srv.title}`;
      }
      document.getElementById("iletisim").scrollIntoView({ behavior: "smooth" });
    }

    function openServiceModal(serviceId) {
      const item = SERVICES.find((s) => s.id === serviceId);
      if (!item) return;

      document.getElementById("modalTag").textContent = item.tag;
      document.getElementById("modalTitle").textContent = item.title;
      document.getElementById("modalDesc").textContent = item.details;

      const imgEl = document.getElementById("modalImg");
      if (item.image) {
        imgEl.style.display = "block";
        imgEl.src = `/images/${item.image}`;
        imgEl.alt = item.title;
      } else {
        imgEl.style.display = "none";
      }

      const listEl = document.getElementById("modalFeatures");
      listEl.innerHTML = "";
      item.features.forEach((feat) => {
        const li = document.createElement("li");
        li.textContent = feat;
        listEl.appendChild(li);
      });

      const waText = encodeURIComponent(`Merhaba KOLAY Otomasyon, "${item.tag} - ${item.title}" hakkında bilgi ve teklif almak istiyorum.`);
      document.getElementById("modalWaBtn").href = `https://wa.me/${WA_NUMBER}?text=${waText}`;

      activeServiceOption = `${item.tag} - ${item.title}`;
      document.getElementById("serviceModal").classList.add("open");
    }

    function closeServiceModal() {
      document.getElementById("serviceModal").classList.remove("open");
    }

    function closeModalOnBackdrop(e) {
      if (e.target.id === "serviceModal") {
        closeServiceModal();
      }
    }

    function selectServiceAndScroll() {
      const selectEl = document.getElementById("service");
      if (selectEl && activeServiceOption) {
        selectEl.value = activeServiceOption;
      }
      closeServiceModal();
      document.getElementById("iletisim").scrollIntoView({ behavior: "smooth" });
    }

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeServiceModal();
    });

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("visible");
          }
        });
      },
      { threshold: 0.12 }
    );

    document.querySelectorAll(".reveal").forEach((el) => observer.observe(el));

    window.addEventListener("load", () => {
      switchDemo("mobil-otomasyon", document.querySelector('.demo-tab[data-demo="mobil-otomasyon"]'));
      document.querySelectorAll(".reveal").forEach((el) => {
        const rect = el.getBoundingClientRect();
        if (rect.top < window.innerHeight * 0.95) {
          el.classList.add("visible");
        }
      });
    });
  </script>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Panel Girişi — KOLAY Otomasyon ve Web Sistemleri</title>
  <style>
    :root {
      --bg: #080d0b;
      --bg-soft: #0f1714;
      --card: #121d18;
      --text: #f8fafc;
      --muted: #9ca3af;
      --accent: #10b981;
      --accent-bright: #34d399;
      --accent-2: #f59e0b;
      --danger: #ef4444;
      --border: rgba(16, 185, 129, 0.22);
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: "Inter", system-ui, -apple-system, sans-serif;
    }

    body {
      min-height: 100vh;
      display: grid;
      place-items: center;
      background:
        radial-gradient(circle at 20% 20%, rgba(16, 185, 129, 0.14), transparent 40%),
        var(--bg);
      color: var(--text);
      padding: 20px;
    }

    .login-card {
      width: 100%;
      max-width: 410px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 28px;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
      display: grid;
      gap: 16px;
    }

    .login-card h1 {
      font-size: 1.35rem;
    }

    .login-card p {
      color: var(--muted);
      font-size: 0.9rem;
    }

    .err-box {
      padding: 11px 13px;
      border-radius: 10px;
      background: rgba(239, 68, 68, 0.14);
      border: 1px solid rgba(239, 68, 68, 0.38);
      color: #fca5a5;
      font-size: 0.88rem;
      font-weight: 600;
    }

    label {
      display: block;
      font-size: 0.85rem;
      color: #d1d5db;
      margin-bottom: 6px;
      font-weight: 600;
    }

    input {
      width: 100%;
      padding: 12px 14px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--bg-soft);
      color: var(--text);
      font-size: 0.95rem;
    }

    input:focus {
      outline: none;
      border-color: var(--accent);
    }

    .btn-login {
      width: 100%;
      padding: 12px 16px;
      border-radius: 11px;
      border: none;
      cursor: pointer;
      font-weight: 800;
      font-size: 0.95rem;
      color: #04130d;
      background: linear-gradient(135deg, var(--accent-bright), var(--accent-2));
    }

    .back-link {
      text-align: center;
      font-size: 0.88rem;
    }

    .back-link a {
      color: var(--accent-bright);
      text-decoration: none;
    }
  </style>
</head>
<body>
  <form class="login-card" method="POST" action="{{ url_for('login', next=next_url) }}">
    <div>
      <h1>KOLAY Otomasyon — Panel Girişi</h1>
      <p>Gelen talepleri yönetmek için yönetici bilgilerini gir.</p>
    </div>

    {% if error %}
    <div class="err-box">{{ error }}</div>
    {% endif %}

    <div>
      <label for="username">Kullanıcı Adı</label>
      <input id="username" type="text" name="username" autocomplete="username" required />
    </div>

    <div>
      <label for="password">Şifre</label>
      <input id="password" type="password" name="password" autocomplete="current-password" required />
    </div>

    <button type="submit" class="btn-login">Panele Giriş Yap</button>

    <div class="back-link">
      <a href="{{ url_for('index') }}">← Vitrin Sitesine Dön</a>
    </div>
  </form>
</body>
</html>
"""

PANEL_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Talep Yönetim Paneli — KOLAY Otomasyon ve Web Sistemleri</title>
  <style>
    :root {
      --bg: #080d0b;
      --bg-soft: #0f1714;
      --card: #121d18;
      --text: #f8fafc;
      --muted: #9ca3af;
      --accent: #10b981;
      --accent-bright: #34d399;
      --amber: #f59e0b;
      --danger: #ef4444;
      --border: rgba(16, 185, 129, 0.2);
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: "Inter", system-ui, -apple-system, sans-serif;
    }

    body {
      background: var(--bg);
      color: var(--text);
      padding: 24px 18px 48px;
      line-height: 1.55;
    }

    .container {
      max-width: 1120px;
      margin: 0 auto;
    }

    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 14px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 24px;
    }

    .topbar h1 {
      font-size: 1.45rem;
    }

    .topbar p {
      color: var(--muted);
      font-size: 0.9rem;
    }

    .top-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }

    .back-btn,
    .logout-btn {
      text-decoration: none;
      padding: 10px 16px;
      border-radius: 10px;
      font-weight: 700;
      font-size: 0.9rem;
      cursor: pointer;
    }

    .back-btn {
      background: rgba(16, 185, 129, 0.14);
      border: 1px solid rgba(16, 185, 129, 0.35);
      color: var(--accent-bright);
    }

    .logout-btn {
      background: rgba(239, 68, 68, 0.14);
      border: 1px solid rgba(239, 68, 68, 0.35);
      color: #fca5a5;
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }

    .stat-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px 18px;
    }

    .stat-card span {
      color: var(--muted);
      font-size: 0.82rem;
      display: block;
    }

    .stat-card strong {
      font-size: 1.65rem;
      color: var(--accent-bright);
    }

    .ticket-list {
      display: grid;
      gap: 14px;
    }

    .ticket-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 20px;
      display: grid;
      gap: 12px;
    }

    .ticket-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      flex-wrap: wrap;
      gap: 10px;
    }

    .ticket-title {
      font-size: 1.08rem;
      font-weight: 700;
    }

    .ticket-meta {
      color: var(--muted);
      font-size: 0.86rem;
      margin-top: 2px;
    }

    .status-badge {
      padding: 4px 11px;
      border-radius: 999px;
      font-size: 0.78rem;
      font-weight: 700;
    }

    .st-yeni {
      background: rgba(245, 158, 11, 0.16);
      color: #fcd34d;
      border: 1px solid rgba(245, 158, 11, 0.35);
    }

    .st-inceleniyor {
      background: rgba(56, 189, 248, 0.16);
      color: #7dd3fc;
      border: 1px solid rgba(56, 189, 248, 0.35);
    }

    .st-tamamlandi {
      background: rgba(16, 185, 129, 0.16);
      color: #6ee7b7;
      border: 1px solid rgba(16, 185, 129, 0.35);
    }

    .ticket-msg {
      background: var(--bg-soft);
      border: 1px solid rgba(255, 255, 255, 0.06);
      padding: 12px 14px;
      border-radius: 10px;
      color: #e5e7eb;
      font-size: 0.94rem;
      white-space: pre-wrap;
    }

    .ticket-actions {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
    }

    .status-form {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    select, button {
      padding: 8px 12px;
      border-radius: 9px;
      border: 1px solid var(--border);
      background: var(--bg-soft);
      color: var(--text);
      font-size: 0.86rem;
      cursor: pointer;
    }

    .btn-save {
      background: var(--accent);
      color: #04130d;
      font-weight: 700;
      border: none;
    }

    .btn-del {
      background: rgba(239, 68, 68, 0.14);
      border-color: rgba(239, 68, 68, 0.35);
      color: #fca5a5;
      font-weight: 600;
    }

    .empty {
      text-align: center;
      padding: 46px 20px;
      background: var(--card);
      border: 1px dashed var(--border);
      border-radius: 16px;
      color: var(--muted);
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="topbar">
      <div>
        <h1>KOLAY Otomasyon — Gelen Talepler Paneli</h1>
        <p>Veritabanı: <code>tickets.db</code> • Aktif oturum: <code>{{ admin_user }}</code></p>
      </div>
      <div class="top-actions">
        <a href="{{ url_for('index') }}" class="back-btn">← Vitrin Sitesine Dön</a>
        <form method="POST" action="{{ url_for('logout') }}" style="display: inline;">
          <button type="submit" class="logout-btn">Çıkış Yap</button>
        </form>
      </div>
    </div>

    <div class="stats">
      <div class="stat-card">
        <span>Toplam Talep</span>
        <strong>{{ tickets|length }}</strong>
      </div>
      <div class="stat-card">
        <span>Yeni Bekleyen</span>
        <strong style="color: #fbbf24;">{{ yeni_count }}</strong>
      </div>
      <div class="stat-card">
        <span>Tamamlanan</span>
        <strong>{{ tamam_count }}</strong>
      </div>
    </div>

    {% if tickets %}
    <div class="ticket-list">
      {% for t in tickets %}
      <div class="ticket-card">
        <div class="ticket-head">
          <div>
            <div class="ticket-title">{{ t.name }} — <span style="color: var(--accent-bright);">{{ t.service or 'Genel Talep' }}</span></div>
            <div class="ticket-meta">İletişim: {{ t.phone or '-' }} • Tarih: {{ t.created_at or 'Belirtilmedi' }}</div>
          </div>
          {% set st = t.status or 'Yeni' %}
          <span class="status-badge {% if st == 'Tamamlandı' %}st-tamamlandi{% elif st == 'İnceleniyor' %}st-inceleniyor{% else %}st-yeni{% endif %}">
            {{ st }}
          </span>
        </div>

        <div class="ticket-msg">{{ t.message }}</div>

        <div class="ticket-actions">
          <form class="status-form" method="POST" action="{{ url_for('update_ticket', ticket_id=t.id) }}">
            <select name="status">
              <option value="Yeni" {% if st == 'Yeni' %}selected{% endif %}>Yeni</option>
              <option value="İnceleniyor" {% if st == 'İnceleniyor' %}selected{% endif %}>İnceleniyor</option>
              <option value="Tamamlandı" {% if st == 'Tamamlandı' %}selected{% endif %}>Tamamlandı</option>
            </select>
            <button type="submit" class="btn-save">Durumu Güncelle</button>
          </form>

          <form method="POST" action="{{ url_for('delete_ticket', ticket_id=t.id) }}" onsubmit="return confirm('Bu talebi silmek istediğine emin misin?');">
            <button type="submit" class="btn-del">Talebi Sil</button>
          </form>
        </div>
      </div>
      {% endfor %}
    </div>
    {% else %}
    <div class="empty">Henüz kayıtlı bir talep bulunmuyor. Vitrin sayfasındaki iletişim formundan test kaydı oluşturabilirsin.</div>
    {% endif %}
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


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        service = request.form.get("service", "").strip()
        message = request.form.get("message", "").strip()
        if name and message:
            add_ticket(name, phone, service, message)
        return redirect(url_for("index", sent="1") + "#iletisim")

    sent = request.args.get("sent") == "1"
    return render_template_string(
        INDEX_HTML,
        services=SERVICES_DATA,
        sent=sent,
        wa_number=WHATSAPP_NUMBER,
    )


@app.route("/panel/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next") or url_for("panel")
    error = None

    if session.get("panel_auth"):
        return redirect(url_for("panel"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        target_next = request.form.get("next") or url_for("panel")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["panel_auth"] = True
            session["panel_user"] = username
            return redirect(target_next)
        error = "Kullanıcı adı veya şifre hatalı."

    return render_template_string(LOGIN_HTML, error=error, next_url=next_url)


@app.route("/panel/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/panel")
@login_required
def panel():
    tickets = load_tickets()
    yeni_count = sum(1 for t in tickets if (t.get("status") or "Yeni") == "Yeni")
    tamam_count = sum(1 for t in tickets if t.get("status") == "Tamamlandı")
    return render_template_string(
        PANEL_HTML,
        tickets=tickets,
        yeni_count=yeni_count,
        tamam_count=tamam_count,
        admin_user=session.get("panel_user", ADMIN_USERNAME),
    )


@app.route("/panel/update/<ticket_id>", methods=["POST"])
@login_required
def update_ticket(ticket_id):
    new_status = request.form.get("status", "Yeni").strip()
    if new_status not in {"Yeni", "İnceleniyor", "Tamamlandı"}:
        new_status = "Yeni"
    update_ticket_status(ticket_id, new_status)
    return redirect(url_for("panel"))


@app.route("/panel/delete/<ticket_id>", methods=["POST"])
@login_required
def delete_ticket(ticket_id):
    delete_ticket_by_id(ticket_id)
    return redirect(url_for("panel"))


if __name__ == "__main__":
    app.run(debug=True)