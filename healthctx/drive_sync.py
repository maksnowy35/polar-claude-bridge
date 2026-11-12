"""Google Drive as the archive and the place where the assistant reads context files.

Layout under the root folder (GDRIVE_FOLDER_ID):
    status.md, INDEX.md, monthly.csv, daily/, sessions/, days/    <- push_context
    raw/...                                                        <- push_dir / pull_dir of database/private/raw
    confidential/...                                               <- same for database/confidential (opt-in)

Only requests, no Google SDK: the API surface we need is five calls.
"""
import hashlib
import logging
import mimetypes
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_ROOT_NAME = "polar-claude-bridge"
TIMEOUT_S = 60


class DriveError(RuntimeError):
    pass


def _md5(data):
    return hashlib.md5(data).hexdigest()


class DriveClient:
    def __init__(self, client_id, client_secret, refresh_token, session=None):
        if not (client_id and client_secret and refresh_token):
            raise DriveError("GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET and GDRIVE_REFRESH_TOKEN must be set")
        self._credentials = {"client_id": client_id, "client_secret": client_secret,
                             "refresh_token": refresh_token, "grant_type": "refresh_token"}
        self.session = session or requests.Session()
        self._access_token = None
        self._listing_cache = {}

    def _authorize(self):
        response = self.session.request("POST", TOKEN_URL, data=self._credentials, timeout=TIMEOUT_S)
        if response.status_code in (400, 401):
            # Google answers invalid_grant when the refresh token expired or was revoked;
            # tokens of an OAuth app in "Testing" status die after 7 days.
            raise DriveError("Google rejected the refresh token (invalid_grant?), generate a new one, see README")
        if response.status_code >= 400:
            raise DriveError(f"token endpoint returned {response.status_code}")
        self._access_token = response.json()["access_token"]

    def _call(self, method, url, **kwargs):
        if self._access_token is None:
            self._authorize()
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self._access_token}"
        response = self.session.request(method, url, headers=headers, timeout=TIMEOUT_S, **kwargs)
        if response.status_code == 404:
            raise DriveError("404 from Drive: wrong GDRIVE_FOLDER_ID or the file is not visible to this OAuth app")
        if response.status_code == 403:
            raise DriveError("403 from Drive: no access to the folder or quota exceeded")
        if response.status_code >= 400:
            raise DriveError(f"{response.status_code} from Drive for {method} {url}")
        return response

    def list_children(self, folder_id):
        if folder_id in self._listing_cache:
            return self._listing_cache[folder_id]
        children, page_token = {}, None
        while True:
            params = {"q": f"'{folder_id}' in parents and trashed = false",
                      "fields": "nextPageToken, files(id, name, mimeType, md5Checksum)",
                      "pageSize": 1000}
            if page_token:
                params["pageToken"] = page_token
            body = self._call("GET", FILES_URL, params=params).json()
            for item in body.get("files", []):
                children[item["name"]] = item
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        self._listing_cache[folder_id] = children
        return children

    def ensure_folder(self, parent_id, name, create=True):
        existing = self.list_children(parent_id).get(name)
        if existing:
            return existing["id"]
        if not create:
            return None
        created = self._call("POST", FILES_URL, json={"name": name, "mimeType": FOLDER_MIME,
                                                      "parents": [parent_id]}).json()
        self.list_children(parent_id)[name] = {"id": created["id"], "name": name, "mimeType": FOLDER_MIME}
        return created["id"]

    def upload(self, parent_id, name, data):
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        existing = self.list_children(parent_id).get(name)
        file_id = existing["id"] if existing else None
        if file_id is None:
            # metadata first, then content: simpler than a multipart body and only one more call
            file_id = self._call("POST", FILES_URL, json={"name": name, "parents": [parent_id]}).json()["id"]
        self._call("PATCH", f"{UPLOAD_URL}/{file_id}", params={"uploadType": "media"},
                   data=data, headers={"Content-Type": content_type})
        self.list_children(parent_id)[name] = {"id": file_id, "name": name, "md5Checksum": _md5(data)}
        return file_id

    def download(self, file_id):
        return self._call("GET", f"{FILES_URL}/{file_id}", params={"alt": "media"}).content


