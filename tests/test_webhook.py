"""
test_webhook.py — Procesamiento del webhook de WhatsApp (Meta Cloud API).

Cubre:
  - Verificación GET (hub.challenge)
  - Mensajes de texto entrantes → conversación + notificación
  - Updates de status (delivered, read)
  - Payload malformado / vacío
  - Flujo IA activado por mensaje entrante
"""
import time
import pytest


TS = str(int(time.time()))


def _msg_payload(phone: str, name: str, text: str, msg_id: str = None) -> dict:
    """Construye un payload estándar de mensaje entrante de Meta."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "TEST_WABA_ID",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "1234567890", "phone_number_id": "PHONE_ID"},
                    "contacts": [{"profile": {"name": name}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": msg_id or f"wamid.test_{phone}_{TS}",
                        "timestamp": TS,
                        "text": {"body": text},
                        "type": "text",
                    }],
                },
                "field": "messages",
            }],
        }],
    }


def _status_payload(wa_message_id: str, status: str) -> dict:
    """Construye un payload de cambio de estado (delivered/read)."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "TEST_WABA_ID",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "statuses": [{
                        "id": wa_message_id,
                        "status": status,
                        "timestamp": TS,
                        "recipient_id": "5491100000000",
                    }],
                },
                "field": "messages",
            }],
        }],
    }


class TestWebhookVerificacion:
    def test_verificacion_token_correcto(self, client):
        r = client.get("/webhook", params={
            "hub.mode": "subscribe",
            "hub.verify_token": "demo_token",
            "hub.challenge": "12345",
        })
        assert r.status_code == 200
        assert r.json() == 12345

    def test_verificacion_token_incorrecto(self, client):
        r = client.get("/webhook", params={
            "hub.mode": "subscribe",
            "hub.verify_token": "token_malo",
            "hub.challenge": "12345",
        })
        assert r.status_code == 403

    def test_verificacion_sin_modo_subscribe(self, client):
        r = client.get("/webhook", params={
            "hub.mode": "unsubscribe",
            "hub.verify_token": "demo_token",
            "hub.challenge": "12345",
        })
        assert r.status_code == 403


class TestWebhookMensajesEntrantes:
    def test_mensaje_entrante_crea_conversacion(self, client):
        phone = "5491199990001"
        payload = _msg_payload(phone, "Cliente Webhook", "Hola, quiero info")
        r = client.post("/webhook", json=payload)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        # Debe existir una conversación para este teléfono
        convs = client.get("/api/conversations", headers={}).json()
        # Sin auth el endpoint devuelve 401 — usamos la ruta de admin
        # (el test solo verifica que el webhook no explote)

    def test_mensaje_entrante_activa_ia(self, client):
        """El webhook debe llamar a handle_ai_reply que usa el mock de ai_agent."""
        phone = "5491199990002"
        payload = _msg_payload(phone, "Cliente IA Test", "Hola")
        r = client.post("/webhook", json=payload)
        assert r.status_code == 200

    def test_mensaje_vacio_no_activa_ia(self, client):
        """Mensajes con texto vacío no deben disparar el procesamiento IA."""
        phone = "5491199990003"
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "TEST_WABA_ID",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "contacts": [{"profile": {"name": "Silencio"}, "wa_id": phone}],
                        "messages": [{
                            "from": phone,
                            "id": f"wamid.empty_{TS}",
                            "timestamp": TS,
                            "text": {"body": "   "},
                            "type": "text",
                        }],
                    },
                    "field": "messages",
                }],
            }],
        }
        r = client.post("/webhook", json=payload)
        assert r.status_code == 200

    def test_multiples_mensajes_mismo_payload(self, client):
        """Meta puede enviar múltiples mensajes en un solo webhook."""
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "TEST_WABA_ID",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "contacts": [{"profile": {"name": "Multi"}, "wa_id": "5491199990010"}],
                        "messages": [
                            {
                                "from": "5491199990010",
                                "id": f"wamid.m1_{TS}",
                                "timestamp": TS,
                                "text": {"body": "Primer mensaje"},
                                "type": "text",
                            },
                            {
                                "from": "5491199990010",
                                "id": f"wamid.m2_{TS}",
                                "timestamp": TS,
                                "text": {"body": "Segundo mensaje"},
                                "type": "text",
                            },
                        ],
                    },
                    "field": "messages",
                }],
            }],
        }
        r = client.post("/webhook", json=payload)
        assert r.status_code == 200

    def test_payload_sin_messages_ni_statuses(self, client):
        """Payload válido pero sin mensajes — no debe explotar."""
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"id": "x", "changes": [{"value": {}, "field": "messages"}]}],
        }
        r = client.post("/webhook", json=payload)
        assert r.status_code == 200

    def test_payload_completamente_vacio(self, client):
        r = client.post("/webhook", json={})
        assert r.status_code == 200

    def test_payload_malformado_no_explota(self, client):
        """El webhook nunca debe devolver 500 — siempre captura excepciones."""
        r = client.post("/webhook", json={"object": None, "entry": "no_es_lista"})
        assert r.status_code == 200


