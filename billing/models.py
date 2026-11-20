from decimal import Decimal
from django.db import models
from core.models import TimeStampedModel
from accounts.models import CustomerAccount


class Product(TimeStampedModel):
    """
    Represents a sellable product in the Zuora Product Catalog.
    """

    zuora_product_id = models.CharField(
        max_length=64, unique=True, null=True, blank=True, db_index=True
    )
    sku = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    def __str__(self):
        return f"{self.sku} - {self.name}"


class ProductRatePlan(TimeStampedModel):
    """
    Pricing tier / billing frequency attached to a Product.
    """

    class BillingPeriod(models.TextChoices):
        MONTHLY = "Month", "Monthly"
        ANNUAL = "Year", "Annual"

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="rate_plans"
    )
    zuora_rate_plan_id = models.CharField(
        max_length=64, unique=True, null=True, blank=True, db_index=True
    )
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    billing_period = models.CharField(
        max_length=20, choices=BillingPeriod.choices, default=BillingPeriod.MONTHLY
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.product.name} - {self.name} ({self.price} {self.currency})"


class Subscription(TimeStampedModel):
    """
    Tracks a customer's active or historical subscription lifecycle.
    """

    class Status(models.TextChoices):
        ACTIVE = "Active", "Active"
        PENDING = "Pending", "Pending"
        CANCELED = "Canceled", "Canceled"
        EXPIRED = "Expired", "Expired"

    account = models.ForeignKey(
        CustomerAccount, on_delete=models.PROTECT, related_name="subscriptions"
    )
    rate_plan = models.ForeignKey(
        ProductRatePlan, on_delete=models.PROTECT, related_name="subscriptions"
    )
    zuora_subscription_id = models.CharField(
        max_length=64, unique=True, null=True, blank=True, db_index=True
    )
    subscription_number = models.CharField(max_length=64, unique=True, db_index=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    term_start_date = models.DateField()
    term_end_date = models.DateField()
    auto_renew = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["account", "status"]),
        ]

    def __str__(self):
        return f"{self.subscription_number} ({self.status})"


class SubscriptionAmendment(TimeStampedModel):
    """
    Records mid-term subscription changes (upgrades, downgrades, cancellations, renewals).
    """

    class AmendmentType(models.TextChoices):
        UPDATE_PRODUCT = "UpdateProduct", "Update Product"
        RENEWAL = "Renewal", "Renewal"
        CANCELLATION = "Cancellation", "Cancellation"

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="amendments"
    )
    zuora_amendment_id = models.CharField(
        max_length=64, unique=True, null=True, blank=True, db_index=True
    )
    amendment_type = models.CharField(max_length=32, choices=AmendmentType.choices)
    effective_date = models.DateField()
    new_rate_plan = models.ForeignKey(
        ProductRatePlan, on_delete=models.PROTECT, null=True, blank=True
    )
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.subscription.subscription_number} - {self.amendment_type}"


class Invoice(TimeStampedModel):
    """
    Stores generated customer invoices and their remaining balance.
    """

    class Status(models.TextChoices):
        DRAFT = "Draft", "Draft"
        POSTED = "Posted", "Posted"
        PAID = "Paid", "Paid"
        CANCELED = "Canceled", "Canceled"

    account = models.ForeignKey(
        CustomerAccount, on_delete=models.PROTECT, related_name="invoices"
    )
    subscription = models.ForeignKey(
        Subscription, on_delete=models.PROTECT, null=True, blank=True, related_name="invoices"
    )
    zuora_invoice_id = models.CharField(
        max_length=64, unique=True, null=True, blank=True, db_index=True
    )
    invoice_number = models.CharField(max_length=64, unique=True, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance = models.DecimalField(max_digits=12, decimal_places=2)
    due_date = models.DateField(db_index=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.POSTED
    )

    class Meta:
        ordering = ["-due_date"]
        indexes = [
            models.Index(fields=["account", "status"]),
        ]

    def __str__(self):
        return f"{self.invoice_number} ({self.status} - {self.balance})"


class Payment(TimeStampedModel):
    """
    Tracks payments applied toward a customer account or specific invoice.
    """

    class Status(models.TextChoices):
        PROCESSED = "Processed", "Processed"
        FAILED = "Failed", "Failed"
        VOIDED = "Voided", "Voided"

    account = models.ForeignKey(
        CustomerAccount, on_delete=models.PROTECT, related_name="payments"
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, null=True, blank=True, related_name="payments"
    )
    zuora_payment_id = models.CharField(
        max_length=64, unique=True, null=True, blank=True, db_index=True
    )
    payment_number = models.CharField(max_length=64, unique=True, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=50, default="CreditCard")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PROCESSED
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["account", "status"]),
        ]

    def __str__(self):
        return f"{self.payment_number} - {self.amount}"


class Refund(TimeStampedModel):
    """
    Tracks full or partial refunds issued against a processed payment.
    """

    class Status(models.TextChoices):
        PROCESSED = "Processed", "Processed"
        FAILED = "Failed", "Failed"

    payment = models.ForeignKey(
        Payment, on_delete=models.PROTECT, related_name="refunds"
    )
    zuora_refund_id = models.CharField(
        max_length=64, unique=True, null=True, blank=True, db_index=True
    )
    refund_number = models.CharField(max_length=64, unique=True, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PROCESSED
    )

    def __str__(self):
        return f"{self.refund_number} - {self.amount}"


class FinancialTransaction(TimeStampedModel):
    """
    Immutable audit ledger recording every charge, payment, and refund event.
    """

    class TxType(models.TextChoices):
        CHARGE = "CHARGE", "Charge"
        PAYMENT = "PAYMENT", "Payment"
        REFUND = "REFUND", "Refund"

    account = models.ForeignKey(
        CustomerAccount, on_delete=models.PROTECT, related_name="transactions"
    )
    transaction_type = models.CharField(max_length=20, choices=TxType.choices, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference_id = models.CharField(max_length=64, db_index=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["account", "transaction_type", "created_at"]),
        ]

    def __str__(self):
        return f"{self.transaction_type} {self.amount} ({self.reference_id})"


class Attachment(TimeStampedModel):
    """
    Manages file attachments (e.g., contracts, tax exemptions, signed quotes)
    associated with a customer account or invoice.
    """

    account = models.ForeignKey(
        CustomerAccount, on_delete=models.CASCADE, related_name="attachments"
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="attachments"
    )
    file = models.FileField(upload_to="attachments/%Y/%m/")
    zuora_file_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    description = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Attachment for {self.account.account_number}"