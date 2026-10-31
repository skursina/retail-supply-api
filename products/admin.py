from django.contrib import admin

from .models import (
    Category,
    Product,
    ProductParameter,
    ProductParameterValue,
    SupplierProfile,
    SupplierProduct,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent")
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_active", "created_at")
    list_filter = ("category", "is_active")
    search_fields = ("name", "description")


@admin.register(ProductParameter)
class ProductParameterAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    filter_horizontal = ("categories",)


@admin.register(ProductParameterValue)
class ProductParameterValueAdmin(admin.ModelAdmin):
    list_display = ("product", "parameter", "value")
    list_filter = ("parameter",)
    search_fields = ("product__name", "parameter__name", "value")


@admin.register(SupplierProfile)
class SupplierProfileAdmin(admin.ModelAdmin):
    list_display = ("company_name", "user", "phone", "is_accepting_orders")
    list_filter = ("is_accepting_orders",)
    search_fields = ("company_name", "user__username")


@admin.register(SupplierProduct)
class SupplierProductAdmin(admin.ModelAdmin):
    list_display = ("product", "supplier", "price", "quantity", "is_available")
    list_filter = ("supplier", "is_available")
    search_fields = ("product__name", "supplier__company_name")
    