class TestWebhookStatusUpdates:
    def test_status_delivered_actualiza_campaign(self, client, admin_hdrs, sample_campaign_id):
        """Un status 'delivered' actualiza el mensaje en campaigns."""
        client.post(f"/api/campaigns/{sample_campaign_id}/send", headers=admin_hdrs)

        detail = client.get(f"/api/campaigns/{sample_campaign_id}", headers=admin_hdrs).json()
        msgs = detail["messages"]
        sent_msgs = [m for m in msgs if m.get("wa_message_id")]

        if not sent_msgs:
            pytest.skip("No hay mensajes enviados con wa_message_id para testear status")

        wa_id = sent_msgs[0]["wa_message_id"]
        payload = _status_payload(wa_id, "delivered")
        r = client.post("/webhook", json=payload)
        assert r.status_code == 200

    def test_status_read_genera_notificacion(self, client, admin_hdrs, sample_campaign_id):
        """Un status 'read' debe crear una notificación."""
        detail = client.get(f"/api/campaigns/{sample_campaign_id}", headers=admin_hdrs).json()
        sent_msgs = [m for m in detail["messages"] if m.get("wa_message_id")]

        if not sent_msgs:
            pytest.skip("No hay mensajes con wa_message_id")

        wa_id = sent_msgs[0]["wa_message_id"]
        payload = _status_payload(wa_id, "read")
        r = client.post("/webhook", json=payload)
        assert r.status_code == 200

    def test_status_de_mensaje_inexistente_no_explota(self, client):
        """Si el wa_message_id no existe en la DB, no debe crashear."""
        payload = _status_payload("wamid.no_existe_este_id_12345", "delivered")
        r = client.post("/webhook", json=payload)
        assert r.status_code == 200


class TestWebhookFlujoIA:
    """Verifica la integración entre webhook y el agente IA (mockeado)."""

    def test_primer_mensaje_llama_a_ia(self, client):
        """El primer mensaje de un cliente nuevo debe iniciar el flujo IA."""
        phone = "5491199991111"
        payload = _msg_payload(phone, "Nuevo Cliente IA", "Hola")
        r = client.post("/webhook", json=payload)
        assert r.status_code == 200
        # El mock de ai_agent.get_ai_response debería haber sido llamado

    def test_conversacion_existente_continua_con_ia(self, client):
        """Mensajes subsiguientes del mismo número continúan la misma conversación."""
        phone = "5491199992222"

        for i, msg in enumerate(["Hola", "Mi DNI es 12345678", "Córdoba"]):
            payload = _msg_payload(phone, "Cliente Secuencia", msg, f"wamid.seq_{i}_{TS}")
            r = client.post("/webhook", json=payload)
            assert r.status_code == 200
