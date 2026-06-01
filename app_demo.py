"""
Prevención Marketing System - MODO DEMO
Incluye: campañas con imagen, bandeja de entrada para responder.
"""

import os, json, asyncio, random, base64, uuid
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import pandas as pd
from datetime import timezone
import pytz
TZ_AR = pytz.timezone('America/Argentina/Buenos_Aires')

def ar_now() -> str:
    """Devuelve la fecha/hora actual en Argentina como string ISO."""
    return datetime.now(TZ_AR).strftime("%Y-%m-%d %H:%M:%S")
import gspread
from google.oauth2.service_account import Credentials as GCredentials
import sqlite3
import uvicorn
import httpx
import random
import hashlib
import secrets
from datetime import datetime, timedelta
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends
from ai_agent import get_ai_response, generate_first_message, generate_case_summary, generate_reminder_message
from puente_digital import cargar_contacto_puente_digital
from apscheduler.schedulers.asyncio import AsyncIOScheduler

DB_PATH    = os.environ.get("DB_PATH", "/app/data/demo.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ─── TELEGRAM CONFIG ──────────────────────────────────────────────────────────
# Completar con tus datos reales (ver README para instrucciones)
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")   # Token del bot de @BotFather
TG_CHAT_ID   = os.getenv("TG_CHAT_ID", "")     # Chat ID de tu clienta
WA_WABA_ID   = os.getenv("WA_WABA_ID", "")
WA_TOKEN     = os.getenv("WA_TOKEN", "")
GOOGLE_SHEET_ID          = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "")
WA_PHONE_ID  = os.getenv("WA_PHONE_ID", "")

# ─── PUENTE DIGITAL CONFIG ────────────────────────────────────────────────────
PUENTE_USER     = os.getenv("PUENTE_USER", "")
PUENTE_PASSWORD = os.getenv("PUENTE_PASSWORD", "")
ANTHROPIC_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
IMAGES_DIR = "static_images"
os.makedirs(IMAGES_DIR, exist_ok=True)

app = FastAPI(title="Prevención Marketing System")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── DATABASE ──────────────────────────────────────────────────────────────────
_wal_initialized = False

def get_db():
    # timeout=20s para evitar "database is locked" bajo carga concurrente
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    # Habilitar WAL la primera vez (permite múltiples lectores + un escritor sin bloquearse mutuamente)
    global _wal_initialized
    if not _wal_initialized:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=20000")
            conn.commit()
            _wal_initialized = True
        except Exception as e:
            print(f"[DB PRAGMA] no se pudo configurar WAL: {e}", flush=True)
    else:
        try:
            conn.execute("PRAGMA busy_timeout=20000")
        except: pass
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'asesor',
            asesor_id INTEGER,
            nombre TEXT NOT NULL,
            telegram_chat_id TEXT,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT (datetime('now','-3 hours')),
            FOREIGN KEY (asesor_id) REFERENCES asesores(id)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT (datetime('now','-3 hours')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            total INTEGER DEFAULT 0,
            inserted INTEGER DEFAULT 0,
            skipped INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT (datetime('now','-3 hours'))
        );
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id INTEGER,
            name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            extra_data TEXT,
            created_at TIMESTAMP DEFAULT (datetime('now','-3 hours')),
            FOREIGN KEY (import_id) REFERENCES imports(id)
        );
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            message_template TEXT NOT NULL,
            image_path TEXT,
            status TEXT DEFAULT 'draft',
            total_contacts INTEGER DEFAULT 0,
            sent INTEGER DEFAULT 0,
            delivered INTEGER DEFAULT 0,
            read_count INTEGER DEFAULT 0,
            replied INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT (datetime('now','-3 hours'))
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER,
            contact_id INTEGER,
            wa_message_id TEXT UNIQUE,
            phone TEXT NOT NULL,
            name TEXT NOT NULL,
            message_text TEXT,
            image_path TEXT,
            status TEXT DEFAULT 'pending',
            sent_at TIMESTAMP,
            delivered_at TIMESTAMP,
            read_at TIMESTAMP,
            replied_at TIMESTAMP,
            reply_text TEXT,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
            FOREIGN KEY (contact_id) REFERENCES contacts(id)
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            contact_name TEXT,
            contact_phone TEXT,
            message TEXT,
            campaign_id INTEGER,
            created_at TIMESTAMP DEFAULT (datetime('now','-3 hours')),
            read INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_name TEXT NOT NULL,
            contact_phone TEXT NOT NULL,
            campaign_id INTEGER,
            last_message TEXT,
            last_message_at TIMESTAMP,
            unread INTEGER DEFAULT 0,
            UNIQUE(contact_phone)
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            direction TEXT NOT NULL,
            body TEXT,
            image_path TEXT,
            created_at TIMESTAMP DEFAULT (datetime('now','-3 hours')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_name TEXT NOT NULL,
            contact_phone TEXT NOT NULL,
            campaign_id INTEGER,
            dni TEXT,
            localidad TEXT,
            codigo_area TEXT,
            celular TEXT,
            codigo_postal TEXT,
            email TEXT,
            asesor_id INTEGER,
            info_salud TEXT,
            puente_status TEXT DEFAULT 'pending',
            puente_message TEXT,
            lead_status TEXT DEFAULT 'active',
            qualified_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT (datetime('now','-3 hours')),
            FOREIGN KEY (asesor_id) REFERENCES asesores(id)
        );
        CREATE TABLE IF NOT EXISTS asesores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            email TEXT,
            telegram_chat_id TEXT,
            porcentaje INTEGER DEFAULT 0,
            leads_asignados INTEGER DEFAULT 0,
            activo INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS ai_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_phone TEXT NOT NULL UNIQUE,
            contact_name TEXT NOT NULL,
            campaign_id INTEGER,
            history TEXT DEFAULT '[]',
            dni TEXT,
            localidad TEXT,
            celular TEXT,
            codigo_area TEXT,
            codigo_postal TEXT,
            qualified INTEGER DEFAULT 0,
            conversation_complete INTEGER DEFAULT 0,
            post_localidad TEXT,
            post_situacion_laboral TEXT,
            post_cobertura_actual TEXT,
            post_punto_dolor TEXT,
            post_info_salud TEXT,
            qualified_at TIMESTAMP,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT (datetime('now','-3 hours')),
            updated_at TIMESTAMP DEFAULT (datetime('now','-3 hours'))
        );
    """)
    conn.commit()

    # ─── MIGRACIONES para DBs existentes ─────────────────────────────
    migrations = [
        ("ai_conversations", "conversation_complete", "INTEGER DEFAULT 0"),
        ("ai_conversations", "post_localidad", "TEXT"),
        ("ai_conversations", "post_situacion_laboral", "TEXT"),
        ("ai_conversations", "post_cobertura_actual", "TEXT"),
        ("ai_conversations", "post_punto_dolor", "TEXT"),
        ("leads", "lead_status", "TEXT DEFAULT 'active'"),
        ("leads", "clasificacion", "TEXT DEFAULT 'En gestión'"),
        ("leads", "recordatorio_fecha", "TEXT"),
        ("leads", "recordatorio_notificado", "INTEGER DEFAULT 0"),
        ("leads", "productor_id", "INTEGER"),
        ("asesores", "puente_user", "TEXT"),
        ("asesores", "puente_password", "TEXT"),
        ("ai_conversations", "post_info_salud", "TEXT"),
        ("ai_conversations", "qualified_at", "TIMESTAMP"),
        ("leads", "info_salud", "TEXT"),
        ("leads", "gestion_notificada", "INTEGER DEFAULT 0"),
        ("leads", "qualified_at", "TIMESTAMP"),
        ("asesores", "telegram_chat_id", "TEXT"),
        ("asesores", "rol", "TEXT DEFAULT 'asesor'"),
        ("asesores", "telefono", "TEXT"),
        ("users", "telegram_chat_id", "TEXT"),
        ("ai_conversations", "dni_refused", "INTEGER DEFAULT 0"),
        ("ai_conversations", "asesor_id", "INTEGER"),
        ("ai_conversations", "lead_id", "INTEGER"),
        ("ai_conversations", "timeout_summary_sent", "INTEGER DEFAULT 0"),
        ("ai_conversations", "last_user_message_at", "TIMESTAMP"),
    ]
    for table, column, col_type in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            conn.commit()
            print(f"Migración: {table}.{column} agregado", flush=True)
        except Exception:
            pass  # Ya existe

    # ─── Quick Replies ────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quick_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            label TEXT NOT NULL,
            message TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT (datetime('now','-3 hours'))
        )
    """)
    conn.commit()
    # Seed defaults si la tabla está vacía
    qr_count = conn.execute("SELECT COUNT(*) FROM quick_replies").fetchone()[0]
    if qr_count == 0:
        defaults = [
            ("Saludos", "Saludo inicial", "Hola! ¿Cómo estás? Soy tu asesor de Prevención Salud. Estoy para ayudarte con cualquier consulta que tengas 😊", 1),
            ("Saludos", "Seguimiento", "Hola! ¿Pudiste ver la información que te envié? Cualquier duda que tengas me avisás", 2),
            ("Saludos", "Agradecimiento", "Muchas gracias por tu tiempo! Cualquier cosa que necesites no dudes en escribirme", 3),
            ("Comercial", "Pedir datos para cotizar", "Para armarte la mejor propuesta necesitaría saber cuántas personas serían en el grupo familiar y las edades de cada uno. ¿Me los pasás?", 1),
            ("Comercial", "Enviar cotización", "Te paso la cotización que armé para vos. Revisala tranquilo/a y cualquier duda me decís!", 2),
            ("Comercial", "Beneficios del plan", "Con este plan tenés cobertura nacional, más de 3.500 prestadores, farmacia con descuento y mucho más. ¿Querés que te cuente los detalles?", 3),
            ("Comercial", "Formas de pago", "Las formas de pago disponibles son débito automático, tarjeta de crédito o transferencia bancaria. ¿Cuál te queda más cómoda?", 4),
            ("Comercial", "Cerrar venta", "¡Genial! Para avanzar con la afiliación necesitaría que me envíes foto del DNI de frente y dorso de cada integrante. ¿Podés enviármelos?", 5),
        ]
        conn.executemany("INSERT INTO quick_replies (category,label,message,sort_order) VALUES (?,?,?,?)", defaults)
        conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    if count == 0:
        demo_contacts = [
            ("María García","+54 9 11 2345-6789"),("Carlos Rodríguez","+54 9 11 3456-7890"),
            ("Ana Martínez","+54 9 11 4567-8901"),("Luis Fernández","+54 9 11 5678-9012"),
            ("Laura López","+54 9 11 6789-0123"),("Diego González","+54 9 11 7890-1234"),
            ("Sofía Pérez","+54 9 11 8901-2345"),("Martín Sánchez","+54 9 11 9012-3456"),
            ("Valentina Torres","+54 9 11 1234-5678"),("Facundo Díaz","+54 9 11 2345-6780"),
            ("Camila Ruiz","+54 9 11 3456-7891"),("Nicolás Vargas","+54 9 11 4567-8902"),
            ("Lucía Castro","+54 9 11 5678-9013"),("Sebastián Morales","+54 9 11 6789-0124"),
            ("Florencia Herrera","+54 9 11 7890-1235"),("Matías Jiménez","+54 9 11 8901-2346"),
            ("Agustina Silva","+54 9 11 9012-3457"),("Tomás Romero","+54 9 11 1234-5679"),
            ("Micaela Navarro","+54 9 11 2345-6781"),("Gonzalo Reyes","+54 9 11 3456-7892"),
            ("Antonella Molina","+54 9 11 4567-8903"),("Ramiro Ortiz","+54 9 11 5678-9014"),
            ("Julieta Álvarez","+54 9 11 6789-0125"),("Ignacio Medina","+54 9 11 7890-1236"),
            ("Rocío Gómez","+54 9 11 8901-2347"),("Esteban Rojas","+54 9 11 9012-3458"),
            ("Milagros Suárez","+54 9 11 1111-2222"),("Pablo Gutiérrez","+54 9 11 2222-3333"),
            ("Natalia Acosta","+54 9 11 3333-4444"),("Leandro Ramos","+54 9 11 4444-5555"),
        ]
        for name, phone in demo_contacts:
            conn.execute("INSERT OR IGNORE INTO contacts (name,phone,import_id) VALUES (?,?,NULL)", (name, phone))
        conn.commit()
    conn.close()

init_db()

# Crear usuario admin por defecto si no existe
def ensure_admin():
    conn = get_db()
    admin = conn.execute("SELECT id FROM users WHERE role='admin'").fetchone()
    if not admin:
        pw_hash = hashlib.sha256("admin123".encode()).hexdigest()
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role, nombre) VALUES (?,?,?,?)",
            ("admin", pw_hash, "admin", "Administrador")
        )
        conn.commit()
        print("\n✅ Usuario admin creado — usuario: admin / contraseña: admin123")
        print("   ⚠️  Cambiá la contraseña desde el panel después del primer login\n")
    conn.close()

ensure_admin()

def run_migrations():
    conn = get_db()
    for sql in [
        "ALTER TABLE ai_conversations ADD COLUMN codigo_postal TEXT",
        "ALTER TABLE leads ADD COLUMN codigo_postal TEXT",
        "ALTER TABLE chat_messages ADD COLUMN media_type TEXT",
        "ALTER TABLE chat_messages ADD COLUMN media_url TEXT",
        "ALTER TABLE chat_messages ADD COLUMN media_name TEXT",
        "ALTER TABLE campaigns ADD COLUMN template_lang TEXT DEFAULT 'es_AR'",
        "ALTER TABLE campaigns ADD COLUMN header_type TEXT",
        "ALTER TABLE campaigns ADD COLUMN header_example TEXT",
    ]:
        try:
            conn.execute(sql); conn.commit()
        except: pass
    conn.close()

run_migrations()

# Cargar config de Telegram si existe
if os.path.exists("/app/data/.env_telegram"):
    with open("/app/data/.env_telegram") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                if k == "TG_BOT_TOKEN": TG_BOT_TOKEN = v
                if k == "TG_CHAT_ID": TG_CHAT_ID = v


# Cargar config de Telegram si existe
if os.path.exists("/app/data/.env_telegram"):
    with open("/app/data/.env_telegram") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                if k == "TG_BOT_TOKEN": TG_BOT_TOKEN = v
                if k == "TG_CHAT_ID": TG_CHAT_ID = v

# ─── MODELS ────────────────────────────────────────────────────────────────────
class CampaignCreate(BaseModel):
    name: str
    contact_ids: List[int]
    message_template: str = ""
    template_name: str = ""
    template_lang: str = "es_AR"
    header_type: Optional[str] = None
    header_example: Optional[str] = None
    image_path: Optional[str] = None

class SendReply(BaseModel):
    conversation_id: int
    body: str

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
async def send_telegram(message: str, exclude: set = None):
    """Envía SOLO al chat global (TG_CHAT_ID).
    Para enviar a admins usá send_telegram_to_admins() explícito."""
    if not TG_BOT_TOKEN:
        print(f"[TELEGRAM no configurado] {message}", file=__import__('sys').stderr, flush=True)
        return
    sent_to = set(exclude or [])
    if TG_CHAT_ID and TG_CHAT_ID not in sent_to:
        await send_telegram_to(TG_CHAT_ID, message)

async def send_telegram_to_admins(message: str, exclude: set = None):
    """Envía a todos los admins con telegram_chat_id, sin duplicar."""
    if not TG_BOT_TOKEN:
        return
    sent_to = set(exclude or [])
    try:
        conn = get_db()
        admins = conn.execute(
            "SELECT telegram_chat_id FROM users WHERE role='admin' AND telegram_chat_id IS NOT NULL AND telegram_chat_id != ''"
        ).fetchall()
        conn.close()
        for admin in admins:
            chat_id = admin["telegram_chat_id"]
            if chat_id and chat_id not in sent_to:
                await send_telegram_to(chat_id, message)
                sent_to.add(chat_id)
    except Exception as e:
        print(f"Error enviando a admins: {e}", file=__import__('sys').stderr, flush=True)

