from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings

from .emails import (
    send_order_notifications,
    send_order_status_email
)


@shared_task(
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_email(self, subject, message, recipient_list):
    """
    Фоновая отправка email через Celery.

    Задача выполняется отдельным worker,
    не блокируя HTTP-запрос Django.
    """
    return send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipient_list,
        fail_silently=False,
    )


@shared_task(
    bind=True,
    name="orders.send_order_notifications",
)
def send_order_notifications_task(self, order_id):
    """
    Фоновая отправка уведомлений о заказе.

    Получает ID заказа, загружает необходимые данные
    и отправляет письма покупателю и администратору.
    """
    send_order_notifications(order_id)


@shared_task(name="orders.send_order_status_email")
def send_order_status_email_task(order_id):
    """
    Фоновая отправка уведомления об изменении статуса заказа.
    """
    send_order_status_email(order_id)