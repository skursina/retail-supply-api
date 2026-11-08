import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


def generate_order_number():
    """Генерирует уникальный номер заказа."""
    return f"ORD-{uuid.uuid4().hex[:12].upper()}"


class Cart(models.Model):
    """Корзина покупателя."""

    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="carts",
        verbose_name="Покупатель",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Активна",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата изменения",
    )

    class Meta:
        verbose_name = "Корзина"
        verbose_name_plural = "Корзины"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["buyer"],
                condition=Q(is_active=True),
                name="unique_active_cart_per_buyer",
            )
        ]

    def __str__(self):
        return f"Корзина: {self.buyer.username}"


class CartItem(models.Model):
    """Позиция корзины."""

    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Корзина",
    )
    supplier_product = models.ForeignKey(
        "products.SupplierProduct",
        on_delete=models.PROTECT,
        related_name="cart_items",
        verbose_name="Предложение поставщика",
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name="Количество",
    )

    class Meta:
        verbose_name = "Позиция корзины"
        verbose_name_plural = "Позиции корзины"
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "supplier_product"],
                name="unique_supplier_product_in_cart",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="cart_item_quantity_gte_1",
            ),
        ]

    def __str__(self):
        return (
            f"{self.supplier_product.product.name} "
            f"— {self.quantity}"
        )


class Order(models.Model):
    """Заказ покупателя одному поставщику."""

    class Status(models.TextChoices):
        NEW = "new", "Новый"
        CONFIRMED = "confirmed", "Подтверждён поставщиком"
        PROCESSING = "processing", "В обработке"
        SHIPPED = "shipped", "Отгружен"
        COMPLETED = "completed", "Выполнен"
        REJECTED = "rejected", "Отклонён поставщиком"
        CANCELLED = "cancelled", "Отменён"

    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="Покупатель",
    )
    supplier = models.ForeignKey(
        "products.SupplierProfile",
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="Поставщик",
    )
    number = models.CharField(
        max_length=20,
        unique=True,
        default=generate_order_number,
        editable=False,
        verbose_name="Номер заказа",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
        verbose_name="Статус",
    )
    delivery_address = models.ForeignKey(
        "Address", 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        related_name="orders", 
        verbose_name="Адрес доставки",
    )
    delivery_address_text = models.TextField(
        blank=True, 
        verbose_name="Адрес доставки на момент заказа",
    )
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name="Сумма заказа",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата оформления",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата изменения",
    )

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["buyer", "created_at"],
                name="order_buyer_date_idx",
            ),
            models.Index(
                fields=["supplier", "status"],
                name="order_supplier_status_idx",
            ),
        ]

    def __str__(self):
        return self.number


class OrderItem(models.Model):
    """Позиция оформленного заказа."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Заказ",
    )
    supplier_product = models.ForeignKey(
        "products.SupplierProduct",
        on_delete=models.PROTECT,
        related_name="order_items",
        verbose_name="Предложение поставщика",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="order_items",
        verbose_name="Товар",
    )
    product_name = models.CharField(
        max_length=255,
        verbose_name="Название товара на момент заказа",
    )
    unit = models.CharField(
        max_length=50,
        verbose_name="Единица измерения на момент заказа",
    )
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Количество",
    )
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Цена на момент заказа",
    )

    class Meta:
        verbose_name = "Позиция заказа"
        verbose_name_plural = "Позиции заказа"
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="order_item_quantity_gte_1",
            ),
            models.CheckConstraint(
                condition=Q(price__gte=0),
                name="order_item_price_gte_0",
            ),
        ]

    def __str__(self):
        return f"{self.product_name} — {self.quantity}"

    @property
    def line_total(self):
        """Стоимость позиции заказа."""
        return self.price * self.quantity


class Address(models.Model):
    """Адрес доставки покупателя."""

    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="addresses",
        verbose_name="Покупатель",
    )
    title = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Название (например, «Дом»)",
    )
    city = models.CharField(max_length=100, verbose_name="Город")
    street = models.CharField(max_length=255, verbose_name="Улица")
    house = models.CharField(max_length=20, verbose_name="Дом")
    building = models.CharField(
        max_length=20, blank=True, verbose_name="Корпус/строение"
    )
    apartment = models.CharField(
        max_length=20, blank=True, verbose_name="Квартира/офис"
    )
    postal_code = models.CharField(
        max_length=20, blank=True, verbose_name="Индекс"
    )
    is_default = models.BooleanField(
        default=False, verbose_name="Адрес по умолчанию"
    )
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Дата создания"
    )

    class Meta:
        verbose_name = "Адрес доставки"
        verbose_name_plural = "Адреса доставки"
        ordering = ["-is_default", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["buyer"],
                condition=Q(is_default=True),
                name="unique_default_address_per_buyer",
            )
        ]

    def __str__(self):
        parts = [self.city, self.street, f"д. {self.house}"]
        if self.building:
            parts.append(f"корп. {self.building}")
        if self.apartment:
            parts.append(f"кв. {self.apartment}")
        return ", ".join(parts)