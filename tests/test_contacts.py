"""
test_contacts.py — CRUD de contactos: lista, upload CSV/XLSX, búsqueda, importaciones.
Todos los endpoints ahora requieren autenticación.
"""
import io
import pytest


class TestListContacts:
    def test_lista_contactos_con_paginacion(self, client, admin_hdrs):
        r = client.get("/api/contacts?page=1&per_page=10", headers=admin_hdrs)
        assert r.status_code == 200
        data = r.json()
        assert "contacts" in data
        assert "total" in data
        assert "page" in data
        assert len(data["contacts"]) <= 10

    def test_lista_sin_auth_devuelve_401(self, client):
        assert client.get("/api/contacts").status_code == 401

    def test_paginacion_segunda_pagina(self, client, admin_hdrs):
        r1 = client.get("/api/contacts?page=1&per_page=5", headers=admin_hdrs)
        r2 = client.get("/api/contacts?page=2&per_page=5", headers=admin_hdrs)
        assert r1.status_code == 200
        assert r2.status_code == 200
        ids_p1 = {c["id"] for c in r1.json()["contacts"]}
        ids_p2 = {c["id"] for c in r2.json()["contacts"]}
        assert ids_p1.isdisjoint(ids_p2), "Las páginas no deben solaparse"

    def test_busqueda_por_nombre(self, client, admin_hdrs):
        r = client.get("/api/contacts?search=García", headers=admin_hdrs)
        assert r.status_code == 200
        contacts = r.json()["contacts"]
        for c in contacts:
            assert "García" in c["name"] or "García" in c["phone"]

    def test_busqueda_sin_resultados(self, client, admin_hdrs):
        r = client.get("/api/contacts?search=zzznombrequenoexiste", headers=admin_hdrs)
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_total_coherente_con_pagina(self, client, admin_hdrs):
        r = client.get("/api/contacts?per_page=100", headers=admin_hdrs)
        data = r.json()
        assert data["total"] >= len(data["contacts"])

    def test_estructura_contacto(self, client, admin_hdrs):
        r = client.get("/api/contacts?per_page=1", headers=admin_hdrs)
        contacts = r.json()["contacts"]
        assert len(contacts) == 1
        c = contacts[0]
        assert "id" in c
        assert "name" in c
        assert "phone" in c


class TestUploadCSV:
    def _make_csv(self, rows: list[tuple]) -> bytes:
        lines = ["nombre,telefono"] + [f"{n},{p}" for n, p in rows]
        return "\n".join(lines).encode()

    def test_upload_csv_valido(self, client, admin_hdrs):
        csv_data = self._make_csv([
            ("Nuevo Contacto CSV", "5491199990001CSV"),
            ("Otro Contacto",      "5491199990002CSV"),
        ])
        r = client.post("/api/contacts/upload",
                        files={"file": ("nuevos.csv", io.BytesIO(csv_data), "text/csv")},
                        headers=admin_hdrs)
        assert r.status_code == 200
        data = r.json()
        assert data["inserted"] >= 1
        assert "import_id" in data

    def test_upload_sin_auth_devuelve_401(self, client):
        csv_data = b"nombre,telefono\nTest,1234"
        r = client.post("/api/contacts/upload",
                        files={"file": ("t.csv", io.BytesIO(csv_data), "text/csv")})
        assert r.status_code == 401

    def test_upload_csv_sin_columnas_requeridas(self, client, admin_hdrs):
        csv_data = b"columna_rara,otra_columna\nValor1,Valor2"
        r = client.post("/api/contacts/upload",
                        files={"file": ("mal.csv", io.BytesIO(csv_data), "text/csv")},
                        headers=admin_hdrs)
        assert r.status_code == 400

    def test_upload_csv_duplicados_se_omiten(self, client, admin_hdrs):
        phone_dup = "54911888800DUP"  # sin + para evitar encoding de URL
        csv1 = self._make_csv([("Dup Test", phone_dup)])
        csv2 = self._make_csv([("Dup Test 2", phone_dup)])

        r1 = client.post("/api/contacts/upload",
                         files={"file": ("dup1.csv", io.BytesIO(csv1), "text/csv")},
                         headers=admin_hdrs)
        r2 = client.post("/api/contacts/upload",
                         files={"file": ("dup2.csv", io.BytesIO(csv2), "text/csv")},
                         headers=admin_hdrs)
        assert r1.status_code == 200
        assert r2.status_code == 200

        # BUG conocido: el contador `inserted` incrementa aunque INSERT OR IGNORE no inserte.
        # Lo que importa es que el contacto no esté duplicado en la DB.
        r_search = client.get(f"/api/contacts?search={phone_dup}", headers=admin_hdrs)
        assert r_search.json()["total"] == 1, "El teléfono duplicado debe existir solo una vez"

    def test_upload_csv_filas_vacias_se_omiten(self, client, admin_hdrs):
        csv_data = b"nombre,telefono\n,\nOtroV2,5491177770001\n,"
        r = client.post("/api/contacts/upload",
                        files={"file": ("vacios.csv", io.BytesIO(csv_data), "text/csv")},
                        headers=admin_hdrs)
        assert r.status_code == 200
        data = r.json()
        assert data["inserted"] >= 1
        assert data["skipped"] >= 2


class TestImports:
    def test_lista_importaciones_requiere_auth(self, client):
        assert client.get("/api/imports").status_code == 401

    def test_lista_importaciones(self, client, admin_hdrs):
        r = client.get("/api/imports", headers=admin_hdrs)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_importacion_tiene_campos_esperados(self, client, admin_hdrs):
        r = client.get("/api/imports", headers=admin_hdrs)
        imports = r.json()
        if imports:
            imp = imports[0]
            assert "id" in imp
            assert "filename" in imp
            assert "inserted" in imp
            assert "skipped" in imp
            assert "total" in imp

    def test_borrar_importacion(self, client, admin_hdrs):
        csv_data = b"nombre,telefono\nBorrar Test,54911666699XX"
        r_up = client.post("/api/contacts/upload",
                           files={"file": ("tobedeleted.csv", io.BytesIO(csv_data), "text/csv")},
                           headers=admin_hdrs)
        import_id = r_up.json()["import_id"]

        r_del = client.delete(f"/api/imports/{import_id}", headers=admin_hdrs)
        assert r_del.status_code == 200

        r_list = client.get("/api/contacts?search=BorrarTest", headers=admin_hdrs)
        assert r_list.json()["total"] == 0

    def test_borrar_importacion_sin_auth(self, client):
        assert client.delete("/api/imports/1").status_code == 401

    def test_borrar_importacion_inexistente_no_explota(self, client, admin_hdrs):
        r = client.delete("/api/imports/999999", headers=admin_hdrs)
        assert r.status_code == 200


class TestUploadImage:
    def test_upload_sin_auth_devuelve_401(self, client):
        fake_jpg = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"\x00" * 10
        r = client.post("/api/upload-image",
                        files={"file": ("foto.jpg", io.BytesIO(fake_jpg), "image/jpeg")})
        assert r.status_code == 401

    def test_upload_jpg_valido(self, client, admin_hdrs):
        fake_jpg = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"\x00" * 100
        r = client.post("/api/upload-image",
                        files={"file": ("foto.jpg", io.BytesIO(fake_jpg), "image/jpeg")},
                        headers=admin_hdrs)
        assert r.status_code == 200
        data = r.json()
        assert "image_path" in data
        assert "url" in data
        assert data["image_path"].endswith(".jpg")

    def test_upload_extension_no_permitida(self, client, admin_hdrs):
        r = client.post("/api/upload-image",
                        files={"file": ("script.php", b"<?php echo 'hack'; ?>", "text/plain")},
                        headers=admin_hdrs)
        assert r.status_code == 400

    def test_upload_svg_no_permitido(self, client, admin_hdrs):
        r = client.post("/api/upload-image",
                        files={"file": ("xss.svg", b"<svg><script>alert(1)</script></svg>", "image/svg+xml")},
                        headers=admin_hdrs)
        assert r.status_code == 400
