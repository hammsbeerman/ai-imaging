import email
import imaplib
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime

from django.conf import settings
from django.utils import timezone

from indexer.models_mail import InboundEmail


def _setting(name: str, default=""):
    return getattr(settings, name, default)


def decode_mime_header(value: str) -> str:
    if not value:
        return ""
    out = []
    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            out.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            out.append(part)
    return "".join(out).strip()


def extract_body_text(msg) -> str:
    if msg.is_multipart():
        parts = []
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")
            if "attachment" in disposition.lower():
                continue
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    parts.append(payload.decode(charset, errors="replace"))
        return "\n\n".join(p.strip() for p in parts if p and p.strip()).strip()

    payload = msg.get_payload(decode=True)
    if payload:
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace").strip()
    return ""


def connect_imap():
    host = _setting("IMAP_HOST", "")
    port = int(_setting("IMAP_PORT", 993) or 993)
    username = _setting("IMAP_USERNAME", "")
    password = _setting("IMAP_PASSWORD", "")
    mailbox = _setting("IMAP_MAILBOX", "INBOX") or "INBOX"
    use_ssl = bool(_setting("IMAP_USE_SSL", True))

    if not host or not username or not password:
        raise RuntimeError("IMAP settings are incomplete")

    client = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
    client.login(username, password)
    status, _ = client.select(mailbox)
    if status != "OK":
        raise RuntimeError(f"Unable to select IMAP mailbox {mailbox}")
    return client, mailbox


def fetch_unread_uids(client):
    status, data = client.uid("search", None, "UNSEEN")
    if status != "OK":
        return []
    raw = data[0] or b""
    return [uid for uid in raw.split() if uid]


def parse_received_at(msg):
    raw = msg.get("Date", "")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt is None:
            return None
        if dt.tzinfo is None:
            return timezone.make_aware(dt, timezone.get_current_timezone())
        return dt
    except Exception:
        return None


def import_email_from_uid(client, mailbox: str, uid: bytes):
    status, data = client.uid("fetch", uid, "(RFC822)")
    if status != "OK" or not data:
        raise RuntimeError(f"Could not fetch email UID {uid!r}")

    raw_bytes = None
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2:
            raw_bytes = item[1]
            break
    if not raw_bytes:
        raise RuntimeError(f"No RFC822 payload found for UID {uid!r}")

    msg = email.message_from_bytes(raw_bytes)
    source_message_id = (msg.get("Message-ID") or "").strip()
    if source_message_id and InboundEmail.objects.filter(source_message_id=source_message_id).exists():
        return None

    from_name, from_email = parseaddr(msg.get("From", ""))
    obj = InboundEmail.objects.create(
        source_message_id=source_message_id,
        imap_uid=uid.decode("utf-8", errors="ignore"),
        mailbox=mailbox,
        from_name=decode_mime_header(from_name),
        from_email=from_email,
        to_emails=msg.get("To", "") or "",
        subject=decode_mime_header(msg.get("Subject", "")),
        body_text=extract_body_text(msg),
        received_at=parse_received_at(msg),
        status=InboundEmail.STATUS_PENDING,
    )
    return obj, msg


def mark_uid_seen(client, uid: bytes):
    client.uid("store", uid, "+FLAGS", "(\\Seen)")