def resolve_root(client, folder_id, dry_run=False):
    if folder_id:
        return folder_id
    # With the drive.file scope the app only sees folders it created itself, so it owns its root.
    root_id = client.ensure_folder("root", DEFAULT_ROOT_NAME, create=not dry_run)
    logger.warning("GDRIVE_FOLDER_ID not set, using '%s' (id %s), put the id in .env", DEFAULT_ROOT_NAME, root_id)
    return root_id


def _folder_for(client, root_id, parts, dry_run):
    folder_id = root_id
    for part in parts:
        folder_id = client.ensure_folder(folder_id, part, create=not dry_run)
        if folder_id is None:
            return None
    return folder_id


def push_files(client, root_id, base_dir, rel_paths, remote_prefix=(), dry_run=False):
    base_dir = Path(base_dir)
    uploaded = 0
    for rel_path in rel_paths:
        local = base_dir / rel_path
        if not local.is_file():
            continue
        data = local.read_bytes()
        parts = Path(rel_path).parts
        folder_id = _folder_for(client, root_id, list(remote_prefix) + list(parts[:-1]), dry_run)
        remote = client.list_children(folder_id).get(parts[-1]) if folder_id else None
        if remote and remote.get("md5Checksum") == _md5(data):
            continue
        logger.debug("upload %s", "/".join(list(remote_prefix) + list(parts)))
        if not dry_run:
            client.upload(folder_id, parts[-1], data)
        uploaded += 1
    return uploaded


def push_context(client, root_id, context_dir, dry_run=False):
    changed_list = Path(context_dir) / ".changed.txt"
    if not changed_list.exists():
        logger.info("no .changed.txt in %s, nothing to push", context_dir)
        return 0
    rel_paths = [line for line in changed_list.read_text(encoding="utf-8").splitlines() if line]
    uploaded = push_files(client, root_id, context_dir, rel_paths, dry_run=dry_run)
    logger.info("context: %d of %d changed files %s", uploaded, len(rel_paths),
                "would be uploaded" if dry_run else "uploaded")
    return uploaded


def push_dir(client, root_id, local_dir, remote_name, dry_run=False):
    local_dir = Path(local_dir)
    if not local_dir.exists():
        logger.info("%s does not exist, nothing to push", local_dir)
        return 0
    rel_paths = [p.relative_to(local_dir).as_posix() for p in sorted(local_dir.rglob("*")) if p.is_file()]
    uploaded = push_files(client, root_id, local_dir, rel_paths, remote_prefix=(remote_name,), dry_run=dry_run)
    logger.info("%s: %d of %d files %s", remote_name, uploaded, len(rel_paths),
                "would be uploaded" if dry_run else "uploaded")
    return uploaded


def pull_dir(client, root_id, remote_name, local_dir, dry_run=False):
    folder_id = client.list_children(root_id).get(remote_name, {}).get("id")
    if folder_id is None:
        logger.info("no '%s' folder on Drive yet, nothing to pull", remote_name)
        return 0
    downloaded = _pull_folder(client, folder_id, Path(local_dir), dry_run)
    logger.info("%s: %d files %s", remote_name, downloaded, "would be downloaded" if dry_run else "downloaded")
    return downloaded


def _pull_folder(client, folder_id, local_dir, dry_run):
    downloaded = 0
    for name, item in client.list_children(folder_id).items():
        target = local_dir / name
        if item.get("mimeType") == FOLDER_MIME:
            downloaded += _pull_folder(client, item["id"], target, dry_run)
            continue
        if target.exists() and _md5(target.read_bytes()) == item.get("md5Checksum"):
            continue
        downloaded += 1
        if dry_run:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(client.download(item["id"]))
    return downloaded
