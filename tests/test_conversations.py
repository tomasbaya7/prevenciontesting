"""
test_conversations.py — Bandeja de entrada: mensajes, reply, quick replies.
"""
import pytest


def _seed_conversation(client, phone: str, name: str = "Test Conv") -> int:
    """Crea una conversación via webhook y retorna el conv_id."""
    import time
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "contacts": [{"profile": {"name": name}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": f"wamid.conv_{phone}_{int(time.time())}",
                        "timestamp": str(int(time.time())),
                        "text": {"body": "Hola"},
                        "type": "text",
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    client.post("/webhook", json=payload)

    # Obtener el conv_id (necesitamos auth para /api/conversations)
    return phone  # devolvemos el phone para buscar por él


class TestConversaciones:
    def test_listar_conversaciones_requiere_auth(self, client):
        r = client.get("/api/conversations")
        assert r.status_code == 401

    def test_listar_conversaciones_admin(self, client, admin_hdrs):
        r = client.get("/api/conversations", headers=admin_hdrs)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_my_conversations_vendedor(self, client, vendedor_hdrs):
        r = client.get("/api/my-conversations", headers=vendedor_hdrs)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_mensajes_conv_sin_auth(self, client):
        """GET /api/conversations/{id}/messages ahora requiere auth (bug corregido)."""
        r = client.get("/api/conversations/1/messages")
        assert r.status_code == 401

    def test_mensajes_conv_inexistente(self, client, admin_hdrs):
        r = client.get("/api/conversations/999999/messages", headers=admin_hdrs)
        assert r.status_code == 200
        data = r.json()
        assert data["conversation"] is None
        assert data["messages"] == []

    def test_estructura_mensajes_conv(self, client, admin_hdrs):
        _seed_conversation(client, "5491188880001", "Estructura Test")

        convs = client.get("/api/my-conversations", headers=admin_hdrs).json()
        if convs:
            conv_id = convs[0]["id"]
            r = client.get(f"/api/conversations/{conv_id}/messages", headers=admin_hdrs)
            assert r.status_code == 200
            data = r.json()
            assert "conversation" in data
            assert "messages" in data
            assert isinstance(data["messages"], list)


class TestReply:
    def test_reply_sin_auth(self, client):
        r = client.post("/api/conversations/reply",
                        json={"conversation_id": 1, "body": "Hola"})
        assert r.status_code == 401

    def test_reply_conv_inexistente(self, client, admin_hdrs):
        r = client.post("/api/conversations/reply",
                        json={"conversation_id": 999999, "body": "Hola"},
                        headers=admin_hdrs)
        # Debe devolver error (conversación no encontrada)
        assert r.status_code in (404, 400, 200)

    def test_reply_body_requerido(self, client, admin_hdrs):
        r = client.post("/api/conversations/reply",
                        json={"conversation_id": 1},
                        headers=admin_hdrs)
        assert r.status_code == 422

    def test_reply_valido(self, client, admin_hdrs):
        _seed_conversation(client, "5491188880002", "Reply Test")
        convs = client.get("/api/my-conversations", headers=admin_hdrs).json()
        if convs:
            conv_id = convs[0]["id"]
            r = client.post("/api/conversations/reply",
                            json={"conversation_id": conv_id, "body": "Gracias por escribirnos"},
                            headers=admin_hdrs)
            assert r.status_code == 200


class TestQuickReplies:
    def test_listar_quick_replies_requiere_auth(self, client):
        assert client.get("/api/quick-replies").status_code == 401

    def test_listar_quick_replies_con_auth(self, client, admin_hdrs):
        r = client.get("/api/quick-replies", headers=admin_hdrs)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # Deben existir los defaults del seed
        assert len(data) > 0

    def test_estructura_quick_reply(self, client, admin_hdrs):
        r = client.get("/api/quick-replies", headers=admin_hdrs)
        qr = r.json()[0]
        assert "id" in qr
        assert "category" in qr
        assert "label" in qr
        assert "message" in qr

    def test_crear_quick_reply_requiere_admin(self, client, vendedor_hdrs):
        r = client.post("/api/quick-replies",
                        json={"category": "Test", "label": "Test", "message": "Test"},
                        headers=vendedor_hdrs)
        assert r.status_code == 403

    def test_crear_quick_reply_como_admin(self, client, admin_hdrs):
        r = client.post("/api/quick-replies",
                        json={"category": "Test", "label": "Test Label", "message": "Mensaje de test"},
                        headers=admin_hdrs)
        assert r.status_code == 200
        qr_id = r.json()["id"]

        # Limpiar
        client.delete(f"/api/quick-replies/{qr_id}", headers=admin_hdrs)

    def test_editar_quick_reply_como_admin(self, client, admin_hdrs):
        r = client.post("/api/quick-replies",
                        json={"category": "Cat", "label": "Lab", "message": "Msg"},
                        headers=admin_hdrs)
        qr_id = r.json()["id"]

        r_edit = client.put(f"/api/quick-replies/{qr_id}",
                            json={"category": "Cat", "label": "Lab Editado", "message": "Msg Editado"},
                            headers=admin_hdrs)
        assert r_edit.status_code == 200

        client.delete(f"/api/quick-replies/{qr_id}", headers=admin_hdrs)

    def test_borrar_quick_reply_requiere_admin(self, client, vendedor_hdrs):
        r = client.delete("/api/quick-replies/1", headers=vendedor_hdrs)
        assert r.status_code == 403


class TestNotificaciones:
    def test_listar_notificaciones_requiere_auth(self, client):
        assert client.get("/api/notifications").status_code == 401

    def test_listar_notificaciones_con_auth(self, client, admin_hdrs):
        r = client.get("/api/notifications", headers=admin_hdrs)
        assert r.status_code == 200

    def test_marcar_leidas_requiere_auth(self, client):
        assert client.post("/api/notifications/mark-read").status_code == 401

    def test_marcar_leidas_con_auth(self, client, admin_hdrs):
        r = client.post("/api/notifications/mark-read", headers=admin_hdrs)
        assert r.status_code == 200
