"""
conftest.py — Setup global de fixtures y mocks para la suite de tests.

Los mocks de módulos externos (puente_digital, ai_agent, gspread, apscheduler)
se aplican a sys.modules ANTES de importar app_demo para que los `from X import Y`
del módulo principal obtengan los mocks correctamente.
"""
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock

# ─── 1. DB en archivo temporal (se crea antes de importar app_demo) ───────────
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name

# ─── 2. Mock de módulos externos ──────────────────────────────────────────────

# puente_digital → evita que Playwright se inicie
_mock_puente = MagicMock()
_mock_puente.cargar_contacto_puente_digital = AsyncMock(
    return_value={"success": True, "message": "Mock OK"}
)
sys.modules["puente_digital"] = _mock_puente

# google sheets / google auth
sys.modules["gspread"] = MagicMock()
sys.modules["google"] = MagicMock()
sys.modules["google.oauth2"] = MagicMock()
sys.modules["google.oauth2.service_account"] = MagicMock()

# apscheduler → el scheduler no se inicia realmente
_mock_sched_inst = MagicMock()
_mock_sched_cls = MagicMock(return_value=_mock_sched_inst)
_mock_sched_mod = MagicMock()
_mock_sched_mod.AsyncIOScheduler = _mock_sched_cls
sys.modules["apscheduler"] = _mock_sched_mod
sys.modules["apscheduler.schedulers"] = _mock_sched_mod
sys.modules["apscheduler.schedulers.asyncio"] = _mock_sched_mod

# ai_agent → no llama a la API de Anthropic
_mock_ai = MagicMock()
_mock_ai.get_ai_response = AsyncMock(return_value={
    "reply": "¿Cuál es tu DNI?",
    "extracted": {},
    "dni_refused": False,
    "post_data": {},
    "conversation_complete": False,
})
_mock_ai.generate_first_message = AsyncMock(return_value="Hola, soy Valentina.")
_mock_ai.generate_case_summary = AsyncMock(return_value="Resumen del caso de prueba.")
_mock_ai.generate_reminder_message = AsyncMock(return_value="Recordatorio de prueba.")
_mock_ai.get_agent_config = MagicMock(return_value={"name": "Valentina"})
_mock_ai.save_agent_config = MagicMock()
_mock_ai.get_extra_info = MagicMock(return_value="")
_mock_ai.save_extra_info = MagicMock()
sys.modules["ai_agent"] = _mock_ai

# ─── 3. Import app DESPUÉS de los mocks ──────────────────────────────────────
import pytest
from fastapi.testclient import TestClient
from app_demo import app  # init_db() y ensure_admin() se ejecutan aquí


# ─── FIXTURES ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    """TestClient compartido en toda la sesión."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, f"Login admin falló: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def admin_hdrs(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def asesor_id(client, admin_hdrs):
    """Crea un asesor de test reutilizable en toda la sesión."""
    r = client.post("/api/asesores", json={
        "nombre": "Asesor Test Suite",
        "porcentaje": 100,
        "email": "asesor@test.com",
    }, headers=admin_hdrs)
    assert r.status_code == 200, f"Crear asesor falló: {r.text}"
    return r.json()["id"]


@pytest.fixture(scope="session")
def vendedor_token(client, admin_hdrs, asesor_id):
    """Crea un usuario vendedor vinculado al asesor de test."""
    client.post("/api/users", json={
        "username": "vendedor_test",
        "password": "vendedor123",
        "nombre": "Vendedor Test",
        "role": "vendedor",
        "asesor_id": asesor_id,
    }, headers=admin_hdrs)
    r = client.post("/api/auth/login", json={"username": "vendedor_test", "password": "vendedor123"})
    assert r.status_code == 200
    return r.json()["token"]


@pytest.fixture(scope="session")
def vendedor_hdrs(vendedor_token):
    return {"Authorization": f"Bearer {vendedor_token}"}


@pytest.fixture(scope="session")
def sample_contact_id(client, admin_hdrs):
    """Retorna el id del primer contacto demo (siempre existe por init_db)."""
    r = client.get("/api/contacts?per_page=1", headers=admin_hdrs)
    assert r.status_code == 200
    contacts = r.json()["contacts"]
    assert len(contacts) > 0, "No hay contactos demo en la DB"
    return contacts[0]["id"]


@pytest.fixture(scope="session")
def sample_campaign_id(client, sample_contact_id, admin_hdrs):
    """Crea una campaña de test y retorna su id."""
    r = client.post("/api/campaigns", json={
        "name": "Campaña Test Suite",
        "contact_ids": [sample_contact_id],
        "message_template": "Hola {{nombre}}",
        "template_name": "prevencion_contacto_inicial",
    }, headers=admin_hdrs)
    assert r.status_code == 200, f"Crear campaña falló: {r.text}"
    return r.json()["campaign_id"]


@pytest.fixture(scope="session")
def lax_client():
    """TestClient sin raise_server_exceptions — para tests que esperan errores HTTP del servidor."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def test_db():
    """Conexión directa a la DB de test — útil para seed/assert a nivel SQL."""
    from app_demo import get_db
    conn = get_db()
    yield conn
    conn.close()


@pytest.fixture(scope="class")
def login_test_user(client, admin_hdrs):
    """Usuario dedicado a tests de login — evita invalidar la sesión admin."""
    client.post("/api/users", json={
        "username": "login_tester",
        "password": "pass_login_123",
        "nombre": "Login Tester",
        "role": "vendedor",
    }, headers=admin_hdrs)
    return {"username": "login_tester", "password": "pass_login_123"}
