"""
test_security.py — Auditoría de autorización de cada endpoint.

Todos los tests verifican el comportamiento CORRECTO (post-fix).
Los endpoints que antes eran vulnerables ahora deben devolver 401/403.
"""
import pytest


# ─── ENDPOINTS PROTEGIDOS — deben rechazar acceso sin auth ───────────────────

class TestEndpointsProtegidos:
    """Verifica que todos los endpoints requieren la autenticación correcta."""

    # Auth básica
    def test_me_requiere_auth(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_change_password_requiere_auth(self, client):
        r = client.post("/api/auth/change-password",
                        json={"current_password": "a", "new_password": "b"})
        assert r.status_code == 401

    # Contactos
    def test_contacts_requiere_auth(self, client):
        assert client.get("/api/contacts").status_code == 401

    def test_upload_contacts_requiere_auth(self, client):
        r = client.post("/api/contacts/upload",
                        files={"file": ("t.csv", b"nombre,telefono\nTest,1234", "text/csv")})
        assert r.status_code == 401

    def test_imports_requiere_auth(self, client):
        assert client.get("/api/imports").status_code == 401

    def test_delete_import_requiere_admin(self, client):
        assert client.delete("/api/imports/1").status_code == 401

    def test_upload_image_requiere_auth(self, client):
        r = client.post("/api/upload-image",
                        files={"file": ("t.jpg", b"\xff\xd8\xff", "image/jpeg")})
        assert r.status_code == 401

    # Campañas
    def test_campaigns_list_requiere_auth(self, client):
        assert client.get("/api/campaigns").status_code == 401

    def test_campaigns_create_requiere_auth(self, client):
        r = client.post("/api/campaigns", json={"name": "x", "contact_ids": [], "message_template": "x"})
        assert r.status_code == 401

    def test_campaigns_detail_requiere_auth(self, client, sample_campaign_id):
        assert client.get(f"/api/campaigns/{sample_campaign_id}").status_code == 401

    def test_send_campaign_requiere_auth(self, client, sample_campaign_id):
        assert client.post(f"/api/campaigns/{sample_campaign_id}/send").status_code == 401

    def test_borrar_campaign_requiere_admin(self, client, sample_campaign_id):
        assert client.delete(f"/api/campaigns/{sample_campaign_id}").status_code == 401

    def test_borrar_campaign_vendedor_no_puede(self, client, vendedor_hdrs, sample_campaign_id):
        assert client.delete(f"/api/campaigns/{sample_campaign_id}", headers=vendedor_hdrs).status_code == 403

    # Conversaciones
    def test_conversaciones_requiere_auth(self, client):
        assert client.get("/api/conversations").status_code == 401

    def test_conv_messages_requiere_auth(self, client):
        assert client.get("/api/conversations/1/messages").status_code == 401

    def test_conv_messages_since_requiere_auth(self, client):
        assert client.get("/api/conversations/1/messages-since").status_code == 401

    def test_reply_requiere_auth(self, client):
        r = client.post("/api/conversations/reply", json={"conversation_id": 1, "body": "hola"})
        assert r.status_code == 401

    # Leads
    def test_leads_requiere_auth(self, client):
        assert client.get("/api/leads").status_code == 401

    def test_cargar_puente_requiere_auth(self, client):
        assert client.post("/api/leads/1/cargar-puente").status_code == 401

    def test_completar_lead_requiere_auth(self, client):
        assert client.post("/api/leads/1/completar").status_code == 401

    def test_reactivar_lead_requiere_auth(self, client):
        assert client.post("/api/leads/1/reactivar").status_code == 401

    def test_clasificar_lead_requiere_auth(self, client):
        assert client.post("/api/leads/1/clasificar", json={"clasificacion": "x"}).status_code == 401

    def test_recordatorio_requiere_auth(self, client):
        assert client.post("/api/leads/1/recordatorio", json={"recordatorio_fecha": "2026-06-10"}).status_code == 401

    def test_lead_info_requiere_auth(self, client):
        assert client.get("/api/leads/1/info").status_code == 401

    # Asesores
    def test_asesores_get_requiere_auth(self, client):
        assert client.get("/api/asesores").status_code == 401

    def test_asesores_create_requiere_admin(self, client):
        assert client.post("/api/asesores", json={"nombre": "x"}).status_code == 401

    def test_asesores_create_vendedor_no_puede(self, client, vendedor_hdrs):
        r = client.post("/api/asesores", json={"nombre": "x"}, headers=vendedor_hdrs)
        assert r.status_code == 403

    def test_asesores_update_requiere_admin(self, client, asesor_id):
        assert client.put(f"/api/asesores/{asesor_id}", json={"nombre": "x", "porcentaje": 0}).status_code == 401

    def test_asesores_delete_requiere_admin(self, client, asesor_id):
        assert client.delete(f"/api/asesores/{asesor_id}").status_code == 401

    # Config
    def test_agent_config_get_requiere_auth(self, client):
        assert client.get("/api/agent-config").status_code == 401

    def test_agent_config_post_requiere_admin(self, client):
        assert client.post("/api/agent-config", json={"name": "x"}).status_code == 401

    def test_planes_info_get_requiere_auth(self, client):
        assert client.get("/api/planes-info").status_code == 401

    def test_planes_info_post_requiere_admin(self, client):
        assert client.post("/api/planes-info", json={"content": "x"}).status_code == 401

    def test_telegram_status_requiere_auth(self, client):
        assert client.get("/api/telegram/status").status_code == 401

    def test_telegram_test_requiere_auth(self, client):
        assert client.post("/api/telegram/test").status_code == 401

    def test_telegram_configure_requiere_admin(self, client):
        r = client.post("/api/telegram/configure", json={"token": "x", "chat_id": "y"})
        assert r.status_code == 401

    def test_templates_requiere_auth(self, client):
        assert client.get("/api/templates").status_code == 401

    def test_ai_conversations_requiere_auth(self, client):
        assert client.get("/api/ai-conversations").status_code == 401

    # Notificaciones / stats
    def test_notifications_requiere_auth(self, client):
        assert client.get("/api/notifications").status_code == 401

    def test_stats_requiere_auth(self, client):
        assert client.get("/api/stats").status_code == 401

    def test_my_leads_requiere_auth(self, client):
        assert client.get("/api/my-leads").status_code == 401

    def test_my_conversations_requiere_auth(self, client):
        assert client.get("/api/my-conversations").status_code == 401

    def test_quick_replies_get_requiere_auth(self, client):
        assert client.get("/api/quick-replies").status_code == 401

    def test_quick_replies_post_requiere_admin(self, client):
        r = client.post("/api/quick-replies", json={"category": "x", "label": "x", "message": "x"})
        assert r.status_code == 401

    def test_ai_test_requiere_admin(self, client):
        assert client.post("/api/ai/test", json={"message": "hola"}).status_code == 401

    def test_puente_config_requiere_auth(self, client):
        assert client.get("/api/my-puente-config").status_code == 401

    def test_productores_requiere_auth(self, client):
        assert client.get("/api/productores").status_code == 401

    def test_reset_data_requiere_admin(self, client, vendedor_hdrs):
        assert client.delete("/api/reset-data", headers=vendedor_hdrs).status_code == 403

    def test_reset_data_sin_auth(self, client):
        assert client.delete("/api/reset-data").status_code == 401

    def test_crear_usuario_requiere_admin(self, client):
        r = client.post("/api/users", json={"username": "x", "password": "x", "nombre": "x"})
        assert r.status_code == 401

    def test_crear_usuario_vendedor_no_puede(self, client, vendedor_hdrs):
        r = client.post("/api/users", json={"username": "x", "password": "x", "nombre": "x"},
                        headers=vendedor_hdrs)
        assert r.status_code == 403

    def test_listar_usuarios_requiere_admin(self, client):
        assert client.get("/api/users").status_code == 401

    def test_listar_usuarios_vendedor_no_puede(self, client, vendedor_hdrs):
        assert client.get("/api/users", headers=vendedor_hdrs).status_code == 403


# ─── SQL INJECTION — VERIFICACIÓN DE LA FIX ──────────────────────────────────

class TestSQLInjection:
    """
    Verifica que la SQL injection en GET /api/leads?status=... fue corregida.
    La query ahora usa parámetros (?) en vez de interpolación de string.
    Usa lax_client (raise_server_exceptions=False) para capturar errores HTTP reales.
    """

    def test_sqli_sin_auth_devuelve_401(self, lax_client):
        assert lax_client.get("/api/leads?status='").status_code == 401

    def test_sqli_comilla_simple_no_rompe_sql(self, lax_client, admin_hdrs):
        """Con parametrización: comilla devuelve [] en vez de error 500."""
        r = lax_client.get("/api/leads?status='", headers=admin_hdrs)
        assert r.status_code == 200
        assert r.json() == []

    def test_sqli_union_no_expone_datos_sensibles(self, lax_client, admin_hdrs):
        """El UNION SELECT devuelve [] porque el valor literal no existe."""
        payload = "x' UNION SELECT username,password_hash,1,1,1,1,1,1,1,1,1,1,1 FROM users--"
        r = lax_client.get(f"/api/leads?status={payload}", headers=admin_hdrs)
        assert r.status_code == 200
        assert r.json() == [], "Con parametrización el payload UNION devuelve lista vacía"
