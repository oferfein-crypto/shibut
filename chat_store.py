"""Server-only Firestore persistence for Shibut Mehkar.

Authentication must be verified by Streamlit OIDC; never accept an owner id from
an HTTP request or an untrusted URL. This module does not store user emails.
Google-upload file URIs are deliberately not persisted (they expire).
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
import uuid

from firebase_admin import credentials, firestore as firebase_firestore, get_app, initialize_app
from google.cloud import firestore


COLLECTION = "shibut_conversations_v1"


def account_key(issuer: str, google_sub: str, pepper: str) -> str:
    """Pseudonymize immutable Google OIDC identity, not an editable email address."""
    if not (issuer and google_sub and pepper):
        raise ValueError("Google identity / pepper are missing")
    payload = f"{issuer}|{google_sub}".encode("utf-8")
    return "google_" + hmac.new(pepper.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def firestore_client(service_account_json: str):
    """Initialize one process-global Admin SDK app from a Streamlit Secret."""
    config = json.loads(service_account_json)
    if config.get("type") != "service_account" or not config.get("project_id"):
        raise ValueError("Firebase service-account configuration is invalid")
    app_name = "shibut_mehkar_firestore"
    try:
        app = get_app(app_name)
    except ValueError:
        app = initialize_app(credentials.Certificate(config), name=app_name)
    return firebase_firestore.client(app=app)


def fresh_thread_id() -> str:
    return str(uuid.uuid4())


def fresh_guest_owner() -> str:
    return "guest_" + uuid.uuid4().hex


def _root(db):
    return db.collection(COLLECTION)


def _thread_ref(db, thread_id):
    return _root(db).document(thread_id)


def _verify_owner(db, thread_id: str, owner_key: str):
    doc = _thread_ref(db, thread_id).get()
    if not doc.exists:
        raise LookupError("השיחה אינה קיימת.")
    if doc.to_dict().get("owner_key") != owner_key:
        raise PermissionError("אין הרשאה לגשת לשיחה.")
    return doc


def append_message(
    db, *, thread_id: str, owner_key: str, auth_mode: str,
    message: dict, new_thread: bool, first_title: str = "",
):
    """Atomically persist a message and update the conversation index.

    Caller must derive owner_key from authenticated st.user or guest session.
    The caller generates message.id once so a retry cannot duplicate it.
    """
    if auth_mode not in ("google", "guest"):
        raise ValueError("invalid auth_mode")
    if not isinstance(thread_id, str) or not isinstance(owner_key, str):
        raise ValueError("invalid owner/thread")
    if not thread_id or not owner_key:
        raise ValueError("missing owner/thread")
    if message.get("role") not in ("user", "assistant"):
        raise ValueError("invalid role")

    ref = _thread_ref(db, thread_id)
    text = str(message.get("content", ""))
    if not message.get("id"):
        raise ValueError("missing unique message id")
    safe_graphic = message.get("graphic")
    safe_files = [
        {"name": str(f.get("name", ""))[:250],
         "mime_type": str(f.get("mime_type", ""))[:100]}
        for f in (message.get("files") or [])
    ]
    msg_ref = ref.collection("messages").document(message["id"])
    # No Gemini file URI, access tokens, email, uploaded file contents or cookie.
    msg_data = {
        "role": message["role"],
        "content": text,
        "graphic": safe_graphic,
        "files": safe_files,
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    title = (first_title or text).replace("\n", " ").strip()[:90] or "שיחה חדשה"
    update = {
        "updated_at": firestore.SERVER_TIMESTAMP,
        "message_count": firestore.Increment(1),
    }
    @firestore.transactional
    def save(transaction):
        existing = ref.get(transaction=transaction)
        if existing.exists:
            data = existing.to_dict()
            if data.get("owner_key") != owner_key or data.get("auth_mode") != auth_mode:
                raise PermissionError("אין הרשאה לעדכן שיחה זו.")
        elif not new_thread:
            raise LookupError("השיחה טרם נוצרה במסד הנתונים.")

        if msg_ref.get(transaction=transaction).exists:
            return
        thread_update = dict(update)
        if not existing.exists:
            thread_update.update({
                "owner_key": owner_key,
                "auth_mode": auth_mode,
                "title": title,
                "created_at": firestore.SERVER_TIMESTAMP,
            })
        transaction.create(msg_ref, msg_data)
        transaction.set(ref, thread_update, merge=True)

    save(db.transaction())


def list_user_threads(db, owner_key: str, limit=100):
    """No composite index needed. For the usual course load, read up to 1000."""
    from google.cloud.firestore_v1.base_query import FieldFilter
    query = _root(db).where(filter=FieldFilter("owner_key", "==", owner_key)).limit(1000)
    docs = list(query.stream())
    rows = [{"id": d.id, **d.to_dict()} for d in docs]
    return sorted(rows, key=lambda x: x.get("updated_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:limit]


def read_thread(db, thread_id: str, owner_key: str):
    """Enforce ownership in the server before reading messages."""
    meta = _verify_owner(db, thread_id, owner_key)
    return {"id": meta.id, **meta.to_dict()}, read_messages(db, thread_id)


def read_messages(db, thread_id):
    query = _thread_ref(db, thread_id).collection("messages").order_by("created_at")
    return [{"id": d.id, **d.to_dict()} for d in query.stream()]


def recent_threads(db, limit=250):
    q = _root(db).order_by("updated_at", direction=firestore.Query.DESCENDING).limit(limit)
    return [{"id": d.id, **d.to_dict()} for d in q.stream()]


def _lecturer_archive_settings(db):
    return db.collection("shibut_settings").document("lecturer_archive")


def lecturer_archive_cutoff(db):
    """Timestamp through which conversations are excluded from the general archive."""
    snapshot = _lecturer_archive_settings(db).get()
    return (snapshot.to_dict() or {}).get("cleared_at")


def clear_lecturer_archive(db, expected_cutoff):
    """Reset the general archive without modifying any account's conversation records."""
    ref = _lecturer_archive_settings(db)

    @firestore.transactional
    def clear(transaction):
        snapshot = ref.get(transaction=transaction)
        if (snapshot.to_dict() or {}).get("cleared_at") != expected_cutoff:
            return False
        transaction.set(ref, {"cleared_at": firestore.SERVER_TIMESTAMP}, merge=True)
        return True

    return clear(db.transaction())


def all_threads(db, *, after=None):
    """Admin only. Might be expensive on a large Firestore dataset."""
    query = _root(db)
    if after is not None:
        from google.cloud.firestore_v1.base_query import FieldFilter
        query = query.where(filter=FieldFilter("created_at", ">", after))
    for doc in query.stream():
        yield {"id": doc.id, **doc.to_dict()}


def _safe_csv_text(value):
    """Prevent spreadsheet CSV formula injection in user-supplied chat content."""
    value = str(value or "")
    if value.lstrip().startswith(("=", "+", "-", "@")) or value[:1] in ("\t", "\r", "\n"):
        return "'" + value
    return value


def _time_iso(obj):
    return obj.isoformat() if hasattr(obj, "isoformat") else str(obj or "")


def transcript_csv(db, threads) -> bytes:
    """Excel-compatible UTF-8 CSV with ALL text and graphics descriptors."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "conversation_id", "auth_mode", "anonymous_user_id", "title",
        "conversation_created_utc", "message_created_utc", "role",
        "text", "attached_file_names", "visualization_json",
    ])
    for thread in threads:
        for msg in read_messages(db, thread["id"]):
            writer.writerow([
                thread["id"], thread.get("auth_mode", ""),
                thread.get("owner_key", ""), _safe_csv_text(thread.get("title", "")),
                _time_iso(thread.get("created_at")), _time_iso(msg.get("created_at")),
                msg.get("role", ""), _safe_csv_text(msg.get("content", "")),
                _safe_csv_text(", ".join(f.get("name", "") for f in msg.get("files", []))),
                _safe_csv_text(json.dumps(msg.get("graphic"), ensure_ascii=False)),
            ])
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
