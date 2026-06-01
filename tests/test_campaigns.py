"""
test_campaigns.py — CRUD de campañas y disparo de envío.
Todos los endpoints ahora requieren autenticación.
"""
import pytest


class TestCampaignCRUD:
    def test_crear_campaña_sin_auth(self, client, sample_contact_id):
        r = client.post("/api/campaigns", json={
            "name": "Sin Auth",
            "contact_ids": [sample_contact_id],
            "message_template": "Hola",
        })
        assert r.status_code == 401

    def test_crear_campaña_valida(self, client, admin_hdrs, sample_contact_id):
        r = client.post("/api/campaigns", json={
            "name": "Test Campaña",
            "contact_ids": [sample_contact_id],
            "message_template": "Hola {{nombre}}, somos Prevención Salud.",
            "template_name": "prevencion_contacto_inicial",
            "template_lang": "es_AR",
        }, headers=admin_hdrs)
        assert r.status_code == 200
        data = r.json()
        assert "campaign_id" in data
        assert data["contacts"] == 1

    def test_crear_campaña_sin_contactos(self, client, admin_hdrs):
        r = client.post("/api/campaigns", json={
            "name": "Sin Contactos",
            "contact_ids": [],
            "message_template": "Hola",
        }, headers=admin_hdrs)
        assert r.status_code == 200
        assert r.json()["contacts"] == 0

    def test_listar_campañas_sin_auth(self, client):
        assert client.get("/api/campaigns").status_code == 401

    def test_listar_campañas(self, client, admin_hdrs, sample_campaign_id):
        r = client.get("/api/campaigns", headers=admin_hdrs)
        assert r.status_code == 200
        campaigns = r.json()
        assert isinstance(campaigns, list)
        assert sample_campaign_id in [c["id"] for c in campaigns]

    def test_detalle_campaña_sin_auth(self, client, sample_campaign_id):
        assert client.get(f"/api/campaigns/{sample_campaign_id}").status_code == 401

    def test_detalle_campaña(self, client, admin_hdrs, sample_campaign_id):
        r = client.get(f"/api/campaigns/{sample_campaign_id}", headers=admin_hdrs)
        assert r.status_code == 200
        data = r.json()
        assert "campaign" in data
        assert "messages" in data
        assert data["campaign"]["id"] == sample_campaign_id

    def test_detalle_campaña_inexistente(self, client, admin_hdrs):
        r = client.get("/api/campaigns/999999", headers=admin_hdrs)
        assert r.status_code == 404

    def test_template_personaliza_nombre(self, client, admin_hdrs, sample_contact_id):
        r_contact = client.get("/api/contacts?per_page=1", headers=admin_hdrs)
        contact = r_contact.json()["contacts"][0]
        first_name = contact["name"].split()[0]

        r = client.post("/api/campaigns", json={
            "name": "Test Personalización",
            "contact_ids": [contact["id"]],
            "message_template": "Hola {{nombre}}, te contactamos.",
        }, headers=admin_hdrs)
        cid = r.json()["campaign_id"]
        detail = client.get(f"/api/campaigns/{cid}", headers=admin_hdrs).json()
        msg_text = detail["messages"][0]["message_text"]
        assert first_name in msg_text
        assert "{{nombre}}" not in msg_text


class TestCampaignSend:
    def test_enviar_sin_auth(self, client, sample_campaign_id):
        assert client.post(f"/api/campaigns/{sample_campaign_id}/send").status_code == 401

    def test_enviar_campaña_modo_demo(self, client, admin_hdrs, sample_campaign_id):
        r = client.post(f"/api/campaigns/{sample_campaign_id}/send", headers=admin_hdrs)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "sending"
        assert data["campaign_id"] == sample_campaign_id

    def test_enviar_campaña_inexistente(self, client, admin_hdrs):
        r = client.post("/api/campaigns/999999/send", headers=admin_hdrs)
        assert r.status_code == 404

    def test_status_campaña_cambia_a_sending(self, client, admin_hdrs, sample_contact_id):
        r_create = client.post("/api/campaigns", json={
            "name": "Test Status Sending",
            "contact_ids": [sample_contact_id],
            "message_template": "Hola",
        }, headers=admin_hdrs)
        cid = r_create.json()["campaign_id"]

        detail = client.get(f"/api/campaigns/{cid}", headers=admin_hdrs).json()
        assert detail["campaign"]["status"] == "draft"

        client.post(f"/api/campaigns/{cid}/send", headers=admin_hdrs)

        detail2 = client.get(f"/api/campaigns/{cid}", headers=admin_hdrs).json()
        assert detail2["campaign"]["status"] in ("sending", "sent")


class TestCampaignDelete:
    def test_borrar_campaña_como_admin(self, client, admin_hdrs, sample_contact_id):
        r_create = client.post("/api/campaigns", json={
            "name": "Para Borrar",
            "contact_ids": [sample_contact_id],
            "message_template": "Hola",
        }, headers=admin_hdrs)
        cid = r_create.json()["campaign_id"]

        r_del = client.delete(f"/api/campaigns/{cid}", headers=admin_hdrs)
        assert r_del.status_code == 200

        assert client.get(f"/api/campaigns/{cid}", headers=admin_hdrs).status_code == 404

    def test_borrar_campaña_sin_auth(self, client, sample_campaign_id):
        r = client.delete(f"/api/campaigns/{sample_campaign_id}")
        assert r.status_code == 401

    def test_borrar_campaña_como_vendedor(self, client, vendedor_hdrs, sample_campaign_id):
        r = client.delete(f"/api/campaigns/{sample_campaign_id}", headers=vendedor_hdrs)
        assert r.status_code == 403
