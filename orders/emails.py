import logging
from django.conf import settings
from django.core.mail import send_mail
from .models import Order

logger = logging.getLogger(__name__)


def _get_order(order_or_id):
    if isinstance(order_or_id, Order):
        return order_or_id
    return Order.objects.select_related("buyer", "supplier__user").prefetch_related("items").get(pk=order_or_id)


def _order_lines_text(order):
    return "\n".join(
        f"  - {item.product_name} — {item.quantity} {item.unit} "
        f"× {item.price} ₽ = {item.line_total} ₽"
        for item in order.items.all()
    )


def send_order_confirmation_to_buyer(order_or_id):
    order = _get_order(order_or_id)
    if not order.buyer.email:
        logger.warning("У заказа %s отсутствует email покупателя", order.pk)
        return
    send_mail(
        subject=f"Заказ {order.number} принят",
        message=(f"Здравствуйте!\n\nВаш заказ {order.number} принят.\n"
                 f"Поставщик: {order.supplier.company_name}\n"
                 f"Сумма: {order.total_amount} ₽\n"
                 f"Адрес: {order.delivery_address_text or '—'}\n\n"
                 f"Состав заказа:\n{_order_lines_text(order)}\n"),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[order.buyer.email], fail_silently=False,
    )


def send_order_invoice_to_supplier(order_or_id):
    """Историческое имя функции; накладная направляется администратору."""
    order = _get_order(order_or_id)
    admin_email = getattr(settings, "ORDER_ADMIN_EMAIL", "")
    if not admin_email:
        logger.warning("ORDER_ADMIN_EMAIL не задан: накладная заказа %s не отправлена", order.pk)
        return
    send_mail(
        subject=f"Накладная по заказу {order.number}",
        message=(f"Новый заказ {order.number}\n"
                 f"Покупатель: {order.buyer.username} ({order.buyer.email})\n"
                 f"Поставщик: {order.supplier.company_name}\n"
                 f"Адрес: {order.delivery_address_text or '—'}\n"
                 f"Сумма: {order.total_amount} ₽\n\n"
                 f"Позиции:\n{_order_lines_text(order)}\n"),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[admin_email], fail_silently=False,
    )


def send_order_notifications(order_id):
    """Сбой почты не отменяет уже оформленный заказ."""
    for sender in (send_order_confirmation_to_buyer, send_order_invoice_to_supplier):
        try:
            sender(order_id)
        except Exception:
            logger.exception("Не удалось отправить уведомление о заказе %s", order_id)


def send_order_status_email(order_or_id):
    order = _get_order(order_or_id)
    if not order.buyer.email:
        return
    try:
        send_mail(
            subject=f"Заказ {order.number}: {order.get_status_display()}",
            message=(f"Статус заказа {order.number} изменён: "
                     f"{order.get_status_display()}.\n"
                     f"Поставщик: {order.supplier.company_name}\n"
                     f"Сумма: {order.total_amount} ₽\n"),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[order.buyer.email], fail_silently=False,
        )
    except Exception:
        logger.exception("Не удалось отправить статус заказа %s", order.pk)
