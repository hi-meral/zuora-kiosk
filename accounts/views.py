import structlog
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.schemas import RegisterSchema, CustomerAccountCreateSchema
from core.mixins import MarshmallowValidationMixin
from django.db import transaction
from django.shortcuts import get_object_or_404
from integrations.idempotency import IdempotencyMixin
from integrations.zuora_client import ZuoraClient
from .models import CustomerAccount, Notification

User = get_user_model()
logger = structlog.get_logger(__name__)


class RegisterView(MarshmallowValidationMixin, APIView):
    """
    Registers a new API user with Marshmallow payload validation.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        # Raises marshmallow.ValidationError -> formatted by custom_exception_handler
        data = self.validate_payload(RegisterSchema)

        try:
            user = User.objects.create_user(
                username=data["username"],
                email=data["email"],
                password=data["password"],
            )
        except IntegrityError:
            return Response(
                {
                    "error": {
                        "code": "conflict",
                        "message": "A user with that username already exists.",
                        "details": {},
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )

        logger.info("user_registered", user_id=user.id, username=user.username)
        return Response(
            {"id": user.id, "username": user.username, "email": user.email},
            status=status.HTTP_201_CREATED,
        )


class MeView(APIView):
    """Returns the currently authenticated user's identity."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response(
            {"id": user.id, "username": user.username, "email": user.email},
            status=status.HTTP_200_OK,
        )
        
class CustomerAccountListCreateView(IdempotencyMixin, MarshmallowValidationMixin, APIView):
    """
    GET:  List all customer accounts owned by the authenticated user.
    POST: Create a new customer account locally and in Zuora (idempotent).
    """
    print("AAAAAA")
    def get(self, request):
        accounts = CustomerAccount.objects.filter(owner=request.user).only(
            "id", "account_number", "zuora_account_id", "name", "email", "currency", "balance", "status", "created_at"
        )
        data = [
            {
                "id": str(acc.id),
                "account_number": acc.account_number,
                "zuora_account_id": acc.zuora_account_id,
                "name": acc.name,
                "email": acc.email,
                "currency": acc.currency,
                "balance": str(acc.balance),
                "status": acc.status,
                "created_at": acc.created_at.isoformat(),
            }
            for acc in accounts
        ]
        return Response({"results": data}, status=status.HTTP_200_OK)

    def post(self, request):
        # 1. Check idempotency cache first
        cached_response, idempotency_key = self.check_idempotency(request)
        if cached_response:
            return cached_response

        # 2. Validate payload with Marshmallow
        data = self.validate_payload(CustomerAccountCreateSchema)

        # 3. Call Zuora & persist atomically
        zuora = ZuoraClient()
        with transaction.atomic():
            z_res = zuora.create_account(data, idempotency_key=idempotency_key)
            account = CustomerAccount.objects.create(
                owner=request.user,
                zuora_account_id=z_res["accountId"],
                account_number=z_res["accountNumber"],
                name=data["name"],
                email=data["email"],
                currency=data["currency"],
            )
            response_body = {
                "id": str(account.id),
                "account_number": account.account_number,
                "zuora_account_id": account.zuora_account_id,
                "name": account.name,
                "email": account.email,
                "currency": account.currency,
                "status": account.status,
            }
            self.save_idempotency(
                request, idempotency_key, status.HTTP_201_CREATED, response_body
            )

        logger.info("customer_account_created", account_id=str(account.id))
        return Response(response_body, status=status.HTTP_201_CREATED)


class CustomerAccountDetailView(APIView):
    """
    GET: Retrieve a single customer account owned by the authenticated user.
    """

    def get(self, request, account_id):
        account = get_object_or_404(CustomerAccount, id=account_id, owner=request.user)
        return Response(
            {
                "id": str(account.id),
                "account_number": account.account_number,
                "zuora_account_id": account.zuora_account_id,
                "name": account.name,
                "email": account.email,
                "currency": account.currency,
                "balance": str(account.balance),
                "status": account.status,
            },
            status=status.HTTP_200_OK,
        )


class NotificationListView(APIView):
    """
    GET: List notifications across the authenticated user's customer accounts.
    """

    def get(self, request):
        notifications = (
            Notification.objects.filter(account__owner=request.user)
            .select_related("account")
            .order_by("-created_at")[:50]
        )
        results = [
            {
                "id": str(n.id),
                "account_number": n.account.account_number,
                "channel": n.channel,
                "subject": n.subject,
                "status": n.status,
                "created_at": n.created_at.isoformat(),
            }
            for n in notifications
        ]
        return Response({"results": results}, status=status.HTTP_200_OK)