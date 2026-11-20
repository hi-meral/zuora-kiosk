from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import (
    CustomerAccountDetailView,
    CustomerAccountListCreateView,
    MeView,
    NotificationListView,
    RegisterView,
)

urlpatterns = [
    path("auth/register/", RegisterView.as_view(), name="auth-register"),
    path("auth/token/", TokenObtainPairView.as_view(), name="token-obtain-pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/me/", MeView.as_view(), name="auth-me"),
    path("accounts/", CustomerAccountListCreateView.as_view(), name="account-list-create"),
    path("accounts/<uuid:account_id>/", CustomerAccountDetailView.as_view(), name="account-detail"),
    path("notifications/", NotificationListView.as_view(), name="notification-list"),
]