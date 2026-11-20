import os
import structlog
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = structlog.get_logger(__name__)


class ZuoraWebhookView(APIView):
    """
    POST: Receives asynchronous webhook notifications from Zuora
    (e.g., InvoicePosted, PaymentProcessed, SubscriptionCanceled).
    """

    permission_classes = [AllowAny]

    def post(self, request):
        expected_secret = os.getenv("ZUORA_WEBHOOK_SECRET", "")
        received_secret = request.headers.get("X-Zuora-Webhook-Secret", "")

        if expected_secret and received_secret != expected_secret:
            logger.warning("zuora_webhook_unauthorized")
            return Response(
                {"error": {"code": "unauthorized", "message": "Invalid webhook secret."}},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        event_type = request.data.get("eventType", "unknown")
        logger.info("zuora_webhook_received", event_type=event_type, payload=request.data)

        return Response({"received": True, "event_type": event_type}, status=status.HTTP_200_OK)