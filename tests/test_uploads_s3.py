# tests/test_uploads_s3.py
"""S3-режим загрузок (двойной режим uploads.py). boto3 замокан — реального S3
в тестах нет. Локальный режим (S3_MEDIA_BUCKET пуст) покрыт test_uploads.py."""
import app.services.uploads as up
from app.core.config import settings
from app.services.uploads import _store, delete_stored


class _FakeS3:
    def __init__(self):
        self.puts = []
        self.deletes = []

    def put_object(self, **kw):
        self.puts.append(kw)

    def delete_object(self, **kw):
        self.deletes.append(kw)


def _enable_s3(monkeypatch, fake):
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", "photos-bucket")
    monkeypatch.setattr(settings, "S3_MEDIA_PREFIX", "staging")
    monkeypatch.setattr(settings, "S3_PUBLIC_URL_BASE", "https://photos-bucket.s3.twcstorage.ru")
    monkeypatch.setattr(up, "_s3_client", fake)  # подменяем клиента (boto3 не импортируется)


def test_store_uploads_to_s3(monkeypatch):
    fake = _FakeS3()
    _enable_s3(monkeypatch, fake)
    url = _store(b"jpegbytes", "avatars")
    assert url.startswith("https://photos-bucket.s3.twcstorage.ru/staging/avatars/")
    assert url.endswith(".jpg")
    assert len(fake.puts) == 1
    put = fake.puts[0]
    assert put["Bucket"] == "photos-bucket"
    assert put["Key"].startswith("staging/avatars/") and put["Key"].endswith(".jpg")
    assert put["Body"] == b"jpegbytes" and put["ContentType"] == "image/jpeg"


def test_delete_stored_s3(monkeypatch):
    fake = _FakeS3()
    _enable_s3(monkeypatch, fake)
    delete_stored("https://photos-bucket.s3.twcstorage.ru/staging/salons/abc.jpg")
    assert fake.deletes == [{"Bucket": "photos-bucket", "Key": "staging/salons/abc.jpg"}]


def test_delete_stored_local_fallback_when_s3_on(monkeypatch, tmp_path):
    # S3 включён, но передан ЛОКАЛЬНЫЙ /uploads-URL (переходный период) —
    # удаляем локальный файл, S3 не трогаем.
    fake = _FakeS3()
    _enable_s3(monkeypatch, fake)
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))
    d = tmp_path / "avatars"
    d.mkdir()
    f = d / "x.jpg"
    f.write_bytes(b"z")
    delete_stored("/uploads/avatars/x.jpg")
    assert not f.exists()      # локальный удалён
    assert fake.deletes == []  # S3 не тронут


def test_local_mode_unchanged(monkeypatch, tmp_path):
    # S3_MEDIA_BUCKET пуст → старое локальное поведение (fallback).
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", "")
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))
    url = _store(b"jpeg", "avatars")
    assert url.startswith("/uploads/avatars/") and url.endswith(".jpg")
    assert (tmp_path / "avatars").exists()
