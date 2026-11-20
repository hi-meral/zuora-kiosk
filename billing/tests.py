from datetime import date, timedelta
from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from billing.models import Invoice, Product, ProductRatePlan
from accounts.models import Notification

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_client(db, api_client):
    """Returns an APIClient authenticated with a JWT Bearer token."""
    user = User.objects.create_user(
        username="testuser", email="test@zuorakiosk.com", password="Password123!"
    )
    res = api_client.post(
        "/api/v1/auth/token/",
        {"username": "testuser", "password": "Password123!"},
        format="json",
    )
    token = res.data["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client, user


@pytest.fixture
def sample_rate_plan(db):
    product = Product.objects.create(sku="PRO-001", name="ZuoraKiosk Pro")
    return ProductRatePlan.objects.create(
        product=product, name="Monthly Pro", price=Decimal("100.00"), currency="USD"
    )


@pytest.mark.django_db
def test_unauthenticated_access_blocked(api_client):
    """Protected endpoints must reject requests without a JWT token."""
    res = api_client.get("/api/v1/accounts/")
    assert res.status_code == 401


@pytest.mark.django_db
def test_idempotent_account_creation(auth_client):
    """Repeating a POST with the same Idempotency-Key returns the cached response."""
    client, _ = auth_client
    payload = {"name": "Acme Corp", "email": "billing@acme.com", "currency": "USD"}

    first = client.post(
        "/api/v1/accounts/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="key-acc-1",
    )
    second = client.post(
        "/api/v1/accounts/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="key-acc-1",
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.data["id"] == second.data["id"]

    # Reusing the same key with a different payload must return 409 Conflict
    conflict = client.post(
        "/api/v1/accounts/",
        {"name": "Different Corp", "email": "other@acme.com", "currency": "USD"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="key-acc-1",
    )
    assert conflict.status_code == 409


@pytest.mark.django_db
def test_subscription_payment_and_refund_lifecycle(auth_client, sample_rate_plan):
    """Tests full lifecycle: Account -> Subscription -> Invoice -> Payment -> Refund."""
    client, _ = auth_client

    # 1. Create Customer Account
    acc_res = client.post(
        "/api/v1/accounts/",
        {"name": "Beta LLC", "email": "ap@beta.io", "currency": "USD"},
        format="json",
    )
    assert acc_res.status_code == 201
    account_id = acc_res.data["id"]

    # 2. Create Subscription (automatically generates a $100.00 invoice)
    today = date.today()
    sub_res = client.post(
        "/api/v1/subscriptions/",
        {
            "account_id": account_id,
            "rate_plan_id": str(sample_rate_plan.id),
            "term_start_date": today.isoformat(),
            "term_end_date": (today + timedelta(days=30)).isoformat(),
        },
        format="json",
    )
    assert sub_res.status_code == 201
    invoice = Invoice.objects.get(invoice_number=sub_res.data["invoice_number"])

    # 3. Overpayment must be rejected with 422 BusinessRuleError
    overpay = client.post(
        "/api/v1/payments/",
        {"invoice_id": str(invoice.id), "amount": "150.00"},
        format="json",
    )
    assert overpay.status_code == 422

    # 4. Pay exact invoice amount ($100.00)
    pay_res = client.post(
        "/api/v1/payments/",
        {"invoice_id": str(invoice.id), "amount": "100.00"},
        format="json",
    )
    assert pay_res.status_code == 201
    assert pay_res.data["invoice_status"] == "Paid"

    # 5. Issue partial refund ($40.00)
    ref_res = client.post(
        "/api/v1/refunds/",
        {"payment_id": pay_res.data["id"], "amount": "40.00", "reason": "Prorated credit"},
        format="json",
    )
    assert ref_res.status_code == 201

    # 6. Refunding more than remaining $60.00 must fail with 422
    over_refund = client.post(
        "/api/v1/refunds/",
        {"payment_id": pay_res.data["id"], "amount": "70.00", "reason": "Duplicate"},
        format="json",
    )
    assert over_refund.status_code == 422
    
    # 7. Verify the post_save signal automatically created a Refund notification
    assert Notification.objects.filter(
        subject__startswith="Refund",
        account_id=account_id,
    ).exists()