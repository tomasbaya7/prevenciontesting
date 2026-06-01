"""
test_auth.py — Flujo de autenticación: login, logout, /me, change-password.

TestLogin usa un usuario dedicado (login_tester) para no invalidar la sesión
admin que usan el resto de los tests (create_session borra sesiones previas).
"""
import pytest


class TestLogin:
    """Usa login_test_user para no invalidar la sesión admin de la suite."""

    def test_login_valido(self, client, login_test_user):
        r = client.post("/api/auth/login", json=login_test_user)
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert data["user"]["username"] == login_test_user["username"]

    def test_login_password_incorrecta(self, client, login_test_user):
        r = client.post("/api/auth/login", json={
            "username": login_test_user["username"],
            "password": "wrong_password",
        })
        assert r.status_code == 401

    def test_login_usuario_inexistente(self, client):
        r = client.post("/api/auth/login", json={"username": "noexiste_xyz", "password": "abc"})
        assert r.status_code == 401

    def test_login_username_case_insensitive(self, client, login_test_user):
        r = client.post("/api/auth/login", json={
            "username": login_test_user["username"].upper(),
            "password": login_test_user["password"],
        })
        assert r.status_code == 200

    def test_login_body_vacio(self, client):
        r = client.post("/api/auth/login", json={})
        assert r.status_code == 422  # Pydantic validation error

    def test_login_no_expone_password_hash(self, client, login_test_user):
        r = client.post("/api/auth/login", json=login_test_user)
        user = r.json()["user"]
        assert "password_hash" not in user
        assert "password" not in user

    def test_login_admin_devuelve_rol_correcto(self, client, admin_hdrs):
        """Verifica rol via /me sin hacer un nuevo login que rompa la sesión."""
        r = client.get("/api/auth/me", headers=admin_hdrs)
        assert r.status_code == 200
        assert r.json()["role"] == "admin"


class TestMe:
    def test_me_con_token_valido(self, client, admin_hdrs):
        r = client.get("/api/auth/me", headers=admin_hdrs)
        assert r.status_code == 200
        assert r.json()["role"] == "admin"

    def test_me_sin_token(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code == 401

    def test_me_token_invalido(self, client):
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer token_falso_123"})
        assert r.status_code == 401

    def test_me_no_expone_password(self, client, admin_hdrs):
        r = client.get("/api/auth/me", headers=admin_hdrs)
        data = r.json()
        assert "password_hash" not in data
        assert "password" not in data

    def test_me_tiene_campos_correctos(self, client, admin_hdrs):
        r = client.get("/api/auth/me", headers=admin_hdrs)
        data = r.json()
        for campo in ("id", "username", "nombre", "role"):
            assert campo in data


class TestLogout:
    def test_logout_invalida_sesion(self, client, admin_hdrs):
        """Hace login con un usuario temporal para no romper la sesión admin."""
        # Obtener token fresco con el login_tester (clase diferente, no interfiere)
        r_fresh = client.post("/api/auth/login", json={
            "username": "login_tester",
            "password": "pass_login_123",
        })
        if r_fresh.status_code != 200:
            pytest.skip("login_tester no existe aún — ejecutar TestLogin primero")

        token = r_fresh.json()["token"]
        hdrs = {"Authorization": f"Bearer {token}"}

        assert client.get("/api/auth/me", headers=hdrs).status_code == 200

        client.post("/api/auth/logout", headers=hdrs)

        r2 = client.get("/api/auth/me", headers=hdrs)
        assert r2.status_code == 401

    def test_logout_sin_token_no_explota(self, client):
        r = client.post("/api/auth/logout")
        assert r.status_code == 200


class TestChangePassword:
    def test_cambio_password_correcto(self, client, admin_hdrs):
        client.post("/api/users", json={
            "username": "pwchange_tester",
            "password": "oldpass123",
            "nombre": "PW Change Tester",
            "role": "vendedor",
        }, headers=admin_hdrs)

        r_login = client.post("/api/auth/login", json={
            "username": "pwchange_tester",
            "password": "oldpass123",
        })
        assert r_login.status_code == 200
        temp_hdrs = {"Authorization": f"Bearer {r_login.json()['token']}"}

        r = client.post("/api/auth/change-password", json={
            "current_password": "oldpass123",
            "new_password": "newpass456",
        }, headers=temp_hdrs)
        assert r.status_code == 200

        r2 = client.post("/api/auth/login", json={
            "username": "pwchange_tester",
            "password": "newpass456",
        })
        assert r2.status_code == 200

    def test_cambio_password_actual_incorrecta(self, client, admin_hdrs):
        r = client.post("/api/auth/change-password", json={
            "current_password": "wrongpass_xyz",
            "new_password": "newpass",
        }, headers=admin_hdrs)
        assert r.status_code == 400

    def test_cambio_password_sin_auth(self, client):
        r = client.post("/api/auth/change-password", json={
            "current_password": "admin123",
            "new_password": "algo",
        })
        assert r.status_code == 401


class TestPasswordHashing:
    """
    Verifica que el sistema usa bcrypt y migra hashes SHA-256 legacy.
    Usa un usuario dedicado (no admin) para no invalidar la sesión session-scoped.
    """

    def test_nuevos_usuarios_tienen_hash_bcrypt(self, client, admin_hdrs, test_db):
        """Los usuarios creados via API tienen hash bcrypt, no SHA-256."""
        client.post("/api/users", json={
            "username": "bcrypt_check",
            "password": "segura123",
            "nombre": "Bcrypt Check",
            "role": "vendedor",
        }, headers=admin_hdrs)
        user = test_db.execute("SELECT password_hash FROM users WHERE username='bcrypt_check'").fetchone()
        assert user["password_hash"].startswith("$2"), "El hash debe ser bcrypt (empieza con $2)"

    def test_password_incorrecta_rechazada_con_bcrypt(self, client, login_test_user):
        """Contraseña incorrecta devuelve 401 con hash bcrypt."""
        r = client.post("/api/auth/login", json={
            "username": login_test_user["username"],
            "password": "password_totalmente_incorrecta",
        })
        assert r.status_code == 401

    def test_migracion_sha256_a_bcrypt_en_login(self, client, admin_hdrs, test_db):
        """
        Simula el escenario de migración: un usuario existente con hash SHA-256
        lo loguea correctamente y su hash se actualiza a bcrypt.
        """
        import hashlib
        # 1. Crear usuario con hash SHA-256 directamente en la DB (simula pre-migración)
        sha256_hash = hashlib.sha256("mipass789".encode()).hexdigest()
        test_db.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role, nombre) VALUES (?,?,?,?)",
            ("legacy_sha256_user", sha256_hash, "vendedor", "Legacy User")
        )
        test_db.commit()

        # 2. Login → debe funcionar con SHA-256 y migrar a bcrypt
        r = client.post("/api/auth/login", json={"username": "legacy_sha256_user", "password": "mipass789"})
        assert r.status_code == 200

        # 3. Verificar que el hash fue migrado a bcrypt
        user = test_db.execute("SELECT password_hash FROM users WHERE username='legacy_sha256_user'").fetchone()
        assert user["password_hash"].startswith("$2"), "Hash migrado a bcrypt tras el primer login"

        # 4. Segundo login con el hash ya bcrypt — también debe funcionar
        r2 = client.post("/api/auth/login", json={"username": "legacy_sha256_user", "password": "mipass789"})
        assert r2.status_code == 200

        # 5. Contraseña incorrecta sigue fallando con bcrypt
        r3 = client.post("/api/auth/login", json={"username": "legacy_sha256_user", "password": "wrong"})
        assert r3.status_code == 401


class TestVendedorAuth:
    def test_vendedor_puede_loguearse(self, client, vendedor_hdrs):
        r = client.get("/api/auth/me", headers=vendedor_hdrs)
        assert r.status_code == 200
        assert r.json()["role"] == "vendedor"

    def test_vendedor_no_puede_crear_usuarios(self, client, vendedor_hdrs):
        r = client.post("/api/users", json={
            "username": "intento_intruso",
            "password": "hack123",
            "nombre": "Intruso",
            "role": "admin",
        }, headers=vendedor_hdrs)
        assert r.status_code == 403

    def test_vendedor_no_puede_borrar_usuarios(self, client, vendedor_hdrs):
        r = client.delete("/api/users/1", headers=vendedor_hdrs)
        assert r.status_code == 403

    def test_vendedor_no_puede_listar_usuarios(self, client, vendedor_hdrs):
        r = client.get("/api/users", headers=vendedor_hdrs)
        assert r.status_code == 403
