import structlog
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from accounts.models import Notification
from .models import Refund

logger = structlog.get_logger(__name__)


@receiver(post_save, sender=Refund)
def create_refund_notification(sender, instance, created, **kwargs):
    """
    Automatically creates a customer Notification whenever a new Refund
    record is saved for the first time (created=True).
    Keeps notification side effects decoupled from RefundCreateView.
    """
    if not created:
        # Skip updates to existing refunds so we don't send duplicate alerts
        return

    account = instance.payment.account
    Notification.objects.create(
        account=account,
        channel=Notification.Channel.EMAIL,
        subject=f"Refund {instance.refund_number} Processed",
        message=(
            f"A refund of {instance.amount} {account.currency} has been issued "
            f"for payment {instance.payment.payment_number}. Reason: {instance.reason}"
        ),
        status=Notification.DeliveryStatus.SENT,
        sent_at=timezone.now(),
    )
    logger.info(
        "refund_notification_created_via_signal",
        refund_id=str(instance.id),
        account_id=str(account.id),
    )