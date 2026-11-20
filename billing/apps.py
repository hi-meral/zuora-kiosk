from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "billing"

    def ready(self):
        # Import signal receivers when the app registry is fully populated
        import billing.signals  # noqa: F401