from django.urls import path

from .views import (
    CategoryListView,
    ProductListView,
    ProductDetailView,
    SupplierOrderSettingsView,
)
from .management.commands.export_products import ExportProductsView


urlpatterns = [
    path("categories/", CategoryListView.as_view(), name="category-list"),
    path("products/", ProductListView.as_view(), name="product-list"),
    path("products/<int:pk>", ProductDetailView.as_view(), name="product-detail"),
    path("export/", ExportProductsView.as_view(), name="products-export"),
    path("supplier/settings/", SupplierOrderSettingsView.as_view(), name="supplier-order-settings"),
]