async def send_telegram_to(chat_id: str, message: str):
    """Envía a un chat_id específico usando el bot global."""
    import sys
    if not TG_BOT_TOKEN or not chat_id:
        print(f"[TELEGRAM sin token/chat_id] token={'SI' if TG_BOT_TOKEN else 'NO'} chat_id={chat_id}", file=sys.stderr, flush=True)
        return
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"})
            if resp.status_code != 200:
                print(f"[TELEGRAM ERROR] chat_id={chat_id} status={resp.status_code} body={resp.text}", file=sys.stderr, flush=True)
            else:
                print(f"[TELEGRAM OK] chat_id={chat_id}", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[TELEGRAM EXCEPTION] chat_id={chat_id} error={e}", file=sys.stderr, flush=True)

# ─── ASESOR ASSIGNMENT ────────────────────────────────────────────────────────
def assign_asesor(conn) -> dict | None:
    """Asigna un asesor basado en porcentajes configurados."""
    asesores = conn.execute(
        "SELECT * FROM asesores WHERE activo=1 AND porcentaje>0"
    ).fetchall()
    if not asesores:
        return None
    total_pct = sum(a["porcentaje"] for a in asesores)
    if total_pct == 0:
        return None
    # Weighted random selection
    r = random.randint(1, total_pct)
    cumulative = 0
    for a in asesores:
        cumulative += a["porcentaje"]
        if r <= cumulative:
            return dict(a)
    return dict(asesores[-1])

async def notify_asesor_new_lead(asesor: dict, lead_data: dict):
    """Notifica al asesor y a todos los usuarios vinculados vía Telegram."""
    msg = (
        f"🎯 <b>Nuevo lead asignado — Prevención Salud</b>\n\n"
        f"👤 <b>{lead_data['contact_name']}</b>\n"
        f"📱 {lead_data['contact_phone']}\n"
        f"🪪 DNI: {lead_data.get('dni','—')}\n"
        f"📍 Localidad: {lead_data.get('localidad','—')}\n"
        f"📞 Celular: {lead_data.get('codigo_area','')} {lead_data.get('celular','—')}\n\n"
        f"👉 Cargado en Puente Digital: {'✅' if lead_data.get('puente_status')=='success' else '⏳ pendiente'}"
    )
    sent_to = set()
    # 1. Enviar al asesor directamente (tabla asesores)
    asesor_tg = asesor.get("telegram_chat_id")
    if asesor_tg and TG_BOT_TOKEN:
        try:
            await send_telegram_to(asesor_tg, msg)
            sent_to.add(asesor_tg)
        except Exception as e:
            print(f"Error notif asesor: {e}", file=__import__('sys').stderr, flush=True)
    # 2. Enviar a todos los usuarios vinculados a este asesor (tabla users)
    asesor_id = asesor.get("id")
    if asesor_id and TG_BOT_TOKEN:
        try:
            conn = get_db()
            users = conn.execute(
                "SELECT telegram_chat_id FROM users WHERE asesor_id=? AND telegram_chat_id IS NOT NULL AND telegram_chat_id != ''",
                (asesor_id,)
            ).fetchall()
            conn.close()
            for u in users:
                if u["telegram_chat_id"] not in sent_to:
                    await send_telegram_to(u["telegram_chat_id"], msg)
                    sent_to.add(u["telegram_chat_id"])
        except Exception as e:
            print(f"Error notif usuarios vinculados: {e}", file=__import__('sys').stderr, flush=True)

# ─── AI CONVERSATION HANDLER ──────────────────────────────────────────────────
async def handle_ai_reply(contact_phone: str, contact_name: str, incoming_message: str, campaign_id: int = None):
    """Procesa respuesta entrante con IA — flujo:
    1. Primer mensaje → asignar asesor + crear lead parcial + notificar
    2. Fase 1 (pre): pedir DNI. Si lo da → cargar Puente. Si lo rechaza → pasar a fase 2.
    3. Fase 2 (post): relevar localidad, situación, cobertura, salud.
    4. Al completar → resumen + Telegram al asesor."""
    conn = get_db()
    now = datetime.now(TZ_AR)
    now_str = now.isoformat()

    # Obtener o crear conversación de IA
    ai_conv = conn.execute(
        "SELECT * FROM ai_conversations WHERE contact_phone=?", (contact_phone,)
    ).fetchone()

    if ai_conv:
        history = json.loads(ai_conv["history"])
        already_have = {}
        if ai_conv["dni"]: already_have["dni"] = ai_conv["dni"]
    else:
        history = []
        already_have = {}
        conn.execute(
            "INSERT OR IGNORE INTO ai_conversations (contact_phone, contact_name, campaign_id) VALUES (?,?,?)",
            (contact_phone, contact_name, campaign_id)
        )
        conn.commit()
        ai_conv = conn.execute(
            "SELECT * FROM ai_conversations WHERE contact_phone=?", (contact_phone,)
        ).fetchone()

    is_complete = ai_conv and ai_conv["conversation_complete"] == 1
    if is_complete:
        # Conversación ya cerrada — no respondemos más
        conn.close()
        return None

    # Helpers para columnas que pueden no existir tras migraciones recientes
    def _col(row, name, default=None):
        try:
            return row[name] if row and name in row.keys() else default
        except Exception:
            try: return row[name]
            except Exception: return default

    is_qualified = ai_conv and ai_conv["qualified"] == 1
    dni_refused = bool(_col(ai_conv, "dni_refused", 0))
    lead_id_existing = _col(ai_conv, "lead_id", None)

    # ─── PASO 1: Asignación temprana del asesor (al PRIMER mensaje del cliente) ───
    if not lead_id_existing:
        new_lead, asesor_assigned = assign_asesor_for_phone(conn, contact_phone, contact_name, campaign_id)
        if new_lead:
            conn.execute(
                "UPDATE ai_conversations SET asesor_id=?, lead_id=? WHERE contact_phone=?",
                (new_lead.get("asesor_id"), new_lead["id"], contact_phone)
            )
            conn.commit()
            # Notificar asesor en background
            if asesor_assigned:
                import asyncio as _aio
                _aio.create_task(notify_lead_assigned(asesor_assigned, contact_name, contact_phone))

    # Agregar mensaje entrante al historial
    history.append({"role": "user", "content": incoming_message})

    # Marcar momento del último mensaje del usuario (para timeout)
    conn.execute(
        "UPDATE ai_conversations SET last_user_message_at=? WHERE contact_phone=?",
        (now_str, contact_phone)
    )
    conn.commit()

    # ─── Determinar fase: pre (sin DNI y no rechazó) o post ───
    in_post_phase = is_qualified or dni_refused

    if not in_post_phase:
        # ─── FASE 1: Obtener DNI ─────────────────────────────────────
        result = await get_ai_response(history, contact_name, contact_phone, already_have, phase="pre", campaign_id=campaign_id)

        new_data = {**already_have, **result.get("extracted", {})}
        got_dni_now = bool(new_data.get("dni"))
        dni_refused_now = bool(result.get("dni_refused"))

        # Si recién obtuvimos DNI → pasamos a fase 2 (qualified=1) y disparamos carga Puente en bg
        # Si rechazó → marcamos dni_refused=1 y también pasamos a fase 2 (sin DNI)
        new_qualified = 1 if got_dni_now else 0
        new_refused = 1 if dni_refused_now else 0

        if got_dni_now:
            # DNI recién obtenido → saltar directo a fase 2 sin enviar el reply de fase 1.
            # Evita mensajes de transición incorrectos ("te paso los números", etc.)
            post_result = await get_ai_response(
                history, contact_name, contact_phone, new_data,
                phase="post", post_data={}
            )
            reply_text = post_result["reply"]
        else:
            reply_text = result["reply"]

        history.append({"role": "assistant", "content": reply_text})

        conn.execute("""
            UPDATE ai_conversations SET
                history=?, dni=?, qualified=?, qualified_at=?,
                dni_refused=?, updated_at=?
            WHERE contact_phone=?""",
            (
                json.dumps(history),
                new_data.get("dni"),
                new_qualified,
                now_str if got_dni_now else (ai_conv["qualified_at"] if ai_conv else None),
                new_refused,
                now_str,
                contact_phone
            )
        )
        conn.commit()

        # Si dio DNI → actualizar lead y cargar Puente en background
        if got_dni_now:
            import asyncio as _aio
            _aio.create_task(_load_puente_bg(contact_name, contact_phone, new_data.get("dni"), campaign_id))

        # Guardar respuesta y enviar por WA
        existing_conv = conn.execute("SELECT id FROM conversations WHERE contact_phone=?", (contact_phone,)).fetchone()
        if existing_conv:
            conn.execute("INSERT INTO chat_messages (conversation_id,direction,body) VALUES (?,?,?)",
                         (existing_conv["id"], "out", reply_text))
            conn.execute("UPDATE conversations SET last_message=?,last_message_at=? WHERE id=?",
                         (reply_text, now_str, existing_conv["id"]))
            conn.commit()
        await send_whatsapp_reply(contact_phone, reply_text)
        conn.close()
        return reply_text

    # ─── FASE 2: Relevar info comercial (con o sin DNI) ───────────────
    post_data = {
        "localidad": ai_conv["post_localidad"],
        "situacion_laboral": ai_conv["post_situacion_laboral"],
        "cobertura_actual": ai_conv["post_cobertura_actual"],
        "punto_dolor": ai_conv["post_punto_dolor"],
        "info_salud": ai_conv["post_info_salud"],
    }
    post_data = {k: v for k, v in post_data.items() if v}

    result = await get_ai_response(
        history, contact_name, contact_phone, already_have,
        phase="post", post_data=post_data
    )

    history.append({"role": "assistant", "content": result["reply"]})
    merged_post = result.get("post_data", {})
    is_now_complete = result.get("conversation_complete", False)

    # Guardar datos extraídos
    conn.execute("""
        UPDATE ai_conversations SET
            history=?, post_localidad=?, post_situacion_laboral=?,
            post_cobertura_actual=?, post_punto_dolor=?, post_info_salud=?,
            updated_at=?
        WHERE contact_phone=?""",
        (
            json.dumps(history),
            merged_post.get("localidad"),
            merged_post.get("situacion_laboral"),
            merged_post.get("cobertura_actual"),
            merged_post.get("punto_dolor"),
            merged_post.get("info_salud"),
            now_str,
            contact_phone
        )
    )
    conn.commit()

    reply_text = result["reply"]
    existing_conv = conn.execute("SELECT id FROM conversations WHERE contact_phone=?", (contact_phone,)).fetchone()

    if not is_now_complete:
        # Conversación sigue — enviar respuesta normal
        if existing_conv:
            conn.execute("INSERT INTO chat_messages (conversation_id,direction,body) VALUES (?,?,?)",
                         (existing_conv["id"], "out", reply_text))
            conn.execute("UPDATE conversations SET last_message=?,last_message_at=? WHERE id=?",
                         (reply_text, now_str, existing_conv["id"]))
            conn.commit()
        await send_whatsapp_reply(contact_phone, reply_text)
        conn.close()
        return reply_text

    # ─── COMPLETADO → cierre + resumen ───────────────────────────────
    closing_text = "Perfecto. Le voy a derivar tu caso a un asesor y te va a estar escribiendo por acá."
    history.append({"role": "assistant", "content": closing_text})

    final_post = merged_post
    conn.execute("""
        UPDATE ai_conversations SET
            history=?, conversation_complete=1,
            post_localidad=?, post_situacion_laboral=?,
            post_cobertura_actual=?, post_punto_dolor=?, post_info_salud=?,
            updated_at=?
        WHERE contact_phone=?""",
        (
            json.dumps(history),
            final_post.get("localidad"),
            final_post.get("situacion_laboral"),
            final_post.get("cobertura_actual"),
            final_post.get("punto_dolor"),
            final_post.get("info_salud"),
            now_str,
            contact_phone
        )
    )
    conn.commit()

    if existing_conv:
        conn.execute("INSERT INTO chat_messages (conversation_id,direction,body) VALUES (?,?,?)",
                     (existing_conv["id"], "out", closing_text))
        conn.execute("UPDATE conversations SET last_message=?,last_message_at=? WHERE id=?",
                     (closing_text, now_str, existing_conv["id"]))
        conn.commit()
    await send_whatsapp_reply(contact_phone, closing_text)

    # Resumen + Telegram en background
    dni = already_have.get("dni", "")
    data_for_lead = {
        "dni": dni,
        "codigo_postal": "2000",
        "localidad": final_post.get("localidad", ""),
        "info_salud": final_post.get("info_salud", ""),
    }
    import asyncio as _aio
    _aio.create_task(_qualify_and_notify_bg(contact_name, contact_phone, data_for_lead, campaign_id, dni, final_post))

    conn.close()
    return closing_text


async def _load_puente_bg(contact_name: str, contact_phone: str, dni: str, campaign_id: int = None):
    """Guarda el DNI en el lead. Puente Digital se carga recién cuando la conversación está completa (con todos los datos)."""
    import sys
    try:
        bg_conn = get_db()
        try:
            bg_conn.execute(
                "UPDATE leads SET dni=? WHERE contact_phone=? AND (dni IS NULL OR dni='')",
                (dni, contact_phone)
            )
            bg_conn.commit()
        except Exception as e:
            print(f"[BG DNI] error: {e}", file=sys.stderr, flush=True)
        finally:
            bg_conn.close()
    except Exception as e:
        print(f"[BG DNI] outer error: {e}", file=sys.stderr, flush=True)

async def _qualify_and_notify_bg(contact_name, contact_phone, data_for_lead, campaign_id, dni, final_post):
    """Ejecuta calificación de lead y notificaciones en background, sin bloquear el webhook."""
    import sys
    try:
        bg_conn = get_db()
        try:
            await process_qualified_lead(bg_conn, contact_name, contact_phone, data_for_lead, campaign_id)
        except Exception as _pql_err:
            print(f"[BG] Error en process_qualified_lead: {_pql_err}", file=sys.stderr, flush=True)

        # Generar resumen y notificar
        try:
            summary = await generate_case_summary(contact_name, dni, final_post)
            lead = bg_conn.execute(
                "SELECT l.*, a.telegram_chat_id, a.nombre as asesor_nombre FROM leads l LEFT JOIN asesores a ON l.asesor_id=a.id WHERE l.contact_phone=?",
                (contact_phone,)
            ).fetchone()
            puente_msg = lead["puente_message"] if lead else ""
            puente_status = lead["puente_status"] if lead else "pending"
            is_afiliado = lead and puente_status == "error" and any(
                kw in (puente_msg or "").lower() for kw in ["afiliado", "ya existe", "existente", "duplicado", "already"]
            )
            asesor_nombre = lead["asesor_nombre"] if lead else "Sin asignar"

            if is_afiliado:
                title = "🟢 <b>Lead calificado — Pero ya es un afiliado</b>"
                puente_line = "⚠️ Ya es afiliado existente"
            else:
                title = "🟢 <b>Lead calificado</b>"
                puente_line = "✅ Cargado" if puente_status == "success" else "⏳ Pendiente"

            msg_resumen = (
                f"{title}\n\n"
                f"{summary}\n\n"
                f"👨‍💼 Asesor: {asesor_nombre}\n"
                f"🏥 Puente Digital: {puente_line}\n"
                f"📱 WhatsApp: {contact_phone}"
            )

            asesor_chat_id = lead["telegram_chat_id"] if lead else None
            asesor_id = lead["asesor_id"] if lead else None
            sent_to = set()
            # SOLO al asesor asignado
            if asesor_chat_id:
                await send_telegram_to(asesor_chat_id, msg_resumen)
                sent_to.add(asesor_chat_id)
            # Y a vendedores vinculados a ese asesor
            if asesor_id:
                try:
                    linked_users = bg_conn.execute(
                        "SELECT telegram_chat_id FROM users WHERE asesor_id=? AND telegram_chat_id IS NOT NULL AND telegram_chat_id != ''",
                        (asesor_id,)
                    ).fetchall()
                    for u in linked_users:
                        if u["telegram_chat_id"] not in sent_to:
                            await send_telegram_to(u["telegram_chat_id"], msg_resumen)
                            sent_to.add(u["telegram_chat_id"])
                except:
                    pass
            # Admins NO reciben resumen — solo Lead Desatendido
        except Exception as _sum_err:
            print(f"[BG] Error enviando resumen: {_sum_err}", file=sys.stderr, flush=True)
        finally:
            bg_conn.close()
    except Exception as e:
        print(f"[BG] Error general: {e}", file=sys.stderr, flush=True)

async def export_lead_to_sheets(lead_data: dict):
    """Exporta un lead calificado a Google Sheets."""
    if not GOOGLE_SHEET_ID or not GOOGLE_SHEETS_CREDENTIALS:
        return
    try:
        import json as _json
        creds_dict = _json.loads(GOOGLE_SHEETS_CREDENTIALS)
        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = GCredentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1

        # Add header if empty
        if sheet.row_count == 0 or not sheet.row_values(1):
            sheet.append_row([
                "Fecha", "Nombre", "Teléfono", "DNI", "Localidad",
                "Código Postal", "Código Área", "Celular", "Asesor"
            ])

        sheet.append_row([
            datetime.now(TZ_AR).strftime("%d/%m/%Y %H:%M"),
            lead_data.get("contact_name", ""),
            lead_data.get("contact_phone", ""),
            lead_data.get("dni", ""),
            lead_data.get("localidad", ""),
            lead_data.get("codigo_postal", ""),
            lead_data.get("codigo_area", ""),
            lead_data.get("celular", ""),
            lead_data.get("asesor_nombre", ""),
        ])
        print(f"Sheets: lead exportado — {lead_data.get('contact_name')}")
    except Exception as e:
        print(f"Sheets error: {e}")

async def notify_lead_qualified(contact_name: str, contact_phone: str, data: dict, asesor_nombre: str, puente_ok: bool = False, ya_afiliado: bool = False):
    """Envía notificación de Telegram cuando se califica un lead."""
    if ya_afiliado:
        title = "🎯 <b>Lead calificado — Pero ya es un afiliado</b>"
        puente_line = "🏥 <b>Puente Digital:</b> ⚠️ Ya es afiliado existente"
    else:
        title = "🎯 <b>¡Nuevo lead calificado!</b>"
        puente_line = f"🏥 <b>Puente Digital:</b> {'✅ Cargado' if puente_ok else '⏳ Pendiente'}"
    msg = (
        f"{title}\n\n"
        f"👤 <b>Nombre:</b> {contact_name}\n"
        f"📱 <b>WhatsApp:</b> {contact_phone}\n"
        f"🪪 <b>DNI:</b> {data.get('dni','—')}\n"
        f"📍 <b>Localidad:</b> {data.get('localidad','—')}\n"
        f"📮 <b>Código postal:</b> {data.get('codigo_postal','—')}\n"
        f"👨‍💼 <b>Asesor:</b> {asesor_nombre or 'Sin asignar'}\n"
        f"{puente_line}"
    )
    await send_telegram(msg)

async def process_qualified_lead(conn, contact_name: str, contact_phone: str, data: dict, campaign_id: int = None):
    """Crea o actualiza el lead, lo carga en Puente Digital y asigna asesor.
    Si el lead ya existe (asignación temprana), solo actualiza datos y procesa Puente."""
    phone_clean = contact_phone.replace("+","").replace(" ","")
    if phone_clean.startswith("549"): phone_clean = phone_clean[3:]
    elif phone_clean.startswith("54"): phone_clean = phone_clean[2:]
    celular_raw = data.get("celular", phone_clean)
    codigo_area = data.get("codigo_area", "")
    if not codigo_area and len(phone_clean) >= 10:
        codigo_area = phone_clean[:3]
        celular_raw = phone_clean[3:]

    # Buscar lead existente (creado en asignación temprana)
    existing_lead = conn.execute(
        "SELECT * FROM leads WHERE contact_phone=? ORDER BY id DESC LIMIT 1", (contact_phone,)
    ).fetchone()

    if existing_lead:
        # Actualizar datos faltantes
        lead_id = existing_lead["id"]
        conn.execute("""
            UPDATE leads SET
                dni=COALESCE(NULLIF(?,''), dni),
                localidad=COALESCE(NULLIF(?,''), localidad),
                codigo_area=COALESCE(NULLIF(?,''), codigo_area),
                celular=COALESCE(NULLIF(?,''), celular),
                qualified_at=COALESCE(qualified_at, ?)
            WHERE id=?""",
            (data.get("dni",""), data.get("localidad",""), codigo_area, celular_raw,
             datetime.now(TZ_AR).isoformat(), lead_id)
        )
        conn.commit()
        # Recargar para asesor
        existing_lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        asesor_id = existing_lead["asesor_id"]
        asesor = conn.execute("SELECT * FROM asesores WHERE id=?", (asesor_id,)).fetchone() if asesor_id else None
        asesor = dict(asesor) if asesor else None
    else:
        # Asignar asesor nuevo
        asesor = assign_asesor(conn)
        asesor_id = asesor["id"] if asesor else None
        if asesor_id:
            conn.execute("UPDATE asesores SET leads_asignados=leads_asignados+1 WHERE id=?", (asesor_id,))

        cur = conn.execute("""
            INSERT INTO leads (contact_name, contact_phone, campaign_id, dni, localidad,
                              codigo_area, celular, asesor_id, qualified_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (contact_name, contact_phone, campaign_id,
             data.get("dni"), data.get("localidad"),
             codigo_area, celular_raw, asesor_id,
             datetime.now(TZ_AR).isoformat())
        )
        lead_id = cur.lastrowid
        conn.commit()

    asesor_nombre = asesor["nombre"] if asesor else ""

    # Exportar a Google Sheets
    await export_lead_to_sheets({
        "contact_name": contact_name,
        "contact_phone": contact_phone,
        "dni": data.get("dni", ""),
        "localidad": data.get("localidad", ""),
        "codigo_postal": data.get("codigo_postal", ""),
        "codigo_area": codigo_area,
        "celular": celular_raw,
        "asesor_nombre": asesor_nombre,
    })

    # Cargar en Puente Digital SOLO si hay DNI y no fue ya cargado exitosamente
    dni = (data.get("dni") or "").strip()
    current_puente = existing_lead["puente_status"] if existing_lead else None
    if current_puente == "success":
        pass  # Ya fue subido exitosamente — no reintentar para no quedar como error
    elif dni:
        asesor_puente_user = (asesor.get("puente_user","") if asesor else "") or ""
        asesor_puente_pass = (asesor.get("puente_password","") if asesor else "") or ""
        effective_user = asesor_puente_user or PUENTE_USER
        effective_pass = asesor_puente_pass or PUENTE_PASSWORD
        demo = not (effective_user and effective_pass)

        puente_result = await cargar_contacto_puente_digital(
            dni=dni,
            localidad=data.get("localidad", ""),
            codigo_postal=data.get("codigo_postal", ""),
            codigo_area=codigo_area,
            celular=celular_raw,
            demo_mode=demo,
            username=effective_user,
            password=effective_pass
        )
        puente_status = "success" if puente_result["success"] else "error"
        conn.execute(
            "UPDATE leads SET puente_status=?, puente_message=? WHERE id=?",
            (puente_status, puente_result["message"], lead_id)
        )
    else:
        # Sin DNI → marcar como pendiente, no se carga en Puente
        conn.execute(
            "UPDATE leads SET puente_status=?, puente_message=? WHERE id=?",
            ("pending", "Sin DNI — no se cargó en Puente", lead_id)
        )

    conn.commit()
    return lead_id


def assign_asesor_for_phone(conn, contact_phone: str, contact_name: str, campaign_id: int = None):
    """Asigna un asesor al primer contacto y crea el lead parcial. Idempotente."""
    existing = conn.execute(
        "SELECT * FROM leads WHERE contact_phone=? ORDER BY id DESC LIMIT 1", (contact_phone,)
    ).fetchone()
    if existing:
        return dict(existing) if existing else None, None  # ya existe

    asesor = assign_asesor(conn)
    asesor_id = asesor["id"] if asesor else None
    if asesor_id:
        conn.execute("UPDATE asesores SET leads_asignados=leads_asignados+1 WHERE id=?", (asesor_id,))

    cur = conn.execute("""
        INSERT INTO leads (contact_name, contact_phone, campaign_id, asesor_id, qualified_at, puente_status, puente_message)
        VALUES (?,?,?,?,?,?,?)""",
        (contact_name, contact_phone, campaign_id, asesor_id,
         datetime.now(TZ_AR).isoformat(), "pending", "Pendiente — relevando datos")
    )
    lead_id = cur.lastrowid
    conn.commit()
    lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    return dict(lead) if lead else None, asesor


async def notify_lead_assigned(asesor: dict, contact_name: str, contact_phone: str):
    """Notifica al asesor que se le asignó un nuevo lead (al inicio, antes de tener datos)."""
    if not asesor:
        return
    msg = (
        f"🎯 <b>Nuevo lead asignado — Prevención Salud</b>\n\n"
        f"👤 <b>{contact_name}</b>\n"
        f"📱 {contact_phone}\n\n"
        f"El cliente acaba de responder a la campaña. Te llegará el resumen cuando se complete el relevamiento."
    )
    sent_to = set()
    if asesor.get("telegram_chat_id"):
        try:
            await send_telegram_to(asesor["telegram_chat_id"], msg)
            sent_to.add(asesor["telegram_chat_id"])
        except: pass
    # Linked users
    if asesor.get("id"):
        try:
            conn = get_db()
            users = conn.execute(
                "SELECT telegram_chat_id FROM users WHERE asesor_id=? AND telegram_chat_id IS NOT NULL AND telegram_chat_id != ''",
                (asesor["id"],)
            ).fetchall()
            conn.close()
            for u in users:
                if u["telegram_chat_id"] not in sent_to:
                    await send_telegram_to(u["telegram_chat_id"], msg)
                    sent_to.add(u["telegram_chat_id"])
        except: pass

# ─── HELPERS ───────────────────────────────────────────────────────────────────
def personalize(template: str, name: str) -> str:
    first = name.split()[0]
    return template.replace("{{nombre}}", first).replace("{{name}}", first)

def upsert_conversation(conn, name: str, phone: str, campaign_id: int, last_msg: str, unread: int = 0):
    existing = conn.execute("SELECT id FROM conversations WHERE contact_phone=?", (phone,)).fetchone()
    if existing:
        conn.execute("""UPDATE conversations SET contact_name=?, last_message=?, last_message_at=?, unread=unread+?
                        WHERE contact_phone=?""", (name, last_msg, datetime.now(TZ_AR).isoformat(), unread, phone))
        return existing["id"]
    else:
        cur = conn.execute("""INSERT INTO conversations (contact_name,contact_phone,campaign_id,last_message,last_message_at,unread)
                              VALUES (?,?,?,?,?,?)""", (name, phone, campaign_id, last_msg, datetime.now(TZ_AR).isoformat(), unread))
        return cur.lastrowid

DEMO_REPLIES = [
    "Hola! Me interesa, ¿pueden darme más info?",
    "Perfecto, ¿cuándo podemos hablar?",
    "Gracias por contactarme 👍",
    "¿Tienen disponibilidad esta semana?",
    "Me gustaría saber el precio",
    "Excelente! Los llamo mañana",
    "Ya vi la info, muy interesante",
    "¿Pueden enviarme más detalles por favor?",
    "Sí, me interesa! ¿Cómo sigo?",
    "Perfecto, agendo para la semana que viene",
]

async def simulate_lifecycle(campaign_id: int, msg_id: int, name: str, phone: str, image_path: str = None):
    await asyncio.sleep(random.uniform(0.5, 1.5))
    conn = get_db()
    wa_id = f"demo_{campaign_id}_{msg_id}_{random.randint(10000,99999)}"
    conn.execute("UPDATE messages SET status='sent',wa_message_id=?,sent_at=? WHERE id=?",
                 (wa_id, datetime.now(TZ_AR).isoformat(), msg_id))
    conn.execute("UPDATE campaigns SET sent=sent+1 WHERE id=?", (campaign_id,))
    # Registrar en conversaciones el mensaje enviado
    msg_row = conn.execute("SELECT message_text FROM messages WHERE id=?", (msg_id,)).fetchone()
    conv_id = upsert_conversation(conn, name, phone, campaign_id, msg_row["message_text"] if msg_row else "", 0)
    conn.execute("INSERT INTO chat_messages (conversation_id,direction,body,image_path) VALUES (?,?,?,?)",
                 (conv_id, "out", msg_row["message_text"] if msg_row else "", image_path))
    conn.commit(); conn.close()

    await asyncio.sleep(random.uniform(3, 8))
    conn = get_db()
    conn.execute("UPDATE messages SET status='delivered',delivered_at=? WHERE id=?",
                 (datetime.now(TZ_AR).isoformat(), msg_id))
    conn.execute("UPDATE campaigns SET delivered=delivered+1 WHERE id=?", (campaign_id,))
    conn.commit(); conn.close()

    if random.random() < 0.70:
        await asyncio.sleep(random.uniform(10, 30))
        conn = get_db()
        conn.execute("UPDATE messages SET status='read',read_at=? WHERE id=?",
                     (datetime.now(TZ_AR).isoformat(), msg_id))
        conn.execute("UPDATE campaigns SET read_count=read_count+1 WHERE id=?", (campaign_id,))
        conn.execute("INSERT INTO notifications (type,contact_name,contact_phone,message,campaign_id) VALUES (?,?,?,?,?)",
                     ("read", name, phone, "Leyó tu mensaje", campaign_id))
        conn.commit(); conn.close()

        if random.random() < 0.35:
            await asyncio.sleep(random.uniform(15, 50))
            reply = random.choice(DEMO_REPLIES)
            conn = get_db()
            conn.execute("UPDATE messages SET status='replied',replied_at=?,reply_text=? WHERE id=?",
                         (datetime.now(TZ_AR).isoformat(), reply, msg_id))
            conn.execute("UPDATE campaigns SET replied=replied+1 WHERE id=?", (campaign_id,))
            conn.execute("INSERT INTO notifications (type,contact_name,contact_phone,message,campaign_id) VALUES (?,?,?,?,?)",
                         ("reply", name, phone, reply, campaign_id))
            conn.commit(); conn.close()
            conn = get_db()
            # Agregar al chat
            conv = conn.execute("SELECT id FROM conversations WHERE contact_phone=?", (phone,)).fetchone()
            if conv:
                conn.execute("INSERT INTO chat_messages (conversation_id,direction,body) VALUES (?,?,?)",
                             (conv["id"], "in", reply))
                conn.execute("UPDATE conversations SET last_message=?,last_message_at=?,unread=unread+1 WHERE id=?",
                             (reply, datetime.now(TZ_AR).isoformat(), conv["id"]))
            conn.commit(); conn.close()

async def send_whatsapp_reply(phone: str, message: str) -> bool:
    phone_clean = phone.strip().replace(" ","").replace("-","").replace("+","")
    if not phone_clean.startswith("549"): phone_clean = "549" + phone_clean.lstrip("0")
    if not WA_TOKEN or not WA_PHONE_ID: return True
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://graph.facebook.com/v19.0/{WA_PHONE_ID}/messages",
                json={"messaging_product":"whatsapp","to":phone_clean,"type":"text","text":{"body":message}},
                headers={"Authorization":f"Bearer {WA_TOKEN}","Content-Type":"application/json"}
            )
            return resp.status_code == 200
    except: return False

async def send_whatsapp_template(phone: str, name: str, template_name: str = "prevencion_contacto_inicial", template_lang: str = "es_AR", header_type: str = None, header_example: str = None) -> Optional[str]:
    """Envía template via Meta Cloud API. Retorna wa_message_id o None."""
    phone_clean = phone.strip().replace(" ","").replace("-","").replace("+","")
    if not phone_clean.startswith("549") and not phone_clean.startswith("54"):
        phone_clean = "549" + phone_clean.lstrip("0")

    first = name.split()[0]
    print(f"TEMPLATE: name={template_name} lang={template_lang} header_type={header_type} header_example={str(header_example)[:50] if header_example else None}", flush=True)
    components = []
    # Media IDs permanentes por template
    TEMPLATE_MEDIA_IDS = {
        "flyer_descuento": "1658909608699271",
        "plantilla_sueldo": "2162257297854917",
        "flyer_descuento_dni_nuevo": "963594646581150",
    }
    media_id = TEMPLATE_MEDIA_IDS.get(template_name)
    if header_type == "IMAGE" and media_id:
        components.append({
            "type": "header",
            "parameters": [{"type": "image", "image": {"id": media_id}}]
        })
    components.append({
        "type": "body",
        "parameters": [{"type": "text", "parameter_name": "nombre", "text": first}]
    })
    template_payload = {
        "name": template_name,
        "language": {"code": template_lang or "es_AR"},
        "components": components
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": phone_clean,
        "type": "template",
        "template": template_payload
    }
    headers = {"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"}

    if not WA_TOKEN or not WA_PHONE_ID:
        import uuid
        await asyncio.sleep(0.3)
        print(f"DEMO: would send template '{template_name}' to {phone_clean}")
        return f"demo_{uuid.uuid4().hex[:12]}"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://graph.facebook.com/v19.0/{WA_PHONE_ID}/messages",
                json=payload, headers=headers
            )
            data = resp.json()
            if resp.status_code == 200 and "messages" in data:
                return data["messages"][0]["id"]
            # If NAMED param failed, try without components
            if "parameter" in str(data).lower():
                del template_payload["components"]
                resp2 = await client.post(
                    f"https://graph.facebook.com/v19.0/{WA_PHONE_ID}/messages",
                    json=payload, headers=headers
                )
                data2 = resp2.json()
                if resp2.status_code == 200 and "messages" in data2:
                    return data2["messages"][0]["id"]
            print(f"WA Error: {data}")
            return None
    except Exception as e:
        print(f"Error enviando a {phone}: {e}")
        return None

async def send_campaign_messages(campaign_id: int):
    conn = get_db()
    camp = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
    image_path = camp["image_path"] if camp else None
    pending = conn.execute("SELECT * FROM messages WHERE campaign_id=? AND status='pending'", (campaign_id,)).fetchall()
    conn.close()
    template_name   = camp["message_template"] if camp else "prevencion_contacto_inicial"
    template_lang   = camp["template_lang"] if camp else "es_AR"
    header_type     = camp["header_type"] if camp else None
    header_example  = camp["header_example"] if camp else None
    for msg in pending:
        wa_id = await send_whatsapp_template(msg["phone"], msg["name"], template_name, template_lang, header_type, header_example)
        conn = get_db()
        if wa_id:
            conn.execute("UPDATE messages SET wa_message_id=?,status='sent',sent_at=? WHERE id=?",
                         (wa_id, datetime.now(TZ_AR).isoformat(), msg["id"]))
            conn.execute("UPDATE campaigns SET sent=sent+1 WHERE id=?", (campaign_id,))
        else:
            conn.execute("UPDATE messages SET status='failed' WHERE id=?", (msg["id"],))
        conn.commit(); conn.close()
        await asyncio.sleep(1.2)
    conn = get_db()
    conn.execute("UPDATE campaigns SET status='sent' WHERE id=?", (campaign_id,))
    conn.commit(); conn.close()

# ─── ENDPOINTS ─────────────────────────────────────────────────────────────────

@app.post("/api/contacts/upload")
async def upload_contacts(request: Request, file: UploadFile = File(...)):
    require_auth(request)
    try:
        raw = await file.read()
        df = pd.read_csv(pd.io.common.BytesIO(raw)) if file.filename.endswith(".csv") else pd.read_excel(pd.io.common.BytesIO(raw))
        df.columns = [c.strip().lower() for c in df.columns]
        name_col  = next((c for c in df.columns if any(x in c for x in ["nombre","name","apellido"])), None)
        phone_col = next((c for c in df.columns if any(x in c for x in ["tel","phone","celular","movil","móvil","whatsapp"])), None)
        if not name_col or not phone_col:
            return JSONResponse(status_code=400, content={"error": f"Columnas no detectadas. Encontradas: {list(df.columns)}"})
        conn = get_db()
        # Crear registro de importación
        cur = conn.execute(
            "INSERT INTO imports (filename, total) VALUES (?, ?)",
            (file.filename, len(df))
        )
        import_id = cur.lastrowid
        inserted = skipped = 0
        for _, row in df.iterrows():
            name = str(row[name_col]).strip(); phone = str(row[phone_col]).strip()
            if not name or not phone or "nan" in (name, phone): skipped += 1; continue
            extra = {c: str(row[c]) for c in df.columns if c not in [name_col, phone_col]}
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO contacts (name,phone,extra_data,import_id) VALUES (?,?,?,?)",
                    (name, phone, json.dumps(extra), import_id)
                )
                inserted += 1
            except: skipped += 1
        # Actualizar totales en la importación
        conn.execute("UPDATE imports SET inserted=?, skipped=? WHERE id=?", (inserted, skipped, import_id))
        conn.commit(); conn.close()
        return {"inserted": inserted, "skipped": skipped, "total_in_file": len(df), "import_id": import_id}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/imports")
def get_imports(request: Request):
    """Lista todas las importaciones con sus totales."""
    require_auth(request)
    conn = get_db()
    rows = conn.execute("SELECT * FROM imports ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.delete("/api/imports/{import_id}")
def delete_import(import_id: int, request: Request):
    """Elimina una importación y todos sus contactos."""
    require_admin(request)
    conn = get_db()
    conn.execute("DELETE FROM contacts WHERE import_id=?", (import_id,))
    conn.execute("DELETE FROM imports WHERE id=?", (import_id,))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/upload-image")
async def upload_image(request: Request, file: UploadFile = File(...)):
    """Sube una imagen para usar en campañas. Retorna la ruta."""
    require_auth(request)
    try:
        ext = file.filename.split(".")[-1].lower()
        if ext not in ["jpg","jpeg","png","gif","webp"]:
            raise HTTPException(400, "Formato no soportado. Usá JPG, PNG o GIF.")
        filename = f"{uuid.uuid4().hex}.{ext}"
        path = os.path.join(IMAGES_DIR, filename)
        content = await file.read()
        with open(path, "wb") as f:
            f.write(content)
        return {"image_path": filename, "url": f"/images/{filename}"}
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/images/{filename}")
async def serve_image(filename: str):
    path = os.path.join(IMAGES_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Imagen no encontrada")
    return FileResponse(path)

@app.get("/api/contacts")
def get_contacts(request: Request, page: int = 1, per_page: int = 50, search: str = "", import_id: Optional[int] = None):
    require_auth(request)
    conn = get_db(); offset = (page-1)*per_page
    filters = []
    params  = []
    if search:
        filters.append("(name LIKE ? OR phone LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if import_id is not None:
        filters.append("import_id = ?")
        params.append(import_id)
    elif import_id == 0:
        filters.append("import_id IS NULL")
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    rows  = conn.execute(f"SELECT * FROM contacts {where} LIMIT ? OFFSET ?", params+[per_page,offset]).fetchall()
    total = conn.execute(f"SELECT COUNT(*) FROM contacts {where}", params).fetchone()[0]
    conn.close()
    return {"contacts": [dict(r) for r in rows], "total": total, "page": page, "per_page": per_page}

@app.post("/api/campaigns")
def create_campaign(data: CampaignCreate, request: Request):
    require_auth(request)
    conn = get_db()
    tmpl = data.template_name or data.message_template or "prevencion_contacto_inicial"
    cur = conn.execute("INSERT INTO campaigns (name,message_template,template_lang,header_type,header_example,image_path,total_contacts) VALUES (?,?,?,?,?,?,?)",
                       (data.name, tmpl, data.template_lang or "es_AR", data.header_type, data.header_example, data.image_path, len(data.contact_ids)))
    cid = cur.lastrowid
    for contact_id in data.contact_ids:
        c = conn.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()
        if c:
            conn.execute("INSERT INTO messages (campaign_id,contact_id,phone,name,message_text,image_path) VALUES (?,?,?,?,?,?)",
                         (cid, contact_id, c["phone"], c["name"], personalize(data.message_template, c["name"]), data.image_path))
    conn.commit(); conn.close()
    return {"campaign_id": cid, "contacts": len(data.contact_ids)}

@app.get("/api/campaigns")
def get_campaigns(request: Request):
    require_auth(request)
    conn = get_db()
    rows = conn.execute("SELECT * FROM campaigns ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/campaigns/{campaign_id}")
def get_campaign_detail(campaign_id: int, request: Request):
    require_auth(request)
    conn = get_db()
    campaign = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
    messages  = conn.execute("SELECT * FROM messages WHERE campaign_id=?", (campaign_id,)).fetchall()
    conn.close()
    if not campaign: raise HTTPException(404, "No encontrada")
    return {"campaign": dict(campaign), "messages": [dict(m) for m in messages]}

@app.post("/api/campaigns/{campaign_id}/send")
async def send_campaign(campaign_id: int, background_tasks: BackgroundTasks, request: Request):
    require_auth(request)
    conn = get_db()
    if not conn.execute("SELECT id FROM campaigns WHERE id=?", (campaign_id,)).fetchone():
        conn.close(); raise HTTPException(404)
    conn.execute("UPDATE campaigns SET status='sending' WHERE id=?", (campaign_id,))
    conn.commit(); conn.close()
    background_tasks.add_task(send_campaign_messages, campaign_id)
    return {"status": "sending", "campaign_id": campaign_id}

@app.get("/api/my-leads-contacts")
async def get_my_leads_as_contacts(request: Request):
    """Devuelve los leads asignados al productor como contactos para campañas."""
    user = require_auth(request)
    if user["role"] != "productor":
        raise HTTPException(403, "Solo productores")
    conn = get_db()
    rows = conn.execute("""
        SELECT l.id, l.contact_name as name, l.contact_phone as phone
        FROM leads l WHERE l.productor_id=? AND l.lead_status='active'
        ORDER BY l.contact_name
    """, (user["user_id"],)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ─── BANDEJA DE ENTRADA ────────────────────────────────────────────────────────

@app.get("/api/conversations")
def get_conversations(request: Request):
    user = require_auth(request)
    conn = get_db()
    if user["role"] == "productor":
        # Solo conversaciones de leads asignados a este productor
        rows = conn.execute("""
            SELECT c.* FROM conversations c
            INNER JOIN leads l ON c.contact_phone = l.contact_phone
            WHERE l.productor_id = ?
            ORDER BY c.last_message_at DESC
        """, (user["user_id"],)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM conversations ORDER BY last_message_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/conversations/{conv_id}/messages")
def get_chat_messages(conv_id: int, request: Request):
    require_auth(request)
    conn = get_db()
    conv = conn.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
    if not conv:
        conn.close()
        return {"conversation": None, "messages": []}
    msgs = conn.execute("SELECT * FROM chat_messages WHERE conversation_id=? ORDER BY created_at ASC", (conv_id,)).fetchall()
    # Marcar como leído
    conn.execute("UPDATE conversations SET unread=0 WHERE id=?", (conv_id,))
    conn.commit(); conn.close()
    return {"conversation": dict(conv), "messages": [dict(m) for m in msgs]}

@app.get("/api/conversations/{conv_id}/messages-since")
def get_chat_messages_since(conv_id: int, request: Request, after_id: int = 0):
    """Devuelve solo los mensajes con id > after_id, para polling incremental sin rerender."""
    require_auth(request)
    conn = get_db()
    msgs = conn.execute(
        "SELECT * FROM chat_messages WHERE conversation_id=? AND id > ? ORDER BY created_at ASC",
        (conv_id, after_id)
    ).fetchall()
    # Marcar como leído si hubo entrantes
    if msgs:
        conn.execute("UPDATE conversations SET unread=0 WHERE id=?", (conv_id,))
        conn.commit()
    conn.close()
    return {"messages": [dict(m) for m in msgs]}

@app.post("/api/conversations/send-file")
async def send_file(
    request: Request,
    conversation_id: int = Form(...),
    file: UploadFile = File(...)
):
    require_auth(request)
    conn = get_db()
    conv = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    if not conv: conn.close(); raise HTTPException(404)

    file_bytes = await file.read()
    file_name  = file.filename
    mime_type  = file.content_type or "application/octet-stream"
    is_image   = mime_type.startswith("image/")
    is_audio   = mime_type.startswith("audio/")
    is_video   = mime_type.startswith("video/")

    # Si es audio en webm (Chrome) y tenemos ffmpeg → convertir a OGG/Opus (Meta solo acepta esos containers)
    if is_audio and ("webm" in mime_type or file_name.lower().endswith(".webm")):
        try:
            import subprocess, tempfile, os as _os
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as fin:
                fin.write(file_bytes); fin.flush()
                in_path = fin.name
            out_path = in_path.replace(".webm", ".ogg")
            # Re-empaquetar sin re-codificar (mismo codec opus): -c:a copy
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", in_path, "-c:a", "copy", out_path],
                capture_output=True, timeout=30
            )
            if r.returncode == 0 and _os.path.exists(out_path) and _os.path.getsize(out_path) > 100:
                with open(out_path, "rb") as f: file_bytes = f.read()
                mime_type = "audio/ogg"
                file_name = file_name.rsplit(".",1)[0] + ".ogg"
                print(f"[AUDIO CONVERT] webm → ogg OK ({len(file_bytes)} bytes)", file=__import__('sys').stderr, flush=True)
            else:
                print(f"[AUDIO CONVERT] ffmpeg fallo: rc={r.returncode} stderr={r.stderr[:200] if r.stderr else ''}", file=__import__('sys').stderr, flush=True)
            try: _os.unlink(in_path)
            except: pass
            try: _os.unlink(out_path)
            except: pass
        except FileNotFoundError:
            print("[AUDIO CONVERT] ffmpeg no encontrado en el sistema", file=__import__('sys').stderr, flush=True)
        except Exception as e:
            print(f"[AUDIO CONVERT] error: {e}", file=__import__('sys').stderr, flush=True)

    if is_image:
        media_type_wa = "image"
    elif is_audio:
        media_type_wa = "audio"
    elif is_video:
        media_type_wa = "video"
    else:
        media_type_wa = "document"

    media_id = None
    upload_err = ""
    if WA_TOKEN and WA_PHONE_ID:
        try:
            import io
            async with httpx.AsyncClient(timeout=30) as client:
                upload_resp = await client.post(
                    f"https://graph.facebook.com/v19.0/{WA_PHONE_ID}/media",
                    headers={"Authorization": f"Bearer {WA_TOKEN}"},
                    files={"file": (file_name, io.BytesIO(file_bytes), mime_type)},
                    data={"messaging_product": "whatsapp"}
                )
                upload_data = upload_resp.json()
                media_id = upload_data.get("id")
                if not media_id:
                    upload_err = upload_data.get("error",{}).get("message","upload failed")
                    print(f"[WA UPLOAD ERROR] mime={mime_type} resp={upload_data}", file=__import__('sys').stderr, flush=True)
        except Exception as e:
            upload_err = str(e)
            print(f"[WA UPLOAD EXCEPTION] {e}", file=__import__('sys').stderr, flush=True)

    wa_sent = False
    send_err = ""
    if media_id:
        try:
            phone = conv["contact_phone"]
            phone_clean = phone.strip().replace(" ","").replace("-","").replace("+","")
            if not phone_clean.startswith("549"): phone_clean = "549" + phone_clean.lstrip("0")
            if media_type_wa == "document":
                payload = {
                    "messaging_product": "whatsapp",
                    "to": phone_clean,
                    "type": "document",
                    "document": {"id": media_id, "filename": file_name}
                }
            else:
                payload = {
                    "messaging_product": "whatsapp",
                    "to": phone_clean,
                    "type": media_type_wa,
                    media_type_wa: {"id": media_id}
                }
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"https://graph.facebook.com/v19.0/{WA_PHONE_ID}/messages",
                    json=payload,
                    headers={"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"}
                )
                wa_sent = r.status_code == 200
                if not wa_sent:
                    try:
                        ed = r.json().get("error",{})
                        send_err = ed.get("message","send failed")
                    except: send_err = r.text[:200]
                    print(f"[WA SEND ERROR] type={media_type_wa} status={r.status_code} body={r.text[:500]}", file=__import__('sys').stderr, flush=True)
        except Exception as e:
            send_err = str(e)
            print(f"[WA SEND EXCEPTION] {e}", file=__import__('sys').stderr, flush=True)

    # Save to DB — store base64 for inline preview
    import base64
    b64 = base64.b64encode(file_bytes).decode()
    media_url = f"data:{mime_type};base64,{b64}"

    conn.execute(
        "INSERT INTO chat_messages (conversation_id,direction,body,media_type,media_url,media_name) VALUES (?,?,?,?,?,?)",
        (conversation_id, "out", "", media_type_wa, media_url, file_name)
    )
    conn.execute(
        "UPDATE conversations SET last_message=?,last_message_at=? WHERE id=?",
        (f"📎 {file_name}", datetime.now(TZ_AR).isoformat(), conversation_id)
    )
    conn.commit(); conn.close()
    return {"status": "ok", "sent": wa_sent, "media_id": media_id, "error": upload_err or send_err or ""}

# ─── QUICK REPLIES CRUD ──────────────────────────────────────────────────────
@app.get("/api/quick-replies")
async def get_quick_replies(request: Request):
    require_auth(request)
    conn = get_db()
    rows = conn.execute("SELECT * FROM quick_replies ORDER BY category, sort_order").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/quick-replies")
async def create_quick_reply(request: Request):
    require_admin(request)
    data = await request.json()
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO quick_replies (category,label,message,sort_order) VALUES (?,?,?,?)",
        (data["category"], data["label"], data["message"], data.get("sort_order", 0))
    )
    conn.commit(); conn.close()
    return {"ok": True, "id": cur.lastrowid}

@app.put("/api/quick-replies/{qr_id}")
async def update_quick_reply(qr_id: int, request: Request):
    require_admin(request)
    data = await request.json()
    conn = get_db()
    conn.execute(
        "UPDATE quick_replies SET category=?, label=?, message=?, sort_order=? WHERE id=?",
        (data["category"], data["label"], data["message"], data.get("sort_order", 0), qr_id)
    )
    conn.commit(); conn.close()
    return {"ok": True}

@app.delete("/api/quick-replies/{qr_id}")
async def delete_quick_reply(qr_id: int, request: Request):
    require_admin(request)
    conn = get_db()
    conn.execute("DELETE FROM quick_replies WHERE id=?", (qr_id,))
    conn.commit(); conn.close()
    return {"ok": True}

@app.post("/api/conversations/reply")
async def send_reply(data: SendReply, request: Request):
    require_auth(request)
    conn = get_db()
    conv = conn.execute("SELECT * FROM conversations WHERE id=?", (data.conversation_id,)).fetchone()
    if not conv: conn.close(); raise HTTPException(404)
    ok = await send_whatsapp_reply(conv["contact_phone"], data.body)
    conn.execute("INSERT INTO chat_messages (conversation_id,direction,body) VALUES (?,?,?)",
                 (data.conversation_id, "out", data.body))
    conn.execute("UPDATE conversations SET last_message=?,last_message_at=? WHERE id=?",
                 (data.body, datetime.now(TZ_AR).isoformat(), data.conversation_id))
    conn.commit(); conn.close()
    return {"status": "ok", "sent": ok}

@app.get("/api/notifications")
async def get_notifications(request: Request, unread_only: bool = False):
    user = require_auth(request)
    conn = get_db()
    if user["role"] == "admin":
        q = "SELECT * FROM notifications" + (" WHERE read=0" if unread_only else "") + " ORDER BY created_at DESC LIMIT 100"
        rows = conn.execute(q).fetchall()
    else:
        asesor_id = user["asesor_id"]
        if asesor_id:
            # Get phones of contacts assigned to this asesor
            phones = [r["contact_phone"] for r in conn.execute(
                "SELECT DISTINCT contact_phone FROM leads WHERE asesor_id=?", (asesor_id,)
            ).fetchall()]
            if phones:
                placeholders = ",".join("?" * len(phones))
                base = f"SELECT * FROM notifications WHERE contact_phone IN ({placeholders})"
                if unread_only: base += " AND read=0"
                base += " ORDER BY created_at DESC LIMIT 100"
                rows = conn.execute(base, phones).fetchall()
            else:
                rows = []
        else:
            rows = []
    conn.close()
    return [dict(r) for r in rows]

@app.delete("/api/notifications/clear")
async def clear_notifications(request: Request):
    require_auth(request)
    conn = get_db()
    conn.execute("DELETE FROM notifications WHERE read=1")
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.delete("/api/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int, request: Request):
    require_admin(request)
    conn = get_db()
    # Obtener phones de conversaciones vinculadas para limpiar chat_messages
    conv_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM conversations WHERE campaign_id=?", (campaign_id,)
    ).fetchall()]
    if conv_ids:
        ph = ",".join("?" * len(conv_ids))
        conn.execute(f"DELETE FROM chat_messages WHERE conversation_id IN ({ph})", conv_ids)
    conn.execute("DELETE FROM conversations WHERE campaign_id=?", (campaign_id,))
    conn.execute("DELETE FROM notifications WHERE campaign_id=?", (campaign_id,))
    conn.execute("DELETE FROM leads WHERE campaign_id=?", (campaign_id,))
    conn.execute("DELETE FROM ai_conversations WHERE campaign_id=?", (campaign_id,))
    conn.execute("DELETE FROM messages WHERE campaign_id=?", (campaign_id,))
    conn.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/leads/{lead_id}/force-retry")
async def force_retry_puente(lead_id: int, request: Request):
    require_admin(request)
    conn = get_db()
    conn.execute("UPDATE leads SET puente_status='pending', puente_message=NULL WHERE id=?", (lead_id,))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.delete("/api/contacts/bulk")
async def delete_contacts_bulk(request: Request):
    require_admin(request)
    data = await request.json()
    ids = data.get("ids", [])
    if not ids: raise HTTPException(400, "Sin IDs")
    conn = get_db()
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM contacts WHERE id IN ({placeholders})", ids)
    conn.commit(); conn.close()
    return {"status": "ok", "deleted": len(ids)}

@app.delete("/api/leads/{lead_id}")
async def delete_lead(lead_id: int, request: Request):
    require_admin(request)
    conn = get_db()
    lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead: conn.close(); raise HTTPException(404)
    # Reset qualified status so IA can re-qualify
    conn.execute("UPDATE ai_conversations SET qualified=0 WHERE contact_phone=?", (lead["contact_phone"],))
    conn.execute("DELETE FROM leads WHERE id=?", (lead_id,))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.delete("/api/conversations/{conv_id}/reset-contact")
async def reset_contact(conv_id: int, request: Request):
    """Admin only — resetea el historial completo de un contacto específico."""
    require_admin(request)
    conn = get_db()
    conv = conn.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
    if not conv: conn.close(); raise HTTPException(404)
    phone = conv["contact_phone"]
    phone9 = phone[-9:]
    conn.executescript(f"""
        DELETE FROM chat_messages WHERE conversation_id={conv_id};
        DELETE FROM ai_conversations WHERE contact_phone='{phone}' OR contact_phone LIKE '%{phone9}';
        DELETE FROM leads WHERE contact_phone='{phone}' OR contact_phone LIKE '%{phone9}';
        DELETE FROM notifications WHERE contact_phone='{phone}' OR contact_phone LIKE '%{phone9}';
        DELETE FROM messages WHERE phone LIKE '%{phone9}%';
        DELETE FROM conversations WHERE contact_phone='{phone}' OR contact_phone LIKE '%{phone9}';
        DELETE FROM contacts WHERE phone LIKE '%{phone9}%';
    """)
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/ai-conversations/{phone}/reset")
async def reset_ai_conversation(phone: str, request: Request):
    """Admin only — resetea completamente un contacto por número de teléfono."""
    require_admin(request)
    conn = get_db()
    phone9 = phone[-9:]
    conv_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM conversations WHERE contact_phone=? OR contact_phone LIKE ?",
        (phone, f"%{phone9}")
    ).fetchall()]
    if conv_ids:
        placeholders = ",".join(str(i) for i in conv_ids)
        conn.execute(f"DELETE FROM chat_messages WHERE conversation_id IN ({placeholders})")
    conn.execute("DELETE FROM ai_conversations WHERE contact_phone=? OR contact_phone LIKE ?", (phone, f"%{phone9}"))
    conn.execute("DELETE FROM leads WHERE contact_phone=? OR contact_phone LIKE ?", (phone, f"%{phone9}"))
    conn.execute("DELETE FROM notifications WHERE contact_phone=? OR contact_phone LIKE ?", (phone, f"%{phone9}"))
    conn.execute("DELETE FROM messages WHERE phone LIKE ?", (f"%{phone9}%",))
    conn.execute("DELETE FROM conversations WHERE contact_phone=? OR contact_phone LIKE ?", (phone, f"%{phone9}"))
    conn.execute("DELETE FROM contacts WHERE phone LIKE ?", (f"%{phone9}%",))
    conn.commit(); conn.close()
    return {"status": "ok"}

# ─── AI TESTING — chat de prueba que no toca DB real ───────────────────────────
# Estado en memoria por sesión de prueba
_ai_test_sessions = {}  # session_id -> {history, dni, post_data, phase, complete}

@app.post("/api/ai/test")
async def ai_test_chat(request: Request):
    """Chat de prueba con la IA — usa el mismo prompt y flujo que producción,
    pero NO toca la DB de leads/conversaciones reales."""
    require_admin(request)
    data = await request.json()
    session_id = data.get("session_id") or "default"
    user_message = (data.get("message") or "").strip()
    contact_name = data.get("contact_name") or "Tester"
    contact_phone = data.get("contact_phone") or "549000000000"
    if not user_message:
        raise HTTPException(400, "Mensaje vacío")

    sess = _ai_test_sessions.get(session_id) or {
        "history": [],
        "dni": None,
        "post_data": {},
        "phase": "pre",
        "complete": False,
        "qualified_at": None,
    }

    if sess["complete"]:
        return {
            "reply": "[Conversación ya cerrada — usá 'Reiniciar' para empezar de nuevo]",
            "phase": "done",
            "dni": sess["dni"],
            "post_data": sess["post_data"],
            "complete": True,
        }

    # Agregar mensaje del usuario
    sess["history"].append({"role": "user", "content": user_message})

    already_have = {}
    if sess["dni"]:
        already_have["dni"] = sess["dni"]

    try:
        result = await get_ai_response(
            sess["history"], contact_name, contact_phone, already_have,
            phase=sess["phase"], post_data=sess["post_data"]
        )
    except Exception as e:
        import sys
        print(f"[AI TEST] error: {e}", file=sys.stderr, flush=True)
        raise HTTPException(500, f"Error IA: {e}")

    reply = result.get("reply", "")
    sess["history"].append({"role": "assistant", "content": reply})

    # Procesar resultado según fase
    if sess["phase"] == "pre":
        if result.get("qualified"):
            sess["dni"] = result.get("all_data", {}).get("dni") or sess["dni"]
            sess["phase"] = "post"
            sess["qualified_at"] = datetime.now(TZ_AR).isoformat()
    else:
        # phase = post
        post_extracted = result.get("post_data", {})
        sess["post_data"] = {**sess["post_data"], **{k: v for k, v in post_extracted.items() if v}}
        if result.get("conversation_complete"):
            sess["complete"] = True
            # Auto-cierre fijo, igual que en producción
            closing = "Perfecto. Le voy a derivar tu caso a un asesor y te va a estar escribiendo por acá."
            sess["history"].append({"role": "assistant", "content": closing})
            reply = reply + "\n\n" + closing if reply.strip() else closing

    _ai_test_sessions[session_id] = sess
    return {
        "reply": reply,
        "phase": sess["phase"],
        "dni": sess["dni"],
        "post_data": sess["post_data"],
        "complete": sess["complete"],
        "qualified_at": sess["qualified_at"],
        "history": sess["history"],
    }

@app.post("/api/ai/test/reset")
async def ai_test_reset(request: Request):
    """Resetea la sesión de prueba."""
    require_admin(request)
    data = await request.json()
    session_id = data.get("session_id") or "default"
    _ai_test_sessions.pop(session_id, None)
    return {"status": "ok"}

@app.get("/api/ai/test/state")
async def ai_test_state(request: Request):
    """Devuelve el estado actual de una sesión de prueba."""
    require_admin(request)
    session_id = request.query_params.get("session_id") or "default"
    sess = _ai_test_sessions.get(session_id)
    if not sess:
        return {"history": [], "phase": "pre", "dni": None, "post_data": {}, "complete": False}
    return {
        "history": sess["history"],
        "phase": sess["phase"],
        "dni": sess["dni"],
        "post_data": sess["post_data"],
        "complete": sess["complete"],
    }

@app.delete("/api/reset-data")
async def reset_data(request: Request):
    """Admin only — borra notificaciones, campañas, mensajes y conversaciones."""
    require_admin(request)
    conn = get_db()
    conn.executescript("""
        DELETE FROM notifications;
        DELETE FROM messages;
        DELETE FROM campaigns;
        DELETE FROM conversations;
        DELETE FROM chat_messages;
        DELETE FROM leads;
        DELETE FROM ai_conversations;
    """)
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/notifications/mark-read")
async def mark_read(request: Request):
    user = require_auth(request)
    conn = get_db()
    conn.execute("UPDATE notifications SET read=1")
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.get("/api/stats")
async def get_stats(request: Request):
    user = require_auth(request)
    conn = get_db()
    total_contacts  = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    total_campaigns = conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0]
    if user["role"] == "admin":
        unread_notifs = conn.execute("SELECT COUNT(*) FROM notifications WHERE read=0").fetchone()[0]
        unread_convs  = conn.execute("SELECT COALESCE(SUM(unread),0) FROM conversations").fetchone()[0]
    else:
        asesor_id = user["asesor_id"]
        if asesor_id:
            phones = [r[0] for r in conn.execute(
                "SELECT DISTINCT contact_phone FROM leads WHERE asesor_id=?", (asesor_id,)
            ).fetchall()]
            if phones:
                ph = ",".join("?"*len(phones))
                unread_notifs = conn.execute(f"SELECT COUNT(*) FROM notifications WHERE read=0 AND contact_phone IN ({ph})", phones).fetchone()[0]
                unread_convs  = conn.execute(f"SELECT COALESCE(SUM(unread),0) FROM conversations WHERE contact_phone IN ({ph})", phones).fetchone()[0]
            else:
                unread_notifs = 0; unread_convs = 0
        else:
            unread_notifs = 0; unread_convs = 0
    conn.close()
    return {"total_contacts": total_contacts, "total_campaigns": total_campaigns,
            "unread_notifications": unread_notifs, "unread_conversations": unread_convs}

# ─── AUTH HELPERS ─────────────────────────────────────────────────────────────
import bcrypt as _bcrypt

def hash_password(password: str) -> str:
    """Hashea con bcrypt. Siempre usar para nuevas contraseñas."""
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()

def verify_password(password: str, stored_hash: str) -> bool:
    """Verifica la contraseña soportando bcrypt (nuevo) y SHA-256 (legacy)."""
    if stored_hash.startswith("$2"):
        return _bcrypt.checkpw(password.encode(), stored_hash.encode())
    # Hash legacy SHA-256 (64 hex chars)
    return hashlib.sha256(password.encode()).hexdigest() == stored_hash

def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(TZ_AR) + timedelta(days=7)).isoformat()
    conn = get_db()
    # Clean old sessions for this user
    conn.execute("DELETE FROM sessions WHERE user_id=? OR expires_at < ?",
                 (user_id, datetime.now(TZ_AR).isoformat()))
    conn.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)",
                 (token, user_id, expires))
    conn.commit()
    conn.close()
    return token

def get_current_user(token: str) -> dict | None:
    if not token:
        return None
    conn = get_db()
    session = conn.execute(
        """SELECT s.*, u.id as user_id, u.username, u.role, u.nombre, u.asesor_id, u.active
           FROM sessions s JOIN users u ON s.user_id=u.id
           WHERE s.token=? AND s.expires_at > ?""",
        (token, datetime.now(TZ_AR).isoformat())
    ).fetchone()
    conn.close()
    if session and session["active"]:
        return dict(session)
    return None

def require_auth(request: Request) -> dict:
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        # Try cookie
        token = request.cookies.get("session_token", "")
    user = get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="No autorizado")
    return user

def require_admin(request: Request) -> dict:
    user = require_auth(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Se requiere rol de administrador")
    return user

def require_vendedor(request: Request) -> dict:
    """Permite acceso a vendedor y admin."""
    user = require_auth(request)
    if user["role"] not in ["admin", "vendedor"]:
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    return user

# ─── AUTH ENDPOINTS ────────────────────────────────────────────────────────────

class LoginData(BaseModel):
    username: str
    password: str

@app.post("/api/auth/login")
async def login(data: LoginData):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username=? AND active=1",
        (data.username.strip().lower(),)
    ).fetchone()
    if not user or not verify_password(data.password, user["password_hash"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    # Migración transparente SHA-256 → bcrypt al primer login con hash legacy
    if not user["password_hash"].startswith("$2"):
        conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                     (hash_password(data.password), user["id"]))
        conn.commit()
    token = create_session(user["id"])
    conn.close()
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "nombre": user["nombre"],
            "role": user["role"],
            "asesor_id": user["asesor_id"]
        }
    }

@app.post("/api/auth/logout")
async def logout(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token:
        conn = get_db()
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()
    return {"status": "ok"}

@app.get("/api/auth/me")
async def get_me(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = get_current_user(token)
    if not user:
        raise HTTPException(401, "No autorizado")
    return {
        "id": user["user_id"],
        "username": user["username"],
        "nombre": user["nombre"],
        "role": user["role"],
        "asesor_id": user["asesor_id"]
    }

# ─── USER MANAGEMENT (admin only) ─────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    password: str
    nombre: str
    role: str = "vendedor"
    asesor_id: int | None = None
    telegram_chat_id: str | None = None

class PasswordChange(BaseModel):
    current_password: str
    new_password: str

@app.get("/api/users")
async def get_users(request: Request):
    require_admin(request)
    conn = get_db()
    rows = conn.execute(
        """SELECT u.*, a.nombre as asesor_nombre
           FROM users u LEFT JOIN asesores a ON u.asesor_id=a.id
           ORDER BY u.role DESC, u.nombre"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/users")
async def create_user(data: UserCreate, request: Request):
    require_admin(request)
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, nombre, asesor_id, telegram_chat_id) VALUES (?,?,?,?,?,?)",
            (data.username.strip().lower(), hash_password(data.password), data.role if hasattr(data, "role") and data.role in ["admin","vendedor","asesor","productor"] else "vendedor", data.nombre, data.asesor_id, data.telegram_chat_id)
        )
        conn.commit()
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return {"status": "ok", "user_id": user_id}
    except Exception as e:
        conn.close()
        raise HTTPException(400, f"Error: {str(e)}")

@app.put("/api/users/{user_id}")
async def update_user(user_id: int, data: UserCreate, request: Request):
    require_admin(request)
    conn = get_db()
    if data.password:
        conn.execute(
            "UPDATE users SET username=?, password_hash=?, nombre=?, asesor_id=?, telegram_chat_id=? WHERE id=?",
            (data.username.strip().lower(), hash_password(data.password), data.nombre, data.asesor_id, data.telegram_chat_id, user_id)
        )
    else:
        conn.execute(
            "UPDATE users SET username=?, nombre=?, asesor_id=?, telegram_chat_id=? WHERE id=?",
            (data.username.strip().lower(), data.nombre, data.asesor_id, data.telegram_chat_id, user_id)
        )
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int, request: Request):
    require_admin(request)
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id=? AND role != 'admin'", (user_id,))
    conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.put("/api/users/{user_id}/telegram")
async def update_user_telegram(user_id: int, request: Request):
    require_admin(request)
    data = await request.json()
    conn = get_db()
    conn.execute("UPDATE users SET telegram_chat_id=? WHERE id=?", (data.get("telegram_chat_id"), user_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.post("/api/users/{user_id}/telegram-test")
async def test_user_telegram(user_id: int, request: Request):
    require_admin(request)
    conn = get_db()
    user = conn.execute("SELECT nombre, telegram_chat_id FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    if not user["telegram_chat_id"]:
        raise HTTPException(400, "Este usuario no tiene Telegram configurado")
    msg = f"🔔 <b>Mensaje de prueba</b>\n\nHola {user['nombre']}, tu Telegram está correctamente configurado en el sistema de Prevención Salud."
    await send_telegram_to(user["telegram_chat_id"], msg)
    return {"status": "ok"}

@app.put("/api/asesores/{asesor_id}/telegram")
async def update_asesor_telegram(asesor_id: int, request: Request):
    require_admin(request)
    data = await request.json()
    conn = get_db()
    conn.execute("UPDATE asesores SET telegram_chat_id=? WHERE id=?", (data.get("telegram_chat_id"), asesor_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.post("/api/asesores/{asesor_id}/telegram-test")
async def test_asesor_telegram(asesor_id: int, request: Request):
    require_admin(request)
    conn = get_db()
    asesor = conn.execute("SELECT nombre, telegram_chat_id FROM asesores WHERE id=?", (asesor_id,)).fetchone()
    conn.close()
    if not asesor:
        raise HTTPException(404, "Asesor no encontrado")
    if not asesor["telegram_chat_id"]:
        raise HTTPException(400, "Este asesor no tiene Telegram configurado")
    msg = f"🔔 <b>Mensaje de prueba — Prevención Marketing System</b>\n\nHola {asesor['nombre']}, tu Telegram está correctamente configurado. A partir de ahora vas a recibir notificaciones de:\n\n• Nuevos leads que te asignen\n• Resumen de calificación\n• Mensajes nuevos de tus clientes\n• Alertas de leads sin gestionar"
    await send_telegram_to(asesor["telegram_chat_id"], msg)
    return {"status": "ok"}

@app.post("/api/auth/change-password")
async def change_password(data: PasswordChange, request: Request):
    user = require_auth(request)
    conn = get_db()
    db_user = conn.execute("SELECT * FROM users WHERE id=?", (user["user_id"],)).fetchone()
    if not verify_password(data.current_password, db_user["password_hash"]):
        conn.close()
        raise HTTPException(400, "Contraseña actual incorrecta")
    conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                 (hash_password(data.new_password), user["user_id"]))
    conn.commit()
    conn.close()
    return {"status": "ok"}

# ─── ASESOR-FILTERED ENDPOINTS ────────────────────────────────────────────────

@app.get("/api/my-conversations")
async def get_my_conversations(request: Request):
    """Conversaciones filtradas por asesor logueado."""
    user = require_auth(request)
    conn = get_db()
    if user["role"] == "admin":
        rows = conn.execute("SELECT * FROM conversations ORDER BY last_message_at DESC").fetchall()
    else:
        asesor_id = user["asesor_id"]
        rows = conn.execute(
            """SELECT c.* FROM conversations c
               JOIN leads l ON l.contact_phone=c.contact_phone
               WHERE l.asesor_id=?
               ORDER BY c.last_message_at DESC""",
            (asesor_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/my-stats")
async def get_my_stats(request: Request):
    """Estadísticas personales del vendedor logueado."""
    user = require_auth(request)
    conn = get_db()
    if user["role"] == "admin":
        total_leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        leads_hoy   = conn.execute("SELECT COUNT(*) FROM leads WHERE date(created_at)=date('now')").fetchone()[0]
        respondieron= conn.execute("SELECT COUNT(*) FROM conversations WHERE unread>0").fetchone()[0]
        total_convs = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    else:
        aid = user["asesor_id"]
        total_leads = conn.execute("SELECT COUNT(*) FROM leads WHERE asesor_id=?", (aid,)).fetchone()[0]
        leads_hoy   = conn.execute("SELECT COUNT(*) FROM leads WHERE asesor_id=? AND date(created_at)=date('now')", (aid,)).fetchone()[0]
        respondieron= conn.execute("""SELECT COUNT(*) FROM conversations c
                                      JOIN leads l ON l.contact_phone=c.contact_phone
                                      WHERE l.asesor_id=? AND c.unread>0""", (aid,)).fetchone()[0]
        total_convs = conn.execute("""SELECT COUNT(*) FROM conversations c
                                      JOIN leads l ON l.contact_phone=c.contact_phone
                                      WHERE l.asesor_id=?""", (aid,)).fetchone()[0]
    conn.close()
    return {
        "total_leads": total_leads,
        "leads_hoy": leads_hoy,
        "respondieron": respondieron,
        "total_conversaciones": total_convs
    }

@app.get("/api/my-leads")
async def get_my_leads(request: Request):
    """Leads filtrados por rol del usuario logueado."""
    user = require_auth(request)
    conn = get_db()
    if user["role"] == "admin":
        rows = conn.execute(
            """SELECT l.*, a.nombre as asesor_nombre, p.nombre as productor_nombre 
               FROM leads l
               LEFT JOIN asesores a ON l.asesor_id=a.id
               LEFT JOIN users p ON l.productor_id=p.id
               ORDER BY l.created_at DESC"""
        ).fetchall()
    elif user["role"] == "productor":
        rows = conn.execute(
            """SELECT l.*, a.nombre as asesor_nombre, p.nombre as productor_nombre
               FROM leads l
               LEFT JOIN asesores a ON l.asesor_id=a.id
               LEFT JOIN users p ON l.productor_id=p.id
               WHERE l.productor_id=?
               ORDER BY l.created_at DESC""",
            (user["user_id"],)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT l.*, a.nombre as asesor_nombre, p.nombre as productor_nombre
               FROM leads l
               LEFT JOIN asesores a ON l.asesor_id=a.id
               LEFT JOIN users p ON l.productor_id=p.id
               WHERE l.asesor_id=?
               ORDER BY l.created_at DESC""",
            (user["asesor_id"],)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ─── LEADS ENDPOINTS ──────────────────────────────────────────────────────────

@app.get("/api/leads")
def get_leads(request: Request, status: str = ""):
    require_auth(request)
    conn = get_db()
    base = """SELECT l.*, a.nombre as asesor_nombre
              FROM leads l LEFT JOIN asesores a ON l.asesor_id=a.id"""
    if status:
        rows = conn.execute(f"{base} WHERE l.puente_status=? ORDER BY l.created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute(f"{base} ORDER BY l.created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/leads/{lead_id}/cargar-puente")
async def retry_puente(lead_id: int, request: Request):
    """Reintenta la carga en Puente Digital manualmente."""
    require_auth(request)
    conn = get_db()
    lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        conn.close(); raise HTTPException(404)
    
    # Obtener credenciales del asesor asignado
    asesor = None
    if lead["asesor_id"]:
        asesor = conn.execute("SELECT * FROM asesores WHERE id=?", (lead["asesor_id"],)).fetchone()
    asesor_puente_user = (asesor["puente_user"] if asesor and asesor["puente_user"] else "") or ""
    asesor_puente_pass = (asesor["puente_password"] if asesor and asesor["puente_password"] else "") or ""
    effective_user = asesor_puente_user or PUENTE_USER
    effective_pass = asesor_puente_pass or PUENTE_PASSWORD
    demo = not (effective_user and effective_pass)
    
    result = await cargar_contacto_puente_digital(
        dni=lead["dni"] or "",
        localidad=lead["localidad"] or "",
        codigo_postal=lead["codigo_postal"] or "" if "codigo_postal" in lead.keys() else "",
        codigo_area=lead["codigo_area"] or "",
        celular=lead["celular"] or "",
        demo_mode=demo,
        username=effective_user,
        password=effective_pass
    )
    conn.execute("UPDATE leads SET puente_status=?, puente_message=? WHERE id=?",
                 ("success" if result["success"] else "error", result["message"], lead_id))
    conn.commit(); conn.close()
    return result

# ─── ASESORES ENDPOINTS ───────────────────────────────────────────────────────

@app.get("/api/asesores")
def get_asesores(request: Request):
    require_auth(request)
    conn = get_db()
    rows = conn.execute("SELECT * FROM asesores ORDER BY nombre").fetchall()
    conn.close()
    return [dict(r) for r in rows]

class AsesorCreate(BaseModel):
    nombre: str
    email: str = ""
    telegram_chat_id: str = ""
    porcentaje: int = 0
    puente_user: str = ""
    puente_password: str | None = None

@app.post("/api/asesores")
def create_asesor(data: AsesorCreate, request: Request):
    require_admin(request)
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO asesores (nombre, email, telegram_chat_id, porcentaje, puente_user, puente_password) VALUES (?,?,?,?,?,?)",
        (data.nombre, data.email, data.telegram_chat_id, data.porcentaje, data.puente_user, data.puente_password)
    )
    conn.commit()
    asesor_id = cur.lastrowid
    conn.close()
    return {"id": asesor_id}

@app.put("/api/asesores/{asesor_id}")
async def update_asesor(asesor_id: int, data: AsesorCreate, request: Request):
    require_admin(request)
    conn = get_db()
    if data.puente_password:
        conn.execute(
            "UPDATE asesores SET nombre=?, email=?, telegram_chat_id=?, porcentaje=?, puente_user=?, puente_password=? WHERE id=?",
            (data.nombre, data.email, data.telegram_chat_id, data.porcentaje, data.puente_user, data.puente_password, asesor_id)
        )
    else:
        conn.execute(
            "UPDATE asesores SET nombre=?, email=?, telegram_chat_id=?, porcentaje=?, puente_user=? WHERE id=?",
            (data.nombre, data.email, data.telegram_chat_id, data.porcentaje, data.puente_user, asesor_id)
        )
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.delete("/api/asesores/{asesor_id}")
def delete_asesor(asesor_id: int, request: Request):
    require_admin(request)
    conn = get_db()
    conn.execute("DELETE FROM asesores WHERE id=?", (asesor_id,))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.get("/api/my-puente-config")
async def get_my_puente_config(request: Request):
    """Devuelve las credenciales de Puente y Telegram del asesor logueado."""
    user = require_auth(request)
    if not user["asesor_id"]:
        return {"puente_user": "", "has_password": False, "telegram_chat_id": ""}
    conn = get_db()
    asesor = conn.execute("SELECT puente_user, puente_password, telegram_chat_id FROM asesores WHERE id=?", (user["asesor_id"],)).fetchone()
    conn.close()
    if not asesor:
        return {"puente_user": "", "has_password": False, "telegram_chat_id": ""}
    return {"puente_user": asesor["puente_user"] or "", "has_password": bool(asesor["puente_password"]), "telegram_chat_id": asesor["telegram_chat_id"] or ""}

@app.post("/api/my-puente-config")
async def set_my_puente_config(request: Request):
    """Permite al asesor configurar sus credenciales de Puente y Telegram."""
    user = require_auth(request)
    if not user["asesor_id"]:
        raise HTTPException(400, "No tenés un asesor vinculado")
    data = await request.json()
    conn = get_db()
    updates = []
    params = []
    if "puente_user" in data:
        updates.append("puente_user=?")
        params.append(data["puente_user"])
    if data.get("puente_password"):
        updates.append("puente_password=?")
        params.append(data["puente_password"])
    if "telegram_chat_id" in data:
        updates.append("telegram_chat_id=?")
        params.append(data["telegram_chat_id"])
    if updates:
        params.append(user["asesor_id"])
        conn.execute(f"UPDATE asesores SET {','.join(updates)} WHERE id=?", params)
        conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/my-telegram")
async def get_my_telegram(request: Request):
    """Devuelve el telegram_chat_id del usuario logueado."""
    user = require_auth(request)
    conn = get_db()
    row = conn.execute("SELECT telegram_chat_id FROM users WHERE id=?", (user["user_id"],)).fetchone()
    conn.close()
    return {"telegram_chat_id": row["telegram_chat_id"] if row else None}

@app.post("/api/my-telegram")
async def set_my_telegram(request: Request):
    """Permite al usuario configurar su propio telegram_chat_id."""
    user = require_auth(request)
    data = await request.json()
    conn = get_db()
    conn.execute("UPDATE users SET telegram_chat_id=? WHERE id=?", (data.get("telegram_chat_id"), user["user_id"]))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/my-telegram/test")
async def test_my_telegram(request: Request):
    """Envía un mensaje de prueba al telegram del usuario logueado."""
    user = require_auth(request)
    conn = get_db()
    row = conn.execute("SELECT nombre, telegram_chat_id FROM users WHERE id=?", (user["user_id"],)).fetchone()
    conn.close()
    if not row or not row["telegram_chat_id"]:
        raise HTTPException(400, "No tenés Telegram configurado")
    msg = f"🔔 <b>Mensaje de prueba</b>\n\nHola {row['nombre']}, tu Telegram está correctamente configurado."
    await send_telegram_to(row["telegram_chat_id"], msg)
    return {"ok": True}

# ─── AI CONVERSATION ENDPOINTS ────────────────────────────────────────────────

@app.get("/api/ai-conversations")
def get_ai_conversations(request: Request):
    require_auth(request)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM ai_conversations ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/ai/simulate-reply")
async def simulate_ai_reply(request: Request):
    """Para demo: simula que un contacto responde y la IA procesa."""
    data = await request.json()
    phone = data.get("phone")
    name = data.get("name")
    message = data.get("message")
    campaign_id = data.get("campaign_id")
    reply = await handle_ai_reply(phone, name, message, campaign_id)
    return {"ai_reply": reply}

@app.get("/api/stats")
async def get_stats(request: Request):
    user = require_auth(request)
    conn = get_db()
    total_contacts  = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    total_campaigns = conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0]
    if user["role"] == "admin":
        unread_notifs = conn.execute("SELECT COUNT(*) FROM notifications WHERE read=0").fetchone()[0]
        unread_convs  = conn.execute("SELECT COALESCE(SUM(unread),0) FROM conversations").fetchone()[0]
    else:
        asesor_id = user["asesor_id"]
        if asesor_id:
            phones = [r[0] for r in conn.execute(
                "SELECT DISTINCT contact_phone FROM leads WHERE asesor_id=?", (asesor_id,)
            ).fetchall()]
            if phones:
                ph = ",".join("?"*len(phones))
                unread_notifs = conn.execute(f"SELECT COUNT(*) FROM notifications WHERE read=0 AND contact_phone IN ({ph})", phones).fetchone()[0]
                unread_convs  = conn.execute(f"SELECT COALESCE(SUM(unread),0) FROM conversations WHERE contact_phone IN ({ph})", phones).fetchone()[0]
            else:
                unread_notifs = 0; unread_convs = 0
        else:
            unread_notifs = 0; unread_convs = 0
    total_leads     = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    leads_pending   = conn.execute("SELECT COUNT(*) FROM leads WHERE puente_status='pending'").fetchone()[0]
    conn.close()
    return {
        "total_contacts": total_contacts, "total_campaigns": total_campaigns,
        "unread_notifications": unread_notifs, "unread_conversations": unread_convs,
        "total_leads": total_leads, "leads_pending": leads_pending
    }

@app.get("/api/agent-config")
def get_agent_config_endpoint(request: Request):
    require_auth(request)
    from ai_agent import get_agent_config
    return get_agent_config()

@app.post("/api/agent-config")
async def save_agent_config_endpoint(request: Request):
    require_admin(request)
    from ai_agent import save_agent_config
    data = await request.json()
    save_agent_config(data.get("name", "").strip())
    return {"status": "ok"}

@app.get("/api/planes-info")
def get_planes_info(request: Request):
    """Obtiene la información adicional de planes cargada desde el panel."""
    require_auth(request)
    from ai_agent import get_extra_info
    return {"content": get_extra_info()}

@app.post("/api/planes-info")
async def save_planes_info(request: Request):
    """Guarda información adicional de planes (precios, novedades, etc.)."""
    require_admin(request)
    from ai_agent import save_extra_info
    data = await request.json()
    text = data.get("content", "").strip()
    save_extra_info(text)
    return {"status": "ok", "chars": len(text)}

@app.get("/api/telegram/status")
def telegram_status(request: Request):
    """Verifica si Telegram está configurado."""
    require_auth(request)
    configured = bool(TG_BOT_TOKEN and TG_CHAT_ID)
    return {"configured": configured, "chat_id": TG_CHAT_ID if configured else None}

@app.post("/api/telegram/test")
async def telegram_test(request: Request):
    """Envía un mensaje de prueba al bot."""
    require_auth(request)
    await send_telegram("✅ <b>Prevención Marketing System</b>\n\nNotificaciones de Telegram configuradas correctamente. A partir de ahora recibirás avisos de lecturas y respuestas aquí.")
    return {"status": "ok"}

@app.post("/api/telegram/configure")
async def telegram_configure(request: Request):
    """Guarda token y chat_id en un archivo .env local."""
    require_admin(request)
    global TG_BOT_TOKEN, TG_CHAT_ID
    data = await request.json()
    token = data.get("token", "").strip()
    chat_id = data.get("chat_id", "").strip()
    if not token or not chat_id:
        raise HTTPException(400, "Token y Chat ID son requeridos")
    TG_BOT_TOKEN = token
    TG_CHAT_ID = chat_id
    # Guardar en archivo para persistencia
    with open("/app/data/.env_telegram", "w") as f:
        f.write(f"TG_BOT_TOKEN={token}\nTG_CHAT_ID={chat_id}\n")
    await send_telegram("✅ <b>Prevención Marketing System</b>\n\n¡Notificaciones configuradas! Recibirás avisos de lecturas y respuestas aquí.")
    return {"status": "ok", "message": "Telegram configurado y mensaje de prueba enviado"}

@app.get("/privacidad")
def privacidad():
    from fastapi.responses import HTMLResponse
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<title>Política de Privacidad</title>
<style>body{font-family:Arial,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;color:#333;line-height:1.6}h1{color:#0F2557}h2{color:#1A3570;margin-top:24px}</style>
</head><body>
<h1>Política de Privacidad</h1>
<p><strong>Última actualización:</strong> Abril 2026</p>
<h2>1. Información que recopilamos</h2>
<p>Recopilamos nombre, número de teléfono, DNI y localidad de residencia, proporcionados voluntariamente durante la conversación.</p>
<h2>2. Uso de la información</h2>
<p>Los datos se utilizan exclusivamente para brindar asesoramiento sobre planes de cobertura médica de Prevención Salud (Sancor Seguros).</p>
<h2>3. Compartición de datos</h2>
<p>Los datos no se comparten con terceros salvo con Prevención Salud (Sancor Seguros) a los fines del servicio solicitado.</p>
<h2>4. Almacenamiento y seguridad</h2>
<p>Los datos se almacenan en servidores seguros y se conservan únicamente el tiempo necesario para prestar el servicio.</p>
<h2>5. Derechos del usuario</h2>
<p>El usuario puede solicitar acceso, rectificación o eliminación de sus datos respondiendo al mensaje de WhatsApp.</p>
<h2>6. Contacto</h2>
<p>Para consultas sobre esta política, contactarse por WhatsApp al número desde el cual recibió el mensaje.</p>
</body></html>"""
    return HTMLResponse(content=html)

@app.get("/api/templates")
async def get_templates(request: Request):
    require_auth(request)
    if not WA_TOKEN or not WA_WABA_ID:
        return [{"name": "prevencion_contacto_inicial", "language": "es_AR", "text": "Template por defecto", "header_type": None, "header_example": None}]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://graph.facebook.com/v19.0/{WA_WABA_ID}/message_templates",
                headers={"Authorization": f"Bearer {WA_TOKEN}"},
                params={"status": "APPROVED", "limit": 20}
            )
            data = resp.json()
            templates = []
            for t in data.get("data", []):
                components = t.get("components", [])
                body = next((c["text"] for c in components if c["type"]=="BODY"), "")
                header = next((c for c in components if c["type"]=="HEADER"), None)
                header_type = header.get("format") if header else None
                header_example = None
                if header and header_type == "IMAGE":
                    ex = header.get("example", {})
                    handles = ex.get("header_handle", [])
                    header_example = handles[0] if handles else None
                templates.append({
                    "name": t["name"],
                    "language": t.get("language",""),
                    "text": body,
                    "header_type": header_type,
                    "header_example": header_example
                })
            return templates
    except Exception as e:
        print(f"Templates error: {e}")
        return [{"name": "prevencion_contacto_inicial", "language": "es_AR", "text": "Error al cargar", "header_type": None, "header_example": None}]

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == os.getenv("VERIFY_TOKEN","demo_token") and params.get("hub.mode") == "subscribe":
        return int(params["hub.challenge"])
    raise HTTPException(403)

@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        data = await request.json()
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # Estados de mensaje
                for status in value.get("statuses", []):
                    wa_id = status.get("id"); st = status.get("status")
                    ts = datetime.fromtimestamp(int(status.get("timestamp",0)), tz=TZ_AR).isoformat()
                    conn = get_db()
                    msg = conn.execute("SELECT * FROM messages WHERE wa_message_id=?", (wa_id,)).fetchone()
                    if msg:
                        if st == "delivered":
                            conn.execute("UPDATE messages SET status='delivered',delivered_at=? WHERE wa_message_id=?", (ts,wa_id))
                            conn.execute("UPDATE campaigns SET delivered=delivered+1 WHERE id=?", (msg["campaign_id"],))
                        elif st == "read":
                            conn.execute("UPDATE messages SET status='read',read_at=? WHERE wa_message_id=?", (ts,wa_id))
                            conn.execute("UPDATE campaigns SET read_count=read_count+1 WHERE id=?", (msg["campaign_id"],))
                            conn.execute("INSERT INTO notifications (type,contact_name,contact_phone,message,campaign_id) VALUES (?,?,?,?,?)",
                                         ("read",msg["name"],msg["phone"],"Leyó tu mensaje",msg["campaign_id"]))
                            # Solo notificar Telegram si es lead calificado
                            lead_check = conn.execute("SELECT id FROM leads WHERE contact_phone LIKE ?", (f"%{msg['phone'][-9:]}%",)).fetchone()
                            if lead_check:
                                await send_telegram(f"👁️ <b>{msg['name']}</b> leyó tu mensaje\n📱 {msg['phone']}")
                        conn.commit()
                    conn.close()

                # Mensajes entrantes
                for message in value.get("messages", []):
                    phone = message.get("from")
                    text  = message.get("text", {}).get("body", "")
                    # Media incoming
                    media_type_in = None; media_url_in = None; media_name_in = None
                    for mtype in ["image","document","audio","video"]:
                        if mtype in message:
                            media_type_in = mtype
                            media_id_in = message[mtype].get("id")
                            media_mime = message[mtype].get("mime_type", "image/jpeg")
                            media_name_in = message[mtype].get("filename", mtype)
                            # Descargar media de Meta y guardar como base64
                            try:
                                async with httpx.AsyncClient(timeout=15) as _cl:
                                    # Paso 1: obtener URL de descarga
                                    _r = await _cl.get(f"https://graph.facebook.com/v19.0/{media_id_in}",
                                                        headers={"Authorization":f"Bearer {WA_TOKEN}"})
                                    download_url = _r.json().get("url","")
                                    if download_url:
                                        # Paso 2: descargar el binario
                                        _r2 = await _cl.get(download_url,
                                                            headers={"Authorization":f"Bearer {WA_TOKEN}"})
                                        if _r2.status_code == 200:
                                            media_b64 = base64.b64encode(_r2.content).decode()
                                            media_url_in = f"data:{media_mime};base64,{media_b64}"
                                        else:
                                            print(f"Media download failed: {_r2.status_code}")
                            except Exception as _e:
                                print(f"Media download error: {_e}")
                            break
                    ts    = datetime.fromtimestamp(int(message.get("timestamp",0)), tz=TZ_AR).isoformat()
                    contacts = value.get("contacts", [])
                    contact_name = contacts[0]["profile"]["name"] if contacts else phone
                    conn = get_db()
                    msg = conn.execute("SELECT * FROM messages WHERE phone LIKE ?", (f"%{phone[-9:]}%",)).fetchone()
                    if msg:
                        conn.execute("UPDATE messages SET status='replied',replied_at=?,reply_text=? WHERE id=?", (ts,text,msg["id"]))
                        conn.execute("UPDATE campaigns SET replied=replied+1 WHERE id=?", (msg["campaign_id"],))
                        conn.execute("INSERT INTO notifications (type,contact_name,contact_phone,message,campaign_id) VALUES (?,?,?,?,?)",
                                     ("reply",msg["name"],phone,text,msg["campaign_id"]))
                        contact_name = msg["name"]
                    else:
                        conn.execute("INSERT INTO notifications (type,contact_name,contact_phone,message) VALUES (?,?,?,?)",
                                     ("reply",contact_name,phone,text))
                    # Upsert conversación
                    existing = conn.execute("SELECT id FROM conversations WHERE contact_phone=?", (phone,)).fetchone()
                    if existing:
                        conn.execute("UPDATE conversations SET contact_name=?,last_message=?,last_message_at=?,unread=unread+1 WHERE id=?",
                                     (contact_name,text,ts,existing["id"]))
                        conv_id = existing["id"]
                    else:
                        cur = conn.execute("INSERT INTO conversations (contact_name,contact_phone,last_message,last_message_at,unread) VALUES (?,?,?,?,1)",
                                          (contact_name,phone,text,ts))
                        conv_id = cur.lastrowid
                    conn.execute("INSERT INTO chat_messages (conversation_id,direction,body,media_type,media_url,media_name) VALUES (?,?,?,?,?,?)",
                                     (conv_id,"in",text,media_type_in,media_url_in,media_name_in))
                    conn.commit(); conn.close()
                    # Solo notificar Telegram si ya es lead calificado
                    _conn2 = get_db()
                    lead = _conn2.execute("SELECT id, productor_id, asesor_id FROM leads WHERE contact_phone LIKE ?", (f"%{phone[-9:]}%",)).fetchone()
                    if lead:
                        msg_notif = f"💬 <b>{contact_name}</b>:\n\n\"{text}\"\n\n📱 {phone}"
                        # Notificar SOLO al asesor asignado (tabla asesores)
                        if lead["asesor_id"]:
                            asesor = _conn2.execute("SELECT telegram_chat_id FROM asesores WHERE id=?", (lead["asesor_id"],)).fetchone()
                            if asesor and asesor["telegram_chat_id"]:
                                try:
                                    await send_telegram_to(asesor["telegram_chat_id"], msg_notif)
                                except:
                                    pass
                        # Notificar al productor si tiene
                        if lead["productor_id"]:
                            prod = _conn2.execute("SELECT telegram_chat_id FROM users WHERE id=?", (lead["productor_id"],)).fetchone()
                            if prod and prod["telegram_chat_id"]:
                                try:
                                    await send_telegram_to(prod["telegram_chat_id"], msg_notif)
                                except:
                                    pass
                        # Los admins NO reciben notif de mensajes nuevos
                    _conn2.close()
                    # Procesar con IA (solo si hay texto)
                    if text.strip():
                        campaign_id = msg["campaign_id"] if msg else None
                        await handle_ai_reply(phone, contact_name, text, campaign_id)
        return {"status": "ok"}
    except Exception as e:
        import sys, traceback
        print(f"Webhook error: {e}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return {"status": "ok"}

@app.get("/")
def serve_frontend():
    return FileResponse("index.html")

# ─── Proxy de archivos opus-media-recorder (para evitar cross-origin de los workers) ──
_OPUS_CACHE = {}  # filename -> bytes
_OPUS_URLS = {
    "encoderWorker.umd.js": "https://cdn.jsdelivr.net/npm/opus-media-recorder@0.8.0/encoderWorker.umd.js",
    "OggOpusEncoder.wasm":  "https://cdn.jsdelivr.net/npm/opus-media-recorder@0.8.0/OggOpusEncoder.wasm",
    "WebMOpusEncoder.wasm": "https://cdn.jsdelivr.net/npm/opus-media-recorder@0.8.0/WebMOpusEncoder.wasm",
    "OpusMediaRecorder.umd.js": "https://cdn.jsdelivr.net/npm/opus-media-recorder@0.8.0/OpusMediaRecorder.umd.js",
}

@app.get("/opus/{filename}")
async def opus_proxy(filename: str):
    """Proxea los assets de opus-media-recorder al mismo dominio para evitar problemas
    de fetch cross-origin desde dentro de un Worker."""
    if filename not in _OPUS_URLS:
        raise HTTPException(404, "asset desconocido")
    # Cache en memoria
    if filename not in _OPUS_CACHE:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(_OPUS_URLS[filename])
                if r.status_code != 200:
                    raise HTTPException(502, f"upstream {r.status_code}")
                _OPUS_CACHE[filename] = r.content
        except Exception as e:
            raise HTTPException(502, f"error proxy: {e}")
    from fastapi.responses import Response
    if filename.endswith(".wasm"):
        media = "application/wasm"
    elif filename.endswith(".js"):
        media = "application/javascript"
    else:
        media = "application/octet-stream"
    return Response(content=_OPUS_CACHE[filename], media_type=media,
                    headers={"Cache-Control": "public, max-age=31536000"})

# ─── MARCAR LEAD COMO COMPLETADO ─────────────────────────────────────────────
@app.post("/api/leads/{lead_id}/completar")
async def mark_lead_completed(lead_id: int, request: Request):
    require_auth(request)
    conn = get_db()
    lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        conn.close()
        raise HTTPException(404, "Lead no encontrado")
    conn.execute("UPDATE leads SET lead_status='completado' WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "message": "Lead marcado como completado"}

@app.post("/api/leads/{lead_id}/reactivar")
async def reactivate_lead(lead_id: int, request: Request):
    require_auth(request)
    conn = get_db()
    lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        conn.close()
        raise HTTPException(404, "Lead no encontrado")
    conn.execute("UPDATE leads SET lead_status='active' WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "message": "Lead reactivado"}

@app.post("/api/leads/{lead_id}/clasificar")
async def clasificar_lead(lead_id: int, request: Request):
    require_auth(request)
    data = await request.json()
    clasificacion = data.get("clasificacion", "En gestión")
    conn = get_db()
    lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        conn.close()
        raise HTTPException(404, "Lead no encontrado")
    conn.execute(
        "UPDATE leads SET clasificacion=? WHERE id=?",
        (clasificacion, lead_id)
    )
    conn.commit()
    conn.close()
    return {"ok": True, "clasificacion": clasificacion}

@app.post("/api/leads/{lead_id}/recordatorio")
async def set_recordatorio(lead_id: int, request: Request):
    require_auth(request)
    data = await request.json()
    recordatorio_fecha = data.get("recordatorio_fecha")
    conn = get_db()
    lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        conn.close()
        raise HTTPException(404, "Lead no encontrado")
    conn.execute(
        "UPDATE leads SET recordatorio_fecha=?, recordatorio_notificado=0 WHERE id=?",
        (recordatorio_fecha, lead_id)
    )
    conn.commit()
    conn.close()
    return {"ok": True, "recordatorio_fecha": recordatorio_fecha}

@app.post("/api/leads/{lead_id}/asignar-productor")
async def asignar_productor(lead_id: int, request: Request):
    require_admin(request)
    data = await request.json()
    productor_id = data.get("productor_id")
    conn = get_db()
    lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        conn.close()
        raise HTTPException(404, "Lead no encontrado")
    conn.execute("UPDATE leads SET productor_id=? WHERE id=?", (productor_id, lead_id))
    conn.commit()
    # Notificar al productor por Telegram
    if productor_id:
        productor = conn.execute("SELECT nombre, telegram_chat_id FROM users WHERE id=?", (productor_id,)).fetchone()
        if productor and productor["telegram_chat_id"]:
            msg = (
                f"🎯 <b>Lead asignado</b>\n\n"
                f"👤 {lead['contact_name']}\n"
                f"📱 {lead['contact_phone']}\n"
                f"🪪 DNI: {lead['dni'] or '—'}\n"
                f"📍 {lead['localidad'] or '—'}"
            )
            try:
                await send_telegram_to(productor["telegram_chat_id"], msg)
            except:
                pass
    conn.close()
    return {"ok": True}

@app.get("/api/productores")
async def get_productores(request: Request):
    require_auth(request)
    conn = get_db()
    rows = conn.execute("SELECT id, nombre FROM users WHERE role='productor' AND active=1 ORDER BY nombre").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/leads/{lead_id}/info")
async def get_lead_info(lead_id: int, request: Request):
    require_auth(request)
    conn = get_db()
    lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        conn.close()
        raise HTTPException(404)
    conn.close()
    return dict(lead)

# ─── BACKGROUND TASK: RECORDATORIO 23HS ──────────────────────────────────────
async def send_reminders_loop():
    """Cada 60 min revisa si hay contactos cuya ventana de 24hs está por vencer y les manda un follow-up."""
    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour
            conn = get_db()
            # Buscar leads activos (no completados) con última interacción hace ~23hs
            cutoff_min = datetime.now(TZ_AR) - timedelta(hours=23, minutes=30)
            cutoff_max = datetime.now(TZ_AR) - timedelta(hours=22, minutes=30)
            
            leads = conn.execute("""
                SELECT l.id, l.contact_phone, l.contact_name, l.lead_status,
                       ac.history, ac.updated_at, ac.conversation_complete
                FROM leads l
                JOIN ai_conversations ac ON ac.contact_phone = l.contact_phone
                WHERE l.lead_status = 'active'
            """).fetchall()
            
            for lead in leads:
                try:
                    updated = datetime.fromisoformat(lead["updated_at"]).replace(tzinfo=TZ_AR) if lead["updated_at"] else None
                    if not updated:
                        continue
                    
                    # Solo mandar si la última interacción fue hace entre 22.5 y 23.5 horas
                    if cutoff_max <= updated <= cutoff_min:
                        history = json.loads(lead["history"]) if lead["history"] else []
                        reminder = await generate_reminder_message(lead["contact_name"], history)
                        
                        # Enviar por WhatsApp
                        wa_ok = await send_whatsapp_reply(lead["contact_phone"], reminder)
                        if wa_ok:
                            # Guardar en historial
                            history.append({"role": "assistant", "content": reminder})
                            conn.execute(
                                "UPDATE ai_conversations SET history=?, updated_at=? WHERE contact_phone=?",
                                (json.dumps(history), datetime.now(TZ_AR).isoformat(), lead["contact_phone"])
                            )
                            # Guardar en bandeja de entrada
                            existing_conv = conn.execute(
                                "SELECT id FROM conversations WHERE contact_phone=?", (lead["contact_phone"],)
                            ).fetchone()
                            if existing_conv:
                                conn.execute(
                                    "INSERT INTO chat_messages (conversation_id,direction,body) VALUES (?,?,?)",
                                    (existing_conv["id"], "out", reminder)
                                )
                                conn.execute(
                                    "UPDATE conversations SET last_message=?,last_message_at=? WHERE id=?",
                                    (reminder, datetime.now(TZ_AR).isoformat(), existing_conv["id"])
                                )
                            conn.commit()
                            print(f"Reminder enviado a {lead['contact_name']} ({lead['contact_phone']})", flush=True)
                except Exception as e:
                    print(f"Error enviando reminder a {lead.get('contact_phone','?')}: {e}", flush=True)
            
            conn.close()
        except Exception as e:
            print(f"Error en send_reminders_loop: {e}", flush=True)

# ─── BACKGROUND TASK: RECORDATORIOS DE LEADS ─────────────────────────────────
async def check_lead_recordatorios():
    """Cada 30 min revisa leads con recordatorio próximo y notifica."""
    while True:
        try:
            await asyncio.sleep(1800)  # Check every 30 min
            conn = get_db()
            now = datetime.now(TZ_AR)
            today_str = now.strftime("%Y-%m-%d")
            tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

            # Buscar leads con recordatorio para hoy o mañana, no notificados aún
            leads = conn.execute("""
                SELECT l.*, a.telegram_chat_id, a.nombre as asesor_nombre
                FROM leads l
                LEFT JOIN asesores a ON l.asesor_id = a.id
                WHERE l.recordatorio_fecha IS NOT NULL
                  AND l.recordatorio_notificado = 0
                  AND l.recordatorio_fecha <= ?
                ORDER BY l.recordatorio_fecha ASC
            """, (tomorrow_str,)).fetchall()

            for lead in leads:
                try:
                    fecha = lead["recordatorio_fecha"]
                    es_hoy = fecha == today_str
                    es_pasado = fecha < today_str
                    label = "📅 HOY" if es_hoy else ("⚠️ VENCIDO" if es_pasado else "📅 MAÑANA")

                    # Crear notificación en el panel
                    conn.execute(
                        "INSERT INTO notifications (type,contact_name,contact_phone,message) VALUES (?,?,?,?)",
                        ("reply", lead["contact_name"], lead["contact_phone"],
                         f"{label} — Recordatorio de contacto ({fecha})")
                    )

                    # Notificar por Telegram al asesor
                    if lead["telegram_chat_id"]:
                        try:
                            msg = (
                                f"{label} <b>Recordatorio de lead</b>\n\n"
                                f"👤 {lead['contact_name']}\n"
                                f"📱 {lead['contact_phone']}\n"
                                f"📊 Estado: {lead.get('clasificacion', 'Pendiente')}\n"
                                f"📅 Fecha programada: {fecha}"
                            )
                            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
                            async with httpx.AsyncClient(timeout=10) as client:
                                await client.post(url, json={
                                    "chat_id": lead["telegram_chat_id"],
                                    "text": msg,
                                    "parse_mode": "HTML"
                                })
                        except Exception as e:
                            print(f"Error telegram recordatorio: {e}", flush=True)
                    
                    # NO se envía al canal general — solo al asesor asignado arriba

                    # Marcar como notificado si es hoy o pasado
                    if es_hoy or es_pasado:
                        conn.execute("UPDATE leads SET recordatorio_notificado=1 WHERE id=?", (lead["id"],))

                except Exception as e:
                    print(f"Error procesando recordatorio lead {lead.get('id','?')}: {e}", flush=True)

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error en check_lead_recordatorios: {e}", flush=True)

# ─── SCHEDULER JOBS ─────────────────────────────────────────────────────────

async def job_timeout_conversaciones():
    """Cada minuto: cierra convs con DNI hace más de 5 min sin completarse y manda resumen."""
    try:
        conn = get_db()
        cutoff = (datetime.now(TZ_AR) - timedelta(minutes=5)).isoformat()
        pendientes = conn.execute("""
            SELECT * FROM ai_conversations
            WHERE qualified=1 AND conversation_complete=0
            AND updated_at < ?
        """, (cutoff,)).fetchall()

        for conv in pendientes:
            phone = conv["contact_phone"]
            name = conv["contact_name"]
            dni = conv["dni"] or "—"
            post = {
                "localidad": conv["post_localidad"] or "No contestado",
                "situacion_laboral": conv["post_situacion_laboral"] or "No contestado",
                "cobertura_actual": conv["post_cobertura_actual"] or "No contestado",
                "punto_dolor": conv["post_punto_dolor"] or "No contestado",
                "info_salud": conv["post_info_salud"] or "No contestado",
            }
            # Marcar como completa para que la IA no siga respondiendo
            conn.execute(
                "UPDATE ai_conversations SET conversation_complete=1, updated_at=? WHERE contact_phone=?",
                (datetime.now(TZ_AR).isoformat(), phone)
            )
            conn.commit()

            # Calificar/actualizar el lead y cargar en Puente con los datos disponibles
            campaign_id = conv["campaign_id"]
            data_for_lead = {"dni": dni, "codigo_postal": "2000", "localidad": post["localidad"]}
            await process_qualified_lead(conn, name, phone, data_for_lead, campaign_id)

            # Generar resumen y notificar
            summary = await generate_case_summary(name, dni, post)
            lead = conn.execute(
                "SELECT l.*, a.telegram_chat_id FROM leads l LEFT JOIN asesores a ON l.asesor_id=a.id WHERE l.contact_phone=?",
                (phone,)
            ).fetchone()
            asesor_chat_id = lead["telegram_chat_id"] if lead else None
            msg = f"⏱️ <b>Lead cerrado por timeout</b>\n\n{summary}"
            if asesor_chat_id:
                await send_telegram_to(asesor_chat_id, msg)
            else:
                await send_telegram(msg)

        conn.close()
    except Exception as e:
        print(f"Error job_timeout_conversaciones: {e}", file=__import__('sys').stderr, flush=True)


async def job_alerta_sin_gestion():
    """Cada minuto: notifica al asesor asignado y a admins si un lead lleva 20 min sin gestión."""
    try:
        conn = get_db()
        cutoff = (datetime.now(TZ_AR) - timedelta(minutes=20)).isoformat()
        sin_gestion = conn.execute("""
            SELECT l.*, a.nombre as asesor_nombre, a.telegram_chat_id as asesor_chat_id
            FROM leads l
            LEFT JOIN asesores a ON l.asesor_id = a.id
            WHERE l.qualified_at IS NOT NULL
              AND l.qualified_at < ?
              AND (l.gestion_notificada IS NULL OR l.gestion_notificada = 0)
        """, (cutoff,)).fetchall()

        if not sin_gestion:
            conn.close()
            return

        admins = conn.execute(
            "SELECT telegram_chat_id FROM users WHERE role='admin' AND telegram_chat_id IS NOT NULL AND telegram_chat_id != ''"
        ).fetchall()
        admin_chats = [a["telegram_chat_id"] for a in admins]

        for lead in sin_gestion:
            msg = (
                f"⚠️ <b>Lead sin gestionar</b>\n\n"
                f"👤 {lead['contact_name']}\n"
                f"📱 {lead['contact_phone']}\n"
                f"🪪 DNI: {lead['dni'] or '—'}\n"
                f"👨‍💼 Asesor asignado: {lead['asesor_nombre'] or 'Sin asignar'}\n\n"
                f"Han pasado más de 20 minutos sin gestión."
            )
            sent_to = set()
            # 1. Al asesor asignado a ESE lead específico
            if lead["asesor_chat_id"]:
                await send_telegram_to(lead["asesor_chat_id"], msg)
                sent_to.add(lead["asesor_chat_id"])
            # 2. A TODOS los admins
            for chat_id in admin_chats:
                if chat_id not in sent_to:
                    await send_telegram_to(chat_id, msg)
                    sent_to.add(chat_id)
            conn.execute(
                "UPDATE leads SET gestion_notificada=1 WHERE id=?",
                (lead["id"],)
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error job_alerta_sin_gestion: {e}", file=__import__('sys').stderr, flush=True)


async def job_timeout_inactividad_cliente():
    """Cada minuto: si pasó >= 1 hora sin que el cliente conteste, cierra y manda resumen al asesor."""
    import sys, asyncio as _aio
    try:
        conn = get_db()
        cutoff = (datetime.now(TZ_AR) - timedelta(hours=1)).isoformat()
        rows = conn.execute("""
            SELECT * FROM ai_conversations
            WHERE conversation_complete = 0
              AND (timeout_summary_sent IS NULL OR timeout_summary_sent = 0)
              AND last_user_message_at IS NOT NULL
              AND last_user_message_at < ?
        """, (cutoff,)).fetchall()
        conn.close()
        for r in rows:
            try:
                # Marcar primero para evitar doble envío
                c2 = get_db()
                c2.execute(
                    "UPDATE ai_conversations SET timeout_summary_sent=1, conversation_complete=1, updated_at=? WHERE contact_phone=?",
                    (datetime.now(TZ_AR).isoformat(), r["contact_phone"])
                )
                c2.commit()
                c2.close()

                # Armar resumen con lo que haya
                post_data = {
                    "localidad": r["post_localidad"],
                    "situacion_laboral": r["post_situacion_laboral"],
                    "cobertura_actual": r["post_cobertura_actual"],
                    "punto_dolor": r["post_punto_dolor"],
                    "info_salud": r["post_info_salud"],
                }
                post_data = {k: v for k, v in post_data.items() if v}
                dni = r["dni"] or ""
                _aio.create_task(_send_timeout_summary_bg(
                    r["contact_name"], r["contact_phone"], dni, post_data
                ))
            except Exception as e:
                print(f"[TIMEOUT 1H] error procesando {r['contact_phone']}: {e}", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[TIMEOUT 1H] error general: {e}", file=sys.stderr, flush=True)


async def _send_timeout_summary_bg(contact_name, contact_phone, dni, post_data):
    """Envía el resumen al asesor cuando hubo timeout de 1 hora sin respuesta del cliente."""
    import sys
    try:
        bg_conn = get_db()
        try:
            summary = await generate_case_summary(contact_name, dni, post_data)
            lead = bg_conn.execute(
                "SELECT l.*, a.telegram_chat_id, a.nombre as asesor_nombre FROM leads l LEFT JOIN asesores a ON l.asesor_id=a.id WHERE l.contact_phone=?",
                (contact_phone,)
            ).fetchone()
            puente_msg = lead["puente_message"] if lead else ""
            puente_status = lead["puente_status"] if lead else "pending"
            asesor_nombre = lead["asesor_nombre"] if lead else "Sin asignar"
            asesor_chat_id = lead["telegram_chat_id"] if lead else None
            asesor_id = lead["asesor_id"] if lead else None

            if puente_status == "success": puente_line = "✅ Cargado"
            elif "afiliado" in (puente_msg or "").lower() or "ya existe" in (puente_msg or "").lower():
                puente_line = "⚠️ Ya es afiliado existente"
            elif not dni:
                puente_line = "⏳ Sin DNI — no se cargó"
            else:
                puente_line = "⏳ Pendiente"

            title = "⏰ <b>Lead cerrado por inactividad (1h sin respuesta)</b>"
            msg_resumen = (
                f"{title}\n\n"
                f"{summary}\n\n"
                f"👨‍💼 Asesor: {asesor_nombre}\n"
                f"🏥 Puente Digital: {puente_line}\n"
                f"📱 WhatsApp: {contact_phone}"
            )

            sent_to = set()
            if asesor_chat_id:
                await send_telegram_to(asesor_chat_id, msg_resumen)
                sent_to.add(asesor_chat_id)
            if asesor_id:
                try:
                    linked_users = bg_conn.execute(
                        "SELECT telegram_chat_id FROM users WHERE asesor_id=? AND telegram_chat_id IS NOT NULL AND telegram_chat_id != ''",
                        (asesor_id,)
                    ).fetchall()
                    for u in linked_users:
                        if u["telegram_chat_id"] not in sent_to:
                            await send_telegram_to(u["telegram_chat_id"], msg_resumen)
                            sent_to.add(u["telegram_chat_id"])
                except: pass
        except Exception as e:
            print(f"[TIMEOUT SUMMARY] error: {e}", file=sys.stderr, flush=True)
        finally:
            bg_conn.close()
    except Exception as e:
        print(f"[TIMEOUT SUMMARY] outer error: {e}", file=sys.stderr, flush=True)


@app.on_event("startup")
async def startup_event():
    """Inicia los loops de background al arrancar el servidor."""
    asyncio.create_task(send_reminders_loop())
    asyncio.create_task(check_lead_recordatorios())
    scheduler = AsyncIOScheduler(timezone=TZ_AR)
    scheduler.add_job(job_timeout_conversaciones, "interval", minutes=1)
    scheduler.add_job(job_alerta_sin_gestion, "interval", minutes=1)
    scheduler.add_job(job_timeout_inactividad_cliente, "interval", minutes=2)
    scheduler.start()

if __name__ == "__main__":
    print("\n" + "="*55)
    print("  🟢 PREVENCIÓN MARKETING SYSTEM — DEMO")
    print("  Panel: http://localhost:8000")
    print("="*55 + "\n")
    uvicorn.run("app_demo:app", host="0.0.0.0", port=8000, reload=True)
