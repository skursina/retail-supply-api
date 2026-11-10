from django.db import transaction
from django.core.exceptions import ValidationError

from .models import Order, OrderItem
from .serializers import OrderStatusSerializer
from .emails import send_order_status_email
from products.models import SupplierProduct


def validate_order_status_transition(order, new_status):
    """
    Проверяет, можно ли перевести заказ
    из текущего статуса в новый.

    Использует существующие правила переходов.
    """
    serializer = OrderStatusSerializer(
        instance=order,
        data={"status": new_status},
        partial=True,
    )

    if not serializer.is_valid():
        raise ValidationError(serializer.errors)

    return serializer.validated_data.get("status", order.status)


@transaction.atomic
def change_order_status(order_id, new_status):
    """
    Изменяет статус заказа.

    Проверяет допустимость перехода,
    возвращает остатки при отмене
    и отправляет уведомление после commit.
    """

    # Блокируем заказ от параллельных изменений.
    order = Order.objects.select_for_update().get(pk=order_id)

    old_status = order.status

    # Используем общую проверку переходов.
    new_status = validate_order_status_transition(
        order, new_status
    )

    if old_status == new_status:
        return order

    # При отмене или отклонении возвращаем товары.
    if new_status in (
        Order.Status.CANCELLED,
        Order.Status.REJECTED,
    ):
        items = list(
            OrderItem.objects.filter(order=order)
        )

        offer_ids = sorted({
            item.supplier_product_id for item in items
        })

        offers = {
            offer.pk: offer
            for offer in SupplierProduct.objects
            .select_for_update()
            .filter(pk__in=offer_ids)
            .order_by("pk")
        }

        for item in items:
            offer = offers[item.supplier_product_id]

            offer.quantity += item.quantity
            offer.is_available = True

            offer.save(
                update_fields=["quantity", "is_available"]
            )

    # Сохраняем новый статус.
    order.status = new_status
    order.save(update_fields=["status", "updated_at"])

    # Отправляем уведомление после commit.
    transaction.on_commit(
        lambda order_id=order.pk: send_order_status_email(order_id)
    )

    return order
