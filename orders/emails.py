from django.conf import settings
from django.core.mail import send_mail

from .models import Order


def _order_lines_text(order: Order) -> str:
    lines = []
    for item in order.items.all():
        lines.append(
            f"  - {item.product_name} — {item.quantity} {item.unit} "
            f"× {item.price} ₽ = {item.price * item.quantity} ₽"
        )
    return "\n".join(lines)


def send_order_confirmation_to_buyer(order: Order) -> None:
    """Письмо покупателю: заказ принят."""
    address = order.delivery_address
    address_text = str(address) if address else "—"
    body = (
        f"Здравствуйте!\n\n"
        f"Ваш заказ {order.number} принят.\n"
        f"Поставщик: {order.supplier.company_name}\n"
        f"Сумма: {order.total_amount} ₽\n"
        f"Адрес доставки: {address_text}\n\n"
        f"Состав заказа:\n{_order_lines_text(order)}\n\n"
        f"Спасибо за покупку!"
    )
    send_mail(
        subject=f"Заказ {order.number} принят",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[order.buyer.email],
        fail_silently=False,
    )


def send_order_invoice_to_supplier(order: Order) -> None:
    """Накладная поставщику (или админу, если у поставщика нет email)."""
    recipient = order.supplier.user.email or settings.DEFAULT_FROM_EMAIL
    body = (
        f"Поступил новый заказ {order.number}.\n"
        f"Покупатель: {order.buyer.username} ({order.buyer.email})\n"
        f"Сумма: {order.total_amount} ₽\n"
        f"Адрес доставки: {order.delivery_address or '—'}\n\n"
        f"Состав заказа:\n{_order_lines_text(order)}\n"
    )
    send_mail(
        subject=f"Накладная по заказу {order.number}",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient],
        fail_silently=False,
    )


def send_order_status_email(order: Order) -> None:
    """Уведомление покупателю о смене статуса заказа."""
    status_label = order.get_status_display()
    body = (
        f"Здравствуйте!\n\n"
        f"Статус вашего заказа {order.number} изменился: {status_label}.\n"
        f"Поставщик: {order.supplier.company_name}\n"
        f"Сумма: {order.total_amount} ₽\n"
    )
    send_mail(
        subject=f"Заказ {order.number}: {status_label}",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[order.buyer.email],
        fail_silently=True,  # статус важнее письма
    )