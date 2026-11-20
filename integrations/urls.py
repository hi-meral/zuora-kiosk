from django.urls import path
from .views import ZuoraWebhookView

urlpatterns = [
    path("webhooks/zuora/", ZuoraWebhookView.as_view(), name="zuora-webhook"),
]