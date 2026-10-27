"""Firestore implementation; no disk or memory fallback in the application."""
import logging
import base64
import gzip
import json

import google.auth
from google.api_core.exceptions import AlreadyExists, GoogleAPICallError, NotFound, ResourceExhausted, TooManyRequests
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.oauth2 import service_account

from app.errors import (ConversationNotFound, RecordConflict, RecordNotFound,
                        StoreUnavailable, StoreQuotaExceeded, TooManyRecords)

log = logging.getLogger(__name__)


def unavailable(operation, exc):
    """Keep the useful Firestore failure reason in server logs, never API output."""
    status = getattr(exc, "code", None)
    status = status() if callable(status) else status
    log.warning("Firestore %s failed: %s %s", operation, status or type(exc).__name__, str(exc)[:500])
    if isinstance(exc, (ResourceExhausted, TooManyRequests)):
        return StoreQuotaExceeded("Firestore quota exceeded")
    return StoreUnavailable("Firestore operation failed: " + operation)


class FirestoreRepository:
    def __init__(self, settings):
        if not settings.firebase_project_id:
            raise StoreUnavailable("Firebase 프로젝트 설정이 필요합니다")
        try:
            if settings.firestore_emulator_host:
                credentials = AnonymousCredentials()
            elif settings.google_application_credentials:
                credentials = service_account.Credentials.from_service_account_file(settings.google_application_credentials)
            else:
                credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/datastore"])
            self.client = firestore.Client(project=settings.firebase_project_id, credentials=credentials,
                                           database=settings.firestore_database)
            self.collection = self.client.collection("data")
            self.conversations = self.client.collection("conversations")
            self.analysis_cache = self.client.collection("analysis_cache")
        except Exception as exc:
            log.warning("Firestore client initialization failed (%s)", type(exc).__name__)
            raise StoreUnavailable("Firestore 인증 설정을 확인하세요") from exc

    @staticmethod
    def decode(snapshot):
        return {**snapshot.to_dict(), "id": snapshot.id}

    def get(self, record_id):
        try:
            snapshot = self.collection.document(record_id).get(timeout=10, retry=None)
            if not snapshot.exists:
                raise RecordNotFound()
            return self.decode(snapshot)
        except GoogleAPICallError as exc:
            raise unavailable("get", exc) from exc

    def create(self, record_id, data):
        try:
            self.collection.document(record_id).create(data, timeout=10, retry=None)
            return {**data, "id": record_id}
        except AlreadyExists as exc:
            raise RecordConflict() from exc
        except GoogleAPICallError as exc:
            raise unavailable("create", exc) from exc

    def update(self, record_id, changes):
        try:
            self.collection.document(record_id).update(changes, timeout=10, retry=None)
            return self.get(record_id)
        except NotFound as exc:
            raise RecordNotFound() from exc
        except GoogleAPICallError as exc:
            raise unavailable("update", exc) from exc

    def delete(self, record_id):
        ref = self.collection.document(record_id)

        @firestore.transactional
        def remove(transaction):
            snapshot = ref.get(transaction=transaction, timeout=10, retry=None)
            if not snapshot.exists:
                raise RecordNotFound()
            transaction.delete(ref)

        try:
            remove(self.client.transaction())
        except GoogleAPICallError as exc:
            raise unavailable("delete", exc) from exc

    def list_page(self, limit, cursor=None, item_name=None):
        # Firestore orders the entire matching result before applying the limit.
        query = (self.collection.order_by("year_month", direction=firestore.Query.DESCENDING)
                 .order_by("__name__", direction=firestore.Query.DESCENDING))
        if item_name:
            query = query.where(filter=FieldFilter("item_name", "==", item_name))
        if cursor:
            year_month, record_id = cursor.split(":", 1)
            query = query.start_after({"year_month": year_month,
                                       "__name__": self.collection.document(record_id)})
        try:
            rows = [self.decode(doc) for doc in query.limit(limit + 1).stream(timeout=10, retry=None)]
        except GoogleAPICallError as exc:
            raise unavailable("list page", exc) from exc
        more = len(rows) > limit
        next_cursor = f"{rows[limit - 1]['year_month']}:{rows[limit - 1]['id']}" if more else None
        return {"items": rows[:limit], "next_cursor": next_cursor, "has_more": more}

    def analysis_records(self, first_month, last_month, max_records):
        query = (self.collection.where(filter=FieldFilter("year_month", ">=", first_month))
                 .where(filter=FieldFilter("year_month", "<=", last_month)).limit(max_records + 1))
        try:
            rows = [self.decode(doc) for doc in query.stream(timeout=30, retry=None)]
        except GoogleAPICallError as exc:
            raise unavailable("analysis query", exc) from exc
        if len(rows) > max_records:
            raise TooManyRecords()
        return rows

    def analysis_revision(self):
        try:
            snap = self.analysis_cache.document('revision').get(timeout=10, retry=None)
            return int(snap.get('revision') or 0) if snap.exists else 0
        except GoogleAPICallError as exc:
            raise unavailable('analysis cache revision', exc) from exc

    def read_analysis_cache(self, revision, start_year, end_year, min_years):
        try:
            summary = self.analysis_cache.document('summary').get(timeout=10, retry=None)
            trends = self.analysis_cache.document('trends').get(timeout=10, retry=None)
            if not summary.exists or not trends.exists:
                return None
            a, t = summary.to_dict(), trends.to_dict()
            expected = (revision, start_year, end_year, min_years)
            if tuple(a.get(k) for k in ('revision','start_year','end_year','min_years')) != expected:
                return None
            if tuple(t.get(k) for k in ('revision','start_year','end_year','min_years')) != expected:
                return None
            analysis = {**json.loads(gzip.decompress(base64.b64decode(a['payload']))),
                        'price_trends': json.loads(gzip.decompress(base64.b64decode(t['payload'])))}
            return analysis
        except GoogleAPICallError as exc:
            raise unavailable('analysis cache read', exc) from exc

    def write_analysis_cache(self, revision, start_year, end_year, min_years, analysis):
        config = {'revision': revision, 'start_year': start_year, 'end_year': end_year, 'min_years': min_years}
        try:
            summary = {k: analysis[k] for k in ('metadata', 'rankings', 'monthly_patterns')}
            summary_bytes = json.dumps(summary, ensure_ascii=False, separators=(',', ':'), default=str).encode()
            trends_bytes = json.dumps(analysis['price_trends'], ensure_ascii=False,
                                      separators=(',', ':'), default=str).encode()
            self.analysis_cache.document('summary').set({**config, 'payload': base64.b64encode(gzip.compress(summary_bytes)).decode('ascii')})
            self.analysis_cache.document('trends').set({**config, 'payload': base64.b64encode(gzip.compress(trends_bytes)).decode('ascii')})
        except GoogleAPICallError as exc:
            raise unavailable('analysis cache write', exc) from exc

    def mark_analysis_stale(self):
        try:
            self.analysis_cache.document('revision').set({'revision': firestore.Increment(1)}, merge=True)
        except GoogleAPICallError as exc:
            raise unavailable('analysis cache invalidate', exc) from exc

    def probe(self):
        try:
            list(self.collection.limit(1).stream(timeout=5, retry=None))
        except GoogleAPICallError as exc:
            raise unavailable("health probe", exc) from exc

    def get_conversation(self, conversation_id, owner_id):
        try:
            snapshot = self.conversations.document(conversation_id).get(timeout=10, retry=None)
            if not snapshot.exists or snapshot.get("owner_id") != owner_id:
                raise ConversationNotFound()
            return self.decode(snapshot)
        except GoogleAPICallError as exc:
            raise unavailable("conversation load", exc) from exc

    def list_conversations(self, owner_id, limit=30):
        query = self.conversations.where(filter=FieldFilter("owner_id", "==", owner_id)).limit(limit)
        try:
            return [self.decode(doc) for doc in query.stream(timeout=10, retry=None)]
        except GoogleAPICallError as exc:
            raise unavailable("conversation list", exc) from exc

    def append_conversation(self, conversation_id, owner_id, user_message, assistant_message):
        ref = self.conversations.document(conversation_id)
        now = firestore.SERVER_TIMESTAMP

        @firestore.transactional
        def append(transaction):
            snapshot = ref.get(transaction=transaction)
            created = not snapshot.exists
            if created:
                document = {"owner_id": owner_id,
                            "title": user_message["content"][:72],
                            "created_at": now, "updated_at": now,
                            "messages": [user_message, assistant_message]}
                transaction.create(ref, document)
            else:
                if snapshot.get("owner_id") != owner_id:
                    raise ConversationNotFound()
                history = snapshot.get("messages") or []
                history.extend([user_message, assistant_message])
                transaction.update(ref, {"messages": history[-100:], "updated_at": now})
            return created

        try:
            created = append(self.client.transaction())
            saved = self.get_conversation(conversation_id, owner_id)
            return saved, created
        except GoogleAPICallError as exc:
            raise unavailable("conversation save", exc) from exc
