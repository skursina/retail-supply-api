from django.contrib import admin

from .models import Cart, CartItem, Order, OrderItem, Address


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    fields = ("supplier_product", "quantity")


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "buyer",
        "is_active",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_active", "created_at")
    search_fields = (
        "buyer__username",
        "buyer__email",
    )
    readonly_fields = ("created_at", "updated_at")
    inlines = (CartItemInline,)
    list_select_related = ("buyer",)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    fields = (
        "product_name",
        "unit",
        "quantity",
        "price",
        "line_total",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "buyer",
        "supplier",
        "status",
        "total_amount",
        "created_at",
    )
    list_filter = (
        "status",
        "created_at",
        "supplier",
    )
    search_fields = (
        "number",
        "buyer__username",
        "buyer__email",
        "supplier__company_name",
    )
    readonly_fields = (
        "number",
        "buyer",
        "supplier",
        "total_amount",
        "created_at",
        "updated_at",
    )
    inlines = (OrderItemInline,)
    list_select_related = ("buyer", "supplier")

    def has_delete_permission(self, request, obj=None):
        # Заказы являются историей покупок.
        return False


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("id", "buyer", "city", "street", "house", "is_default")
    list_filter = ("is_default", "city")
    search_fields = ("buyer__username", "city", "street")
    