from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class IdempotencyRecord(TimeStampedModel):
    """
    Stores the response of mutating API requests keyed by an Idempotency-Key
    header so retries return the exact same result without duplicating side effects.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="idempotency_records"
    )
    idempotency_key = models.CharField(max_length=128, db_index=True)
    endpoint = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveIntegerField()
    response_body = models.JSONField()

    class Meta:
        # Scope idempotency keys per user and endpoint
        constraints = [
            models.UniqueConstraint(
                fields=["user", "endpoint", "idempotency_key"],
                name="unique_user_endpoint_idempotency_key",
            )
        ]

    def __str__(self):
        return f"{self.endpoint} [{self.idempotency_key}]"