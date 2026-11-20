import uuid
from django.db import models


class TimeStampedModel(models.Model):
    """
    Abstract base model providing a UUID primary key and automatic
    audit timestamps for all ZuoraKiosk entities.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True