"""
test_leads.py — Gestión de leads: listado, clasificación, recordatorio, SQL injection.
Todos los endpoints ahora requieren autenticación.
"""
import pytest


def _create_lead_via_webhook(client, phone: str, name: str = "Test Lead") -> dict:
    """Helper: simula un mensaje entrante de WhatsApp que crea un lead."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "TEST_WABA",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "contacts": [{"profile": {"name": name}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": f"wamid.test_{phone}",
                        "timestamp": "1717200000",
                        "text": {"body": "Hola, me interesa"},
                        "type": "text",
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    r = client.post("/webhook", json=payload)
    assert r.status_code == 200
    return r.json()


class TestLeadsListado:
    def test_lista_leads_sin_auth(self, client):
        assert client.get("/api/leads").status_code == 401

    def test_lista_leads(self, client, admin_hdrs):
        r = client.get("/api/leads", headers=admin_hdrs)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_filtro_por_status(self, client, admin_hdrs):
        r = client.get("/api/leads?status=pending", headers=admin_hdrs)
        assert r.status_code == 200
        leads = r.json()
        for lead in leads:
            assert lead["puente_status"] == "pending"

    def test_filtro_status_vacio_devuelve_todos(self, client, admin_hdrs):
        r_all = client.get("/api/leads", headers=admin_hdrs)
        r_filtered = client.get("/api/leads?status=", headers=admin_hdrs)
        assert r_all.status_code == 200
        assert r_filtered.status_code == 200
        assert len(r_all.json()) == len(r_filtered.json())

    def test_estructura_lead(self, client, admin_hdrs, asesor_id):
        _create_lead_via_webhook(client, "5491100000001", "Lead Estructura")
        r = client.get("/api/leads", headers=admin_hdrs)
        leads = r.json()
        if leads:
            lead = leads[0]
            assert "id" in lead
            assert "contact_name" in lead
            assert "contact_phone" in lead
            assert "puente_status" in lead


class TestSQLInjection:
    """
    Documenta la corrección de la SQL injection en GET /api/leads?status=...
    La query ahora usa parámetros (?) en vez de interpolación directa.
    """

    def test_endpoint_requiere_auth(self, client):
        r = client.get("/api/leads?status='")
        assert r.status_code == 401

    def test_sqli_comilla_simple_con_auth(self, lax_client, admin_hdrs):
        """Con parametrización, la comilla simple es tratada como string literal — no rompe el SQL."""
        r = lax_client.get("/api/leads?status='", headers=admin_hdrs)
        # Con la fix: devuelve 200 con lista vacía (ningún lead tiene puente_status="'")
        assert r.status_code == 200
        assert r.json() == []

    def test_sqli_tautologia_no_rompe_filtro(self, lax_client, admin_hdrs, asesor_id):
        """
        ' OR '1'='1 ahora es tratado como string literal, no rompe el WHERE.
        Devuelve lista vacía porque ningún lead tiene ese valor exacto.
        """
        _create_lead_via_webhook(lax_client, "5491100000099", "Lead SQLi")

        r_pending = lax_client.get("/api/leads?status=pending", headers=admin_hdrs)
        r_injection = lax_client.get("/api/leads?status=' OR '1'='1", headers=admin_hdrs)

        assert r_pending.status_code == 200
        assert r_injection.status_code == 200

        # Con la fix: la inyección devuelve 0 resultados (el valor literal no existe)
        assert len(r_injection.json()) == 0, \
            "La SQL injection fue corregida: la tautología devuelve 0 resultados"

    def test_sqli_union_no_expone_passwords(self, lax_client, admin_hdrs):
        """Un UNION SELECT sobre users no debe aparecer en la respuesta."""
        payload = "x' UNION SELECT 1,username,password_hash,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1 FROM users--"
        r = lax_client.get(f"/api/leads?status={payload}", headers=admin_hdrs)
        assert r.status_code == 200
        assert r.json() == [], "Con parametrización el UNION devuelve vacío, no datos de users"


class TestLeadAcciones:
    def _get_or_create_lead_id(self, client, admin_hdrs) -> int:
        _create_lead_via_webhook(client, "5491100001001", "Lead Acciones")
        leads = client.get("/api/leads", headers=admin_hdrs).json()
        assert len(leads) > 0
        return leads[0]["id"]

    def test_clasificar_lead_con_auth(self, client, admin_hdrs):
        lead_id = self._get_or_create_lead_id(client, admin_hdrs)
        r = client.post(f"/api/leads/{lead_id}/clasificar",
                        json={"clasificacion": "Interesado"},
                        headers=admin_hdrs)
        assert r.status_code == 200
        assert r.json()["clasificacion"] == "Interesado"

    def test_clasificar_lead_sin_auth(self, client):
        assert client.post("/api/leads/1/clasificar", json={"clasificacion": "x"}).status_code == 401

    def test_recordatorio_con_auth(self, client, admin_hdrs):
        lead_id = self._get_or_create_lead_id(client, admin_hdrs)
        r = client.post(f"/api/leads/{lead_id}/recordatorio",
                        json={"recordatorio_fecha": "2026-06-15"},
                        headers=admin_hdrs)
        assert r.status_code == 200
        assert r.json()["recordatorio_fecha"] == "2026-06-15"

    def test_recordatorio_sin_auth(self, client):
        r = client.post("/api/leads/1/recordatorio", json={"recordatorio_fecha": "2026-06-15"})
        assert r.status_code == 401

    def test_completar_lead_requiere_auth(self, client):
        assert client.post("/api/leads/1/completar").status_code == 401

    def test_completar_lead(self, client, admin_hdrs):
        lead_id = self._get_or_create_lead_id(client, admin_hdrs)
        r = client.post(f"/api/leads/{lead_id}/completar", headers=admin_hdrs)
        assert r.status_code == 200

    def test_reactivar_lead_requiere_auth(self, client):
        assert client.post("/api/leads/1/reactivar").status_code == 401

    def test_reactivar_lead(self, client, admin_hdrs):
        lead_id = self._get_or_create_lead_id(client, admin_hdrs)
        client.post(f"/api/leads/{lead_id}/completar", headers=admin_hdrs)
        r = client.post(f"/api/leads/{lead_id}/reactivar", headers=admin_hdrs)
        assert r.status_code == 200

    def test_lead_info_con_auth(self, client, admin_hdrs):
        lead_id = self._get_or_create_lead_id(client, admin_hdrs)
        r = client.get(f"/api/leads/{lead_id}/info", headers=admin_hdrs)
        assert r.status_code == 200
        assert r.json()["id"] == lead_id

    def test_lead_info_sin_auth(self, client):
        assert client.get("/api/leads/1/info").status_code == 401

    def test_lead_info_inexistente(self, client, admin_hdrs):
        assert client.get("/api/leads/999999/info", headers=admin_hdrs).status_code == 404

    def test_borrar_lead_como_admin(self, client, admin_hdrs):
        _create_lead_via_webhook(client, "5491100002002", "Lead Para Borrar")
        leads = client.get("/api/leads", headers=admin_hdrs).json()
        lead_id = leads[0]["id"]
        assert client.delete(f"/api/leads/{lead_id}", headers=admin_hdrs).status_code == 200

    def test_borrar_lead_sin_auth(self, client):
        assert client.delete("/api/leads/1").status_code == 401

    def test_asignar_productor_sin_auth(self, client):
        assert client.post("/api/leads/1/asignar-productor", json={"productor_id": 1}).status_code == 401

    def test_cargar_puente_sin_auth(self, client):
        assert client.post("/api/leads/1/cargar-puente").status_code == 401


class TestMyLeads:
    def test_my_leads_admin_ve_todos(self, client, admin_hdrs):
        r = client.get("/api/my-leads", headers=admin_hdrs)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_my_leads_sin_auth(self, client):
        assert client.get("/api/my-leads").status_code == 401

    def test_my_leads_vendedor(self, client, vendedor_hdrs):
        r = client.get("/api/my-leads", headers=vendedor_hdrs)
        assert r.status_code == 200
