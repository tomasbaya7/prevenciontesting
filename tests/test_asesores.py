"""
test_asesores.py — CRUD de asesores.
Todos los endpoints ahora requieren autenticación (bugs corregidos).
"""
import pytest


class TestAsesoresCRUD:
    def test_listar_asesores_sin_auth(self, client):
        assert client.get("/api/asesores").status_code == 401

    def test_listar_asesores(self, client, admin_hdrs):
        r = client.get("/api/asesores", headers=admin_hdrs)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_asesor_tiene_campos_esperados(self, client, admin_hdrs, asesor_id):
        r = client.get("/api/asesores", headers=admin_hdrs)
        asesores = r.json()
        assert len(asesores) > 0
        a = asesores[0]
        assert "id" in a
        assert "nombre" in a
        assert "porcentaje" in a
        assert "activo" in a

    def test_crear_asesor_sin_auth(self, client):
        r = client.post("/api/asesores", json={"nombre": "Intruso", "porcentaje": 0})
        assert r.status_code == 401

    def test_crear_asesor_vendedor_no_puede(self, client, vendedor_hdrs):
        r = client.post("/api/asesores", json={"nombre": "Intruso Vendedor", "porcentaje": 0},
                        headers=vendedor_hdrs)
        assert r.status_code == 403

    def test_crear_asesor(self, client, admin_hdrs):
        r = client.post("/api/asesores", json={
            "nombre": "Nuevo Asesor",
            "email": "nuevo@test.com",
            "porcentaje": 30,
        }, headers=admin_hdrs)
        assert r.status_code == 200
        assert "id" in r.json()
        new_id = r.json()["id"]
        client.delete(f"/api/asesores/{new_id}", headers=admin_hdrs)

    def test_crear_asesor_nombre_requerido(self, client, admin_hdrs):
        r = client.post("/api/asesores", json={"email": "sin_nombre@test.com"}, headers=admin_hdrs)
        assert r.status_code == 422

    def test_actualizar_asesor_sin_auth(self, client, asesor_id):
        r = client.put(f"/api/asesores/{asesor_id}", json={"nombre": "Hack", "porcentaje": 0})
        assert r.status_code == 401

    def test_actualizar_asesor(self, client, admin_hdrs):
        r_create = client.post("/api/asesores", json={"nombre": "Asesor Actualizable", "porcentaje": 10},
                               headers=admin_hdrs)
        aid = r_create.json()["id"]

        r_update = client.put(f"/api/asesores/{aid}", json={
            "nombre": "Asesor Actualizado",
            "porcentaje": 50,
            "email": "actualizado@test.com",
        }, headers=admin_hdrs)
        assert r_update.status_code == 200

        asesores = client.get("/api/asesores", headers=admin_hdrs).json()
        found = next((a for a in asesores if a["id"] == aid), None)
        assert found is not None
        assert found["nombre"] == "Asesor Actualizado"
        assert found["porcentaje"] == 50

        client.delete(f"/api/asesores/{aid}", headers=admin_hdrs)

    def test_borrar_asesor_sin_auth(self, client, asesor_id):
        r = client.delete(f"/api/asesores/{asesor_id}")
        assert r.status_code == 401

    def test_borrar_asesor(self, client, admin_hdrs):
        r = client.post("/api/asesores", json={"nombre": "Para Borrar Asesor", "porcentaje": 0},
                        headers=admin_hdrs)
        aid = r.json()["id"]

        r_del = client.delete(f"/api/asesores/{aid}", headers=admin_hdrs)
        assert r_del.status_code == 200

        asesores = client.get("/api/asesores", headers=admin_hdrs).json()
        assert not any(a["id"] == aid for a in asesores)

    def test_porcentaje_no_negativo(self, client, admin_hdrs):
        r = client.get("/api/asesores", headers=admin_hdrs)
        for a in r.json():
            assert a["porcentaje"] >= 0


class TestAsesorTelegram:
    def test_actualizar_telegram_asesor_sin_auth(self, client, asesor_id):
        r = client.put(f"/api/asesores/{asesor_id}/telegram",
                       json={"telegram_chat_id": "123456"})
        assert r.status_code == 401

    def test_actualizar_telegram_asesor_con_admin(self, client, admin_hdrs, asesor_id):
        r = client.put(f"/api/asesores/{asesor_id}/telegram",
                       json={"telegram_chat_id": ""},
                       headers=admin_hdrs)
        assert r.status_code == 200

    def test_test_telegram_asesor_sin_chat_id_falla(self, client, admin_hdrs, asesor_id):
        client.put(f"/api/asesores/{asesor_id}/telegram",
                   json={"telegram_chat_id": ""},
                   headers=admin_hdrs)
        r = client.post(f"/api/asesores/{asesor_id}/telegram-test", headers=admin_hdrs)
        assert r.status_code == 400

    def test_test_telegram_asesor_inexistente(self, client, admin_hdrs):
        r = client.post("/api/asesores/999999/telegram-test", headers=admin_hdrs)
        assert r.status_code == 404


class TestAsesoresSeguridad:
    """Verifica que las correcciones de seguridad están en vigor."""

    def test_listar_asesores_sin_auth_devuelve_401(self, client):
        assert client.get("/api/asesores").status_code == 401

    def test_crear_asesor_sin_auth_devuelve_401(self, client):
        r = client.post("/api/asesores", json={"nombre": "Intruso Externo", "porcentaje": 0})
        assert r.status_code == 401

    def test_actualizar_asesor_sin_auth_devuelve_401(self, client, asesor_id):
        r = client.put(f"/api/asesores/{asesor_id}", json={
            "nombre": "Hackeado",
            "puente_user": "intruso",
            "puente_password": "hack",
        })
        assert r.status_code == 401

    def test_borrar_asesor_sin_auth_devuelve_401(self, client, asesor_id):
        assert client.delete(f"/api/asesores/{asesor_id}").status_code == 401

    def test_credenciales_puente_no_accesibles_sin_auth(self, client, admin_hdrs, asesor_id):
        """Las credenciales de Puente no son accesibles sin autenticación."""
        client.put(f"/api/asesores/{asesor_id}", json={
            "nombre": "Asesor Test Suite",
            "porcentaje": 100,
            "puente_user": "usuario_secreto",
            "puente_password": "pass_secreta",
        }, headers=admin_hdrs)

        r = client.get("/api/asesores")  # sin auth
        assert r.status_code == 401
