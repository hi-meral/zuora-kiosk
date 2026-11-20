import structlog
from marshmallow import ValidationError as MarshmallowValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = structlog.get_logger(__name__)


class ZuoraIntegrationError(Exception):
    """Raised when an external Zuora API call fails after retries."""

    def __init__(self, message="External Zuora service error.", details=None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class BusinessRuleError(Exception):
    """Raised when a domain rule is violated (e.g., refund exceeds payment)."""

    def __init__(self, message="Business rule violation.", details=None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


def custom_exception_handler(exc, context):
    """
    Global DRF exception handler that normalizes all error responses into:
    {
        "error": {
            "code": "<error_code>",
            "message": "<human_readable_summary>",
            "details": {...}
        }
    }
    """
    # 1. Handle Marshmallow schema validation errors
    if isinstance(exc, MarshmallowValidationError):
        logger.warning("validation_failed", errors=exc.messages)
        return Response(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Invalid request payload.",
                    "details": exc.messages,
                }
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 2. Handle domain business rule violations
    if isinstance(exc, BusinessRuleError):
        logger.warning("business_rule_error", message=exc.message, details=exc.details)
        return Response(
            {
                "error": {
                    "code": "business_rule_error",
                    "message": exc.message,
                    "details": exc.details,
                }
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # 3. Handle external Zuora integration failures
    if isinstance(exc, ZuoraIntegrationError):
        logger.error("zuora_integration_error", message=exc.message, details=exc.details)
        return Response(
            {
                "error": {
                    "code": "zuora_integration_error",
                    "message": exc.message,
                    "details": exc.details,
                }
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # 4. Delegate standard DRF exceptions (401, 403, 404, 405, etc.)
    response = drf_exception_handler(exc, context)
    if response is not None:
        return Response(
            {
                "error": {
                    "code": "api_error",
                    "message": str(exc),
                    "details": response.data,
                }
            },
            status=response.status_code,
        )

    # 5. Catch-all for unhandled 500 errors (log details, hide internals from client)
    logger.exception("unhandled_server_error", error=str(exc))
    return Response(
        {
            "error": {
                "code": "internal_server_error",
                "message": "An unexpected error occurred. Please try again later.",
                "details": {},
            }
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )