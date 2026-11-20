from decimal import Decimal
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class CustomerAccount(TimeStampedModel):
    """
    Mirrors a Zuora Customer Account and links it to an internal Django user
    for ownership and authorization checks.
    """

    class Status(models.TextChoices):
        ACTIVE = "Active", "Active"
        DRAFT = "Draft", "Draft"
        CANCELED = "Canceled", "Canceled"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="customer_accounts",
    )
    zuora_account_id = models.CharField(
        max_length=64, unique=True, null=True, blank=True, db_index=True
    )
    account_number = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    email = models.EmailField(db_index=True)
    currency = models.CharField(max_length=3, default="USD")
    balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"]),
        ]

    def __str__(self):
        return f"{self.account_number} - {self.name}"


class Notification(TimeStampedModel):
    """
    Tracks billing, payment, and subscription notifications sent to customers.
    """

    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        WEBHOOK = "WEBHOOK", "Webhook"

    class DeliveryStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"

    account = models.ForeignKey(
        CustomerAccount, on_delete=models.CASCADE, related_name="notifications"
    )
    channel = models.CharField(
        max_length=20, choices=Channel.choices, default=Channel.EMAIL
    )
    subject = models.CharField(max_length=255)
    message = models.TextField()
    status = models.CharField(
        max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["account", "status"]),
        ]

    def __str__(self):
        return f"[{self.status}] {self.subject}"