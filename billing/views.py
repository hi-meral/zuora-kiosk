import uuid
from datetime import timedelta
import structlog
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import CustomerAccount, Notification
from core.exceptions import BusinessRuleError
from core.mixins import MarshmallowValidationMixin
from integrations.idempotency import IdempotencyMixin
from integrations.zuora_client import ZuoraClient
from decimal import Decimal
from django.db.models import Sum
from rest_framework.parsers import MultiPartParser, FormParser
from .models import (
    Attachment,
    FinancialTransaction,
    Invoice,
    Payment,
    Product,
    ProductRatePlan,
    Refund,
    Subscription,
    SubscriptionAmendment,
)
from .schemas import (
    PaymentCreateSchema,
    RefundCreateSchema,
    SubscriptionAmendmentSchema,
    SubscriptionCreateSchema,
)

logger = structlog.get_logger(__name__)


class ProductCatalogListView(APIView):
    """
    GET: Returns active products and their rate plans using prefetch_related
    to prevent N+1 database queries.
    """

    def get(self, request):
        products = Product.objects.filter(is_active=True).prefetch_related("rate_plans")
        catalog = [
            {
                "id": str(p.id),
                "sku": p.sku,
                "name": p.name,
                "description": p.description,
                "rate_plans": [
                    {
                        "id": str(rp.id),
                        "name": rp.name,
                        "price": str(rp.price),
                        "currency": rp.currency,
                        "billing_period": rp.billing_period,
                    }
                    for rp in p.rate_plans.all()
                    if rp.is_active
                ],
            }
            for p in products
        ]
        return Response({"results": catalog}, status=status.HTTP_200_OK)


class SubscriptionListCreateView(IdempotencyMixin, MarshmallowValidationMixin, APIView):
    """
    GET:  List subscriptions for the authenticated user's accounts.
    POST: Create a subscription, generate an initial invoice, and record a charge
          in the financial ledger inside an atomic transaction.
    """

    def get(self, request):
        subs = (
            Subscription.objects.filter(account__owner=request.user)
            .select_related("account", "rate_plan", "rate_plan__product")
            .order_by("-created_at")
        )
        results = [
            {
                "id": str(s.id),
                "subscription_number": s.subscription_number,
                "account_number": s.account.account_number,
                "product": s.rate_plan.product.name,
                "rate_plan": s.rate_plan.name,
                "status": s.status,
                "term_start_date": s.term_start_date.isoformat(),
                "term_end_date": s.term_end_date.isoformat(),
            }
            for s in subs
        ]
        return Response({"results": results}, status=status.HTTP_200_OK)

    def post(self, request):
        cached_response, idempotency_key = self.check_idempotency(request)
        if cached_response:
            return cached_response

        data = self.validate_payload(SubscriptionCreateSchema)
        if data["term_end_date"] <= data["term_start_date"]:
            raise BusinessRuleError("term_end_date must be after term_start_date.")

        account = get_object_or_404(
            CustomerAccount, id=data["account_id"], owner=request.user
        )
        rate_plan = get_object_or_404(
            ProductRatePlan, id=data["rate_plan_id"], is_active=True
        )

        zuora = ZuoraClient()
        with transaction.atomic():
            z_res = zuora.create_subscription(
                {
                    "accountKey": account.zuora_account_id,
                    "ratePlanId": str(rate_plan.id),
                    "termStartDate": data["term_start_date"].isoformat(),
                },
                idempotency_key=idempotency_key,
            )

            sub = Subscription.objects.create(
                account=account,
                rate_plan=rate_plan,
                zuora_subscription_id=z_res["subscriptionId"],
                subscription_number=z_res["subscriptionNumber"],
                status=Subscription.Status.ACTIVE,
                term_start_date=data["term_start_date"],
                term_end_date=data["term_end_date"],
                auto_renew=data["auto_renew"],
            )

            # Generate initial invoice and ledger charge
            invoice = Invoice.objects.create(
                account=account,
                subscription=sub,
                invoice_number=f"INV-{uuid.uuid4().hex[:8].upper()}",
                amount=rate_plan.price,
                balance=rate_plan.price,
                due_date=data["term_start_date"] + timedelta(days=15),
                status=Invoice.Status.POSTED,
            )
            account.balance += rate_plan.price
            account.save(update_fields=["balance", "updated_at"])

            FinancialTransaction.objects.create(
                account=account,
                transaction_type=FinancialTransaction.TxType.CHARGE,
                amount=rate_plan.price,
                reference_id=invoice.invoice_number,
                description=f"Initial charge for {sub.subscription_number}",
            )
            Notification.objects.create(
                account=account,
                subject=f"Subscription {sub.subscription_number} Activated",
                message=f"Invoice {invoice.invoice_number} for {rate_plan.price} {account.currency} is ready.",
                status=Notification.DeliveryStatus.SENT,
            )

            response_body = {
                "id": str(sub.id),
                "subscription_number": sub.subscription_number,
                "status": sub.status,
                "invoice_number": invoice.invoice_number,
                "invoice_amount": str(invoice.amount),
            }
            self.save_idempotency(
                request, idempotency_key, status.HTTP_201_CREATED, response_body
            )

        logger.info("subscription_created", subscription_id=str(sub.id))
        return Response(response_body, status=status.HTTP_201_CREATED)


class SubscriptionAmendView(MarshmallowValidationMixin, APIView):
    """
    POST: Amend an existing subscription (UpdateProduct, Renewal, or Cancellation).
    """

    def post(self, request, subscription_id):
        data = self.validate_payload(SubscriptionAmendmentSchema)
        sub = get_object_or_404(
            Subscription, id=subscription_id, account__owner=request.user
        )

        new_plan = None
        if data["amendment_type"] == "UpdateProduct":
            if not data["new_rate_plan_id"]:
                raise BusinessRuleError(
                    "new_rate_plan_id is required for UpdateProduct amendments."
                )
            new_plan = get_object_or_404(
                ProductRatePlan, id=data["new_rate_plan_id"], is_active=True
            )

        zuora = ZuoraClient()
        with transaction.atomic():
            z_res = zuora.amend_subscription(
                sub.zuora_subscription_id,
                {"type": data["amendment_type"], "effectiveDate": data["effective_date"].isoformat()},
            )
            amendment = SubscriptionAmendment.objects.create(
                subscription=sub,
                zuora_amendment_id=z_res["amendmentId"],
                amendment_type=data["amendment_type"],
                effective_date=data["effective_date"],
                new_rate_plan=new_plan,
                notes=data["notes"],
            )

            if data["amendment_type"] == "Cancellation":
                sub.status = Subscription.Status.CANCELED
                sub.save(update_fields=["status", "updated_at"])
            elif new_plan:
                sub.rate_plan = new_plan
                sub.save(update_fields=["rate_plan", "updated_at"])

        logger.info("subscription_amended", subscription_id=str(sub.id), type=data["amendment_type"])
        return Response(
            {
                "amendment_id": str(amendment.id),
                "subscription_number": sub.subscription_number,
                "amendment_type": amendment.amendment_type,
                "subscription_status": sub.status,
            },
            status=status.HTTP_200_OK,
        )
        
class InvoiceListView(APIView):
    """
    GET: List invoices for the authenticated user's accounts (supports ?status=Posted).
    """

    def get(self, request):
        qs = Invoice.objects.filter(account__owner=request.user).select_related(
            "account", "subscription"
        )
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        results = [
            {
                "id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "account_number": inv.account.account_number,
                "amount": str(inv.amount),
                "balance": str(inv.balance),
                "due_date": inv.due_date.isoformat(),
                "status": inv.status,
            }
            for inv in qs
        ]
        return Response({"results": results}, status=status.HTTP_200_OK)


class PaymentCreateView(IdempotencyMixin, MarshmallowValidationMixin, APIView):
    """
    POST: Process a payment against an invoice atomically with row-level locking
          and idempotency protection.
    """

    def post(self, request):
        cached_response, idempotency_key = self.check_idempotency(request)
        if cached_response:
            return cached_response

        data = self.validate_payload(PaymentCreateSchema)
        amount = Decimal(str(data["amount"]))

        zuora = ZuoraClient()
        with transaction.atomic():
            # Lock the invoice row to prevent concurrent overpayments
            invoice = get_object_or_404(
                Invoice.objects.select_for_update().select_related("account"),
                id=data["invoice_id"],
                account__owner=request.user,
            )

            if invoice.status == Invoice.Status.PAID or invoice.balance <= Decimal("0.00"):
                raise BusinessRuleError("This invoice is already paid in full.")
            if amount > invoice.balance:
                raise BusinessRuleError(
                    f"Payment amount ({amount}) exceeds remaining invoice balance ({invoice.balance})."
                )

            z_res = zuora.create_payment(
                {
                    "accountId": invoice.account.zuora_account_id,
                    "invoiceId": invoice.zuora_invoice_id,
                    "amount": str(amount),
                    "paymentMethod": data["payment_method"],
                },
                idempotency_key=idempotency_key,
            )

            payment = Payment.objects.create(
                account=invoice.account,
                invoice=invoice,
                zuora_payment_id=z_res["id"],
                payment_number=z_res["number"],
                amount=amount,
                payment_method=data["payment_method"],
                status=Payment.Status.PROCESSED,
            )

            # Update invoice & account balances
            invoice.balance -= amount
            if invoice.balance == Decimal("0.00"):
                invoice.status = Invoice.Status.PAID
            invoice.save(update_fields=["balance", "status", "updated_at"])

            invoice.account.balance -= amount
            invoice.account.save(update_fields=["balance", "updated_at"])

            FinancialTransaction.objects.create(
                account=invoice.account,
                transaction_type=FinancialTransaction.TxType.PAYMENT,
                amount=amount,
                reference_id=payment.payment_number,
                description=f"Payment toward {invoice.invoice_number}",
            )
            Notification.objects.create(
                account=invoice.account,
                subject=f"Payment {payment.payment_number} Received",
                message=f"Processed {amount} {invoice.account.currency} for {invoice.invoice_number}.",
                status=Notification.DeliveryStatus.SENT,
            )

            response_body = {
                "id": str(payment.id),
                "payment_number": payment.payment_number,
                "amount": str(payment.amount),
                "invoice_status": invoice.status,
                "remaining_invoice_balance": str(invoice.balance),
            }
            self.save_idempotency(
                request, idempotency_key, status.HTTP_201_CREATED, response_body
            )

        logger.info("payment_processed", payment_id=str(payment.id), amount=str(amount))
        return Response(response_body, status=status.HTTP_201_CREATED)


class RefundCreateView(IdempotencyMixin, MarshmallowValidationMixin, APIView):
    """
    POST: Issue a full or partial refund against a processed payment.
    """

    def post(self, request):
        cached_response, idempotency_key = self.check_idempotency(request)
        if cached_response:
            return cached_response

        data = self.validate_payload(RefundCreateSchema)
        refund_amount = Decimal(str(data["amount"]))

        zuora = ZuoraClient()
        with transaction.atomic():
            payment = get_object_or_404(
                Payment.objects.select_for_update().select_related("account"),
                id=data["payment_id"],
                account__owner=request.user,
            )

            already_refunded = (
                payment.refunds.filter(status=Refund.Status.PROCESSED).aggregate(
                    total=Sum("amount")
                )["total"]
                or Decimal("0.00")
            )
            refundable = payment.amount - already_refunded

            if refund_amount > refundable:
                raise BusinessRuleError(
                    f"Refund amount ({refund_amount}) exceeds refundable balance ({refundable})."
                )

            z_res = zuora.create_refund(
                payment.zuora_payment_id,
                {"amount": str(refund_amount), "reason": data["reason"]},
                idempotency_key=idempotency_key,
            )

            refund = Refund.objects.create(
                payment=payment,
                zuora_refund_id=z_res["id"],
                refund_number=z_res["number"],
                amount=refund_amount,
                reason=data["reason"],
                status=Refund.Status.PROCESSED,
            )

            FinancialTransaction.objects.create(
                account=payment.account,
                transaction_type=FinancialTransaction.TxType.REFUND,
                amount=refund_amount,
                reference_id=refund.refund_number,
                description=f"Refund for {payment.payment_number}: {data['reason']}",
            )

            response_body = {
                "id": str(refund.id),
                "refund_number": refund.refund_number,
                "amount": str(refund.amount),
                "status": refund.status,
            }
            self.save_idempotency(
                request, idempotency_key, status.HTTP_201_CREATED, response_body
            )

        logger.info("refund_processed", refund_id=str(refund.id), amount=str(refund_amount))
        return Response(response_body, status=status.HTTP_201_CREATED)


class AttachmentListCreateView(APIView):
    """
    GET:  List file attachments for the authenticated user's accounts.
    POST: Upload a file attachment (multipart/form-data) linked to an account.
    """

    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        attachments = Attachment.objects.filter(
            account__owner=request.user
        ).select_related("account")
        results = [
            {
                "id": str(att.id),
                "account_number": att.account.account_number,
                "file_name": att.file.name,
                "description": att.description,
                "created_at": att.created_at.isoformat(),
            }
            for att in attachments
        ]
        return Response({"results": results}, status=status.HTTP_200_OK)

    def post(self, request):
        account_id = request.data.get("account_id")
        uploaded_file = request.FILES.get("file")
        if not account_id or not uploaded_file:
            raise BusinessRuleError("Both 'account_id' and 'file' are required.")

        account = get_object_or_404(CustomerAccount, id=account_id, owner=request.user)
        attachment = Attachment.objects.create(
            account=account,
            file=uploaded_file,
            zuora_file_id=f"z-file-{uuid.uuid4().hex[:10]}",
            description=request.data.get("description", ""),
        )
        logger.info("attachment_uploaded", attachment_id=str(attachment.id))
        return Response(
            {
                "id": str(attachment.id),
                "zuora_file_id": attachment.zuora_file_id,
                "file_name": attachment.file.name,
            },
            status=status.HTTP_201_CREATED,
        )


class FinancialTransactionListView(APIView):
    """
    GET: List the immutable financial transaction ledger for the user's accounts.
    """

    def get(self, request):
        txs = FinancialTransaction.objects.filter(
            account__owner=request.user
        ).select_related("account")[:100]
        results = [
            {
                "id": str(tx.id),
                "account_number": tx.account.account_number,
                "type": tx.transaction_type,
                "amount": str(tx.amount),
                "reference_id": tx.reference_id,
                "description": tx.description,
                "created_at": tx.created_at.isoformat(),
            }
            for tx in txs
        ]
        return Response({"results": results}, status=status.HTTP_200_OK)