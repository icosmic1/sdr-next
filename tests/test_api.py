import os
os.environ["DATABASE_URL"]="sqlite:///./data/test_sdr_next.db"
from fastapi.testclient import TestClient
from app.main import app

def test_health_and_dashboard():
    with TestClient(app) as client:
        health=client.get("/api/health")
        assert health.status_code==200
        assert health.json()["status"]=="ok"
        page=client.get("/")
        assert page.status_code==200
        assert "Good morning, Manvi" in page.text

def test_import_rejects_wrong_columns():
    with TestClient(app) as client:
        response=client.post("/api/import",files={"file":("bad.csv",b"company,person\nA,B\n","text/csv")})
        assert response.status_code==400

def test_import_rejects_non_csv():
    with TestClient(app) as client:
        response=client.post("/api/import",files={"file":("bad.txt",b"hello","text/plain")})
        assert response.status_code==400
