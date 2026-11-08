from django.urls import path

from .views import (
    CartView, CartItemView, CartItemDetailView,
    AddressListCreateView, AddressDetailView,
)


urlpatterns = [
    path("cart/", CartView.as_view(), name="cart"),
    path("cart/items/", CartItemView.as_view(), name="cart-item-create"),
    path("cart/items/<int:pk>/", CartItemDetailView.as_view(), name="cart-item-detail"),

    path("addresses/", AddressListCreateView.as_view(), name="address-list"),
    path("addresses/<int:pk>/", AddressDetailView.as_view(), name="address-detail"),
]