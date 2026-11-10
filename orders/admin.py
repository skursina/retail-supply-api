from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import Cart, CartItem, Order, OrderItem, Address
from .services import change_order_status, validate_order_status_transition


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


class OrderAdminForm(forms.ModelForm):
    """Форма редактирования заказа с проверкой статуса."""

    class Meta:
        model = Order
        fields = "__all__"

    def clean_status(self):
        new_status = self.cleaned_data["status"]

        # При редактировании проверяем переход
        # относительно текущего состояния в базе.
        if self.instance.pk:
            current_order = Order.objects.get(
                pk=self.instance.pk
            )

            try:
                validate_order_status_transition(
                    current_order,
                    new_status,
                )
            except ValidationError as exc:
                raise forms.ValidationError(
                    exc.messages
                ) from exc

        return new_status
    

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    form = OrderAdminForm
    
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

    def save_model(self, request, obj, form, change):
        """
        Изменение статуса через общий сервис заказов.

        Правила переходов, остатки и уведомления
        одинаковы для API и Django Admin.
        """
        if not change:
            super().save_model(request, obj, form, change)
            return

        old_order = Order.objects.get(pk=obj.pk)

        if old_order.status == obj.status:
            super().save_model(request, obj, form, change)
            return

        try:
            change_order_status(
                order_id=obj.pk,
                new_status=obj.status,
            )
        except ValidationError as exc:
            self.message_user(
                request,
                f"Не удалось изменить статус: {exc}",
                level=messages.ERROR,
            )
            # Не сохраняем недопустимое изменение.
            obj.status = old_order.status
            return

        self.message_user(
            request,
            "Статус заказа успешно изменён.",
            level=messages.SUCCESS,
        )


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("id", "buyer", "city", "street", "house", "is_default")
    list_filter = ("is_default", "city")
    search_fields = ("buyer__username", "city", "street")
    