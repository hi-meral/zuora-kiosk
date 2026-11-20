import hashlib
import json
import structlog
from rest_framework import status
from rest_framework.response import Response
from .models import IdempotencyRecord

logger = structlog.get_logger(__name__)


class IdempotencyMixin:
    """
    CBV mixin that checks the 'Idempotency-Key' HTTP header.
    - If seen before with the same payload: returns the cached response.
    - If seen before with a different payload: returns 409 Conflict.
    """

    def get_idempotency_key(self, request):
        return request.headers.get("Idempotency-Key", "").strip() or None

    def _hash_payload(self, data):
        encoded = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def check_idempotency(self, request):
        key = self.get_idempotency_key(request)
        if not key:
            return None, None

        req_hash = self._hash_payload(request.data)
        record = IdempotencyRecord.objects.filter(
            user=request.user, endpoint=request.path, idempotency_key=key
        ).first()

        if record:
            if record.request_hash != req_hash:
                return (
                    Response(
                        {
                            "error": {
                                "code": "idempotency_conflict",
                                "message": "Idempotency-Key already used with a different payload.",
                                "details": {},
                            }
                        },
                        status=status.HTTP_409_CONFLICT,
                    ),
                    key,
                )
            logger.info("idempotency_cache_hit", endpoint=request.path, key=key)
            return Response(record.response_body, status=record.response_status), key

        return None, key

    def save_idempotency(self, request, key, response_status, response_body):
        if not key:
            return
        IdempotencyRecord.objects.create(
            user=request.user,
            idempotency_key=key,
            endpoint=request.path,
            request_hash=self._hash_payload(request.data),
            response_status=response_status,
            response_body=response_body,
        )