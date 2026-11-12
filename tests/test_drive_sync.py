import hashlib
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from healthctx.drive_sync import (FILES_URL, FOLDER_MIME, TOKEN_URL, UPLOAD_URL, DriveClient, DriveError,
                                  pull_dir, push_context, push_dir, resolve_root)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self):
        return self._payload


class FakeDrive:
    """In-memory Drive answering the handful of REST calls DriveClient makes."""

    def __init__(self, token_status=200):
        self.files = {"root": {"id": "root", "name": "My Drive", "mimeType": FOLDER_MIME, "parents": []}}
        self.token_status = token_status
        self.writes = 0
        self._next_id = 0

    def add(self, name, parent, mime=None, content=None):
        self._next_id += 1
        file_id = f"f{self._next_id}"
        self.files[file_id] = {"id": file_id, "name": name, "parents": [parent], "mimeType": mime, "content": content}
        return file_id

    def request(self, method, url, params=None, json=None, data=None, headers=None, timeout=None):
        assert timeout, "every call needs a timeout"
        params = params or {}
        if url == TOKEN_URL:
            return FakeResponse(self.token_status, {"access_token": "t"})
        if method == "GET" and url == FILES_URL:
            parent = re.search(r"'([^']+)' in parents", params["q"]).group(1)
            files = [{"id": f["id"], "name": f["name"], "mimeType": f["mimeType"],
                      **({"md5Checksum": hashlib.md5(f["content"]).hexdigest()} if f["content"] is not None else {})}
                     for f in self.files.values() if parent in f["parents"]]
            return FakeResponse(payload={"files": files})
        if method == "POST" and url == FILES_URL:
            self.writes += 1
            return FakeResponse(payload={"id": self.add(json["name"], json["parents"][0], json.get("mimeType"))})
        if method == "PATCH" and url.startswith(UPLOAD_URL):
            self.writes += 1
            self.files[url.rsplit("/", 1)[1]]["content"] = data
            return FakeResponse()
        if method == "GET" and url.startswith(FILES_URL + "/"):
            file = self.files.get(url.rsplit("/", 1)[1])
            return FakeResponse(payload=None, content=file["content"]) if file else FakeResponse(404)
        return FakeResponse(404)

    def find(self, *path):
        parent = "root_folder"
        for name in path:
            parent = next(f["id"] for f in self.files.values() if f["name"] == name and parent in f["parents"])
        return self.files[parent]


class DriveSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="healthctx-drive-"))
        self.drive = FakeDrive()
        self.drive.files["root_folder"] = {"id": "root_folder", "name": "health", "mimeType": FOLDER_MIME,
                                           "parents": ["root"], "content": None}
        self.client = DriveClient("id", "secret", "refresh", session=self.drive)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text):
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_push_context_uploads_only_changed_files_keeping_folders(self):
        self.write("context/status.md", "status")
        self.write("context/days/day_2026-11-10.md", "day")
        self.write("context/monthly.csv", "not in the changed list")
        self.write("context/.changed.txt", "status.md\ndays/day_2026-11-10.md")

        uploaded = push_context(self.client, "root_folder", self.tmp / "context")

        self.assertEqual(uploaded, 2)
        self.assertEqual(self.drive.find("days", "day_2026-11-10.md")["content"], b"day")
        self.assertFalse(any(f["name"] == "monthly.csv" for f in self.drive.files.values()))

    def test_existing_file_is_updated_not_duplicated(self):
        self.write("context/status.md", "v1")
        self.write("context/.changed.txt", "status.md")
        push_context(self.client, "root_folder", self.tmp / "context")
        self.write("context/status.md", "v2")

        push_context(DriveClient("id", "secret", "refresh", session=self.drive), "root_folder", self.tmp / "context")

        copies = [f for f in self.drive.files.values() if f["name"] == "status.md"]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0]["content"], b"v2")

    def test_raw_round_trip_skips_identical_files(self):
        self.write("raw/api/sleep/2026-11-10.json", '{"x": 1}')
        self.write("raw/export/activity-2026-06-09.json", '{"y": 2}')
        self.assertEqual(push_dir(self.client, "root_folder", self.tmp / "raw", "raw"), 2)

        fresh = DriveClient("id", "secret", "refresh", session=self.drive)
        self.assertEqual(push_dir(fresh, "root_folder", self.tmp / "raw", "raw"), 0)

        self.assertEqual(pull_dir(fresh, "root_folder", "raw", self.tmp / "restored"), 2)
        self.assertEqual((self.tmp / "restored/api/sleep/2026-11-10.json").read_text(), '{"x": 1}')

    def test_dry_run_writes_nothing(self):
        self.write("raw/api/sleep/2026-11-10.json", "{}")

        self.assertEqual(push_dir(self.client, "root_folder", self.tmp / "raw", "raw", dry_run=True), 1)
        self.assertEqual(self.drive.writes, 0)

    def test_root_folder_is_created_when_id_missing(self):
        with self.assertLogs("healthctx.drive_sync", level="WARNING"):
            root_id = resolve_root(self.client, "")

        self.assertEqual(self.drive.files[root_id]["name"], "polar-claude-bridge")

    def test_rejected_refresh_token(self):
        client = DriveClient("id", "secret", "refresh", session=FakeDrive(token_status=400))

        with self.assertRaisesRegex(DriveError, "refresh token"):
            client.list_children("root")

    def test_missing_credentials(self):
        with self.assertRaises(DriveError):
            DriveClient("", "secret", "refresh")


if __name__ == "__main__":
    unittest.main()
