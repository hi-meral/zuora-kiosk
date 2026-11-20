from django.urls import path
from .views import (
    AttachmentListCreateView,
    FinancialTransactionListView,
    InvoiceListView,
    PaymentCreateView,
    ProductCatalogListView,
    RefundCreateView,
    SubscriptionAmendView,
    SubscriptionListCreateView,
)

urlpatterns = [
    path("catalog/products/", ProductCatalogListView.as_view(), name="product-catalog"),
    path("subscriptions/", SubscriptionListCreateView.as_view(), name="subscription-list-create"),
    path(
        "subscriptions/<uuid:subscription_id>/amend/",
        SubscriptionAmendView.as_view(),
        name="subscription-amend",
    ),
    path("invoices/", InvoiceListView.as_view(), name="invoice-list"),
    path("payments/", PaymentCreateView.as_view(), name="payment-create"),
    path("refunds/", RefundCreateView.as_view(), name="refund-create"),
    path("attachments/", AttachmentListCreateView.as_view(), name="attachment-list-create"),
    path("transactions/", FinancialTransactionListView.as_view(), name="transaction-list"),
]