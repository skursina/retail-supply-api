from django.db import models
from django.conf import settings


class Category(models.Model):
    name = models.CharField(
        max_length=150,
        unique=True,
        verbose_name="Название категории"
    )
    description = models.TextField(
        blank=True,
        verbose_name="Описание",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="Родительская категория"
    )

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="Категория",
    )
    name = models.CharField(
        max_length=255,
        verbose_name="Название товара",
    )
    description = models.TextField(
        blank=True,
        verbose_name="Описание",
    )
    image = models.URLField(
        blank=True,
        verbose_name="Ссылка на изображение",
    )
    unit = models.CharField(
        max_length=50,
        default="шт.",
        verbose_name="Единица измерения",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Активен",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления",
    )

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProductParameter(models.Model):
    name = models.CharField(
        max_length=150,
        unique=True,
        verbose_name="Название характеристики",
    )
    categories = models.ManyToManyField(
        Category,
        related_name="parameters",
        blank=True,
        verbose_name="Категории",
    )

    class Meta:
        verbose_name = "Характеристика товара"
        verbose_name_plural = "Характеристики товаров"
        ordering = ["name"]

    def __str__(self):
        return self.name

class ProductParameterValue(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="parameter_value",
        verbose_name="Товар",
    )
    parameter = models.ForeignKey(
        ProductParameter,
        on_delete=models.PROTECT,
        related_name="values",
        verbose_name="Характеристика",
    )
    value = models.CharField(
        max_length=255,
        verbose_name="Значение",
    )

    class Meta:
        verbose_name = "Значение характеристики"
        verbose_name_plural = "Значения характеристик"
        constraints = [
            models.UniqueConstraint(
                fields = ["product", "parameter"],
                name = "unique_product_parameter",
            )
        ]

    def __str__(self):
        return f"{self.product.name}: {self.parameter.name} - {self.value}"


class SupplierProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="supplier_profile",
        verbose_name="Пользователь",
    )
    company_name = models.CharField(
        max_length=255,
        verbose_name="Название компании",
    )
    contact_person = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Контактное лицо",
    )
    phone = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Телефон",
    )
    address = models.TextField(
        blank=True,
        verbose_name="Адрес",
    )
    is_accepting_orders = models.BooleanField(
        default=True,
        verbose_name="Принимает заказы",
    )

    class Meta:
        verbose_name = "Поставщик"
        verbose_name_plural = "Поставщики"
        ordering = ["company_name"]

    def __str__(self):
        return self.company_name


class SupplierProduct(models.Model):
    supplier = models.ForeignKey(
        SupplierProfile,
        on_delete=models.PROTECT,
        related_name="offers",
        verbose_name="Поставщик",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="supplier_offers",
        verbose_name="Товар",
    )
    supplier_article = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Артикул поставщика",
    )
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Цена",
    )
    quantity = models.PositiveBigIntegerField(
        default=0,
        verbose_name="Остаток",
    )
    is_available = models.BooleanField(
        default=True,
        verbose_name="Доступен для заказа",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления",
    )

    class Meta:
        verbose_name = "Предложение поставщика"
        verbose_name_plural = "Предложения поставщиков"
        constraints = [
            models.UniqueConstraint(
                fields=["supplier", "product"],
                name="unique_supplier_product",
            )
        ]
        ordering = ["product__name", "price"]

    def __str__(self):
        return (
            f"{self.product.name} - {self.supplier.company_name}"
        )