import structlog
from django.db import connection
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = structlog.get_logger(__name__)


class HealthCheckView(APIView):
    """
    Public health check endpoint for load balancers and uptime monitors.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            db_status = "ok"
        except Exception as exc:
            logger.error("health_check_db_failed", error=str(exc))
            return Response(
                {"status": "unhealthy", "database": "error"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        logger.info("health_check_passed", database=db_status)
        return Response(
            {"status": "healthy", "service": "ZuoraKiosk", "database": db_status},
            status=status.HTTP_200_OK,
        )