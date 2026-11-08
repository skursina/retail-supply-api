from django.urls import path

from .views import (
    CartView, CartItemCreateView, CartItemDetailView,
    AddressListCreateView, AddressDetailView,
    OrderConfirmView, OrderListView, OrderDetailView, OrderStatusUpdateView,
)


urlpatterns = [
    path("cart/", CartView.as_view(), name="cart"),
    path("cart/items/", CartItemCreateView.as_view(), name="cart-item-create"),
    path("cart/items/<int:pk>/", CartItemDetailView.as_view(), name="cart-item-detail"),

    path("addresses/", AddressListCreateView.as_view(), name="address-list"),
    path("addresses/<int:pk>/", AddressDetailView.as_view(), name="address-detail"),

    path("orders/confirm/", OrderConfirmView.as_view(), name="order-confirm"),
    path("orders/", OrderListView.as_view(), name="order-list"),
    path("orders/<int:pk>/", OrderDetailView.as_view(), name="order-detail"),
    path("orders/<int:pk>/status/", OrderStatusUpdateView.as_view(), name="order-status"),
]