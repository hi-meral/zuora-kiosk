import uuid
import requests
import structlog
from django.conf import settings
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from core.exceptions import ZuoraIntegrationError

logger = structlog.get_logger(__name__)


class ZuoraClient:
    """
    Unified client for Zuora REST APIs.
    Supports 'dummy' mode for local development/testing and 'sandbox' mode
    for live Zuora Sandbox calls with OAuth2 and automatic retries.
    """

    def __init__(self):
        self.mode = settings.ZUORA_MODE
        self.base_url = settings.ZUORA_BASE_URL.rstrip("/")
        self.client_id = settings.ZUORA_CLIENT_ID
        self.client_secret = settings.ZUORA_CLIENT_SECRET
        self.session = requests.Session()
        self._access_token = None

    def _get_headers(self):
        if not self._access_token:
            self._authenticate()
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def _authenticate(self):
        """Fetches an OAuth2 Bearer token from Zuora Sandbox."""
        url = f"{self.base_url}/oauth/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }
        response = self.session.post(url, data=payload, timeout=10)
        response.raise_for_status()
        self._access_token = response.json()["access_token"]

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    def _request_with_retry(self, method, path, json_payload=None, idempotency_key=None):
        """
        Executes an HTTP request against Zuora Sandbox with automatic
        exponential-backoff retries on transient network or 5xx errors.
        """
        url = f"{self.base_url}{path}"
        headers = self._get_headers()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        logger.info("zuora_api_request", method=method, path=path, mode=self.mode)
        response = self.session.request(
            method=method, url=url, json=json_payload, headers=headers, timeout=15
        )
        # Trigger retry on 5xx server errors
        if response.status_code >= 500:
            response.raise_for_status()

        data = response.json()
        if not response.ok or data.get("success") is False:
            raise ZuoraIntegrationError(
                message="Zuora rejected the request.",
                details={"status_code": response.status_code, "zuora_response": data},
            )
        return data

    def _execute(self, method, path, dummy_response, json_payload=None, idempotency_key=None):
        """Routes to dummy mock data or live Zuora Sandbox based on ZUORA_MODE."""
        if self.mode == "dummy":
            logger.info(
                "zuora_dummy_call",
                method=method,
                path=path,
                idempotency_key=idempotency_key,
            )
            return dummy_response

        try:
            return self._request_with_retry(
                method, path, json_payload=json_payload, idempotency_key=idempotency_key
            )
        except requests.RequestException as exc:
            logger.error("zuora_request_failed_after_retries", path=path, error=str(exc))
            raise ZuoraIntegrationError(
                message="Failed to communicate with Zuora after retries.",
                details={"error": str(exc)},
            ) from exc

    # --- Domain Operations ---

    def create_account(self, payload, idempotency_key=None):
        dummy = {
            "success": True,
            "accountId": f"z-acc-{uuid.uuid4().hex[:12]}",
            "accountNumber": f"A-{uuid.uuid4().hex[:8].upper()}",
        }
        return self._execute("POST", "/v1/accounts", dummy, payload, idempotency_key)

    def create_subscription(self, payload, idempotency_key=None):
        dummy = {
            "success": True,
            "subscriptionId": f"z-sub-{uuid.uuid4().hex[:12]}",
            "subscriptionNumber": f"S-{uuid.uuid4().hex[:8].upper()}",
        }
        return self._execute("POST", "/v1/subscriptions", dummy, payload, idempotency_key)

    def amend_subscription(self, subscription_key, payload, idempotency_key=None):
        dummy = {
            "success": True,
            "amendmentId": f"z-amd-{uuid.uuid4().hex[:12]}",
        }
        return self._execute(
            "PUT", f"/v1/subscriptions/{subscription_key}", dummy, payload, idempotency_key
        )

    def create_payment(self, payload, idempotency_key=None):
        dummy = {
            "success": True,
            "id": f"z-pay-{uuid.uuid4().hex[:12]}",
            "number": f"P-{uuid.uuid4().hex[:8].upper()}",
            "status": "Processed",
        }
        return self._execute("POST", "/v1/payments", dummy, payload, idempotency_key)

    def create_refund(self, payment_id, payload, idempotency_key=None):
        dummy = {
            "success": True,
            "id": f"z-ref-{uuid.uuid4().hex[:12]}",
            "number": f"R-{uuid.uuid4().hex[:8].upper()}",
            "status": "Processed",
        }
        return self._execute(
            "POST", f"/v1/payments/{payment_id}/refunds", dummy, payload, idempotency_key
        )