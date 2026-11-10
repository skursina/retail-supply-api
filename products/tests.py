from decimal import Decimal
from unittest.mock import patch
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from rest_framework.test import APIClient

from .models import SupplierProduct, SupplierProfile
from products.tasks import import_products_task


class ProductImportTests(TestCase):
    """Проверки YAML-импорта каталога."""

    def setUp(self):
        User = get_user_model()

        self.supplier = User.objects.create_user(
            username="import_test_supplier",
            password="StrongPassword2026!",
            role=User.Role.SUPPLIER,
            is_active=True,
        )

    def test_repeated_import_does_not_create_duplicates(self):
        """Повторный импорт обновляет предложения."""

        # Первый импорт
        call_command(
            "import_products",
            "shop1.yaml",
            supplier=self.supplier.username,
        )

        first_count = SupplierProduct.objects.filter(
            supplier__user=self.supplier
        ).count()

        self.assertEqual(first_count, 14)

        # Второй импорт
        call_command(
            "import_products",
            "shop1.yaml",
            supplier=self.supplier.username,
        )

        offers = SupplierProduct.objects.filter(
            supplier__user=self.supplier
        )

        self.assertEqual(offers.count(), 14)

        # Проверяем конкретный товар
        iphone = offers.get(supplier_article="4216292")

        self.assertEqual(iphone.price, Decimal("110000"))
        self.assertEqual(iphone.quantity, 14)

    def test_import_rejects_negative_price(self):
        """Импорт отклоняет отрицательную цену без записи в БД."""

        invalid_data = {
            "shop": "Тестовый поставщик",
            "categories": [
                {"id": 1, "name": "Тестовая категория"}
            ],
            "goods": [
                {
                    "id": 1001,
                    "category": 1,
                    "name": "Тестовый товар",
                    "price": -500,
                    "quantity": 10,
                    "parameters": {},
                }
            ],
        }

        # Подменяем содержимое YAML только внутри теста.
        with patch(
            "products.management.commands.import_products.yaml.safe_load",
            return_value=invalid_data,
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "import_products",
                    "shop1.yaml",
                    supplier=self.supplier.username,
                )

        # Ни одного предложения не должно появиться.
        self.assertEqual(
            SupplierProduct.objects.filter(
                supplier__user=self.supplier
            ).count(),
            0,
        )        


class ProductCatalogTests(TestCase):
    """Проверки публичного API каталога."""

    def setUp(self):
        from .models import Category, Product

        self.client = APIClient()

        self.category = Category.objects.create(
            name="Тестовая категория каталога"
        )

        self.active_product = Product.objects.create(
            name="Активный товар",
            category=self.category,
            is_active=True,
        )

        self.inactive_product = Product.objects.create(
            name="Скрытый товар",
            category=self.category,
            is_active=False,
        )

    def test_catalog_is_public(self):
        """Каталог доступен без авторизации."""

        response = self.client.get(
            "/api/catalog/products/"
        )

        self.assertEqual(response.status_code, 200)

    def test_catalog_contains_only_active_products(self):
        """Неактивные товары отсутствуют в каталоге."""

        response = self.client.get(
            "/api/catalog/products/"
        )

        self.assertEqual(response.status_code, 200)

        # Поддерживаем как обычный список, так и пагинацию DRF.
        data = response.data
        products = data.get("results", []) if isinstance(data, dict) else data

        ids = [product["id"] for product in products]

        self.assertIn(self.active_product.id, ids)
        self.assertNotIn(self.inactive_product.id, ids)

    def test_product_detail(self):
        """Можно получить подробную информацию об активном товаре."""

        response = self.client.get(
            f"/api/catalog/products/{self.active_product.id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["name"],
            "Активный товар",
        )


class SupplierOrderSettingsTests(TestCase):
    """Проверки API управления приёмом заказов."""

    def setUp(self):
        User = get_user_model()

        self.supplier = User.objects.create_user(
            username="settings_supplier",
            password="StrongPassword2026!",
            role=User.Role.SUPPLIER,
            is_active=True,
        )

        self.other_supplier = User.objects.create_user(
            username="other_supplier",
            password="StrongPassword2026!",
            role=User.Role.SUPPLIER,
            is_active=True,
        )

        self.buyer = User.objects.create_user(
            username="settings_buyer",
            password="StrongPassword2026!",
            role=User.Role.BUYER,
            is_active=True,
        )

        self.shop = SupplierProfile.objects.create(
            user=self.supplier,
            company_name="Магазин №1",
            is_accepting_orders=True,
        )

        self.other_shop = SupplierProfile.objects.create(
            user=self.other_supplier,
            company_name="Магазин №2",
            is_accepting_orders=True,
        )

        self.client = APIClient()
        self.url = "/api/catalog/supplier/settings/"

    def test_supplier_can_disable_orders(self):
        """Поставщик может отключить приём заказов."""
        self.client.force_authenticate(user=self.supplier)

        response = self.client.patch(
            self.url,
            {"is_accepting_orders": False},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.shop.refresh_from_db()
        self.assertFalse(self.shop.is_accepting_orders)

    def test_supplier_cannot_change_other_shop(self):
        """Изменение настроек не затрагивает чужой магазин."""
        self.client.force_authenticate(user=self.supplier)

        response = self.client.patch(
            self.url,
            {"is_accepting_orders": False},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.other_shop.refresh_from_db()
        self.assertTrue(self.other_shop.is_accepting_orders)

    def test_buyer_cannot_manage_supplier_settings(self):
        """Покупатель не может управлять магазином."""
        self.client.force_authenticate(user=self.buyer)

        response = self.client.patch(
            self.url,
            {"is_accepting_orders": False},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_cannot_manage_settings(self):
        """Неавторизованный пользователь не имеет доступа."""
        response = self.client.patch(
            self.url,
            {"is_accepting_orders": False},
            format="json",
        )

        self.assertIn(response.status_code, [401, 403])

    def test_supplier_can_view_own_settings(self):
        """Поставщик видит настройки своего магазина."""
        self.client.force_authenticate(user=self.supplier)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["company_name"],
            "Магазин №1",
        )
        self.assertTrue(response.data["is_accepting_orders"])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class CeleryImportTests(TestCase):
    """Проверка фонового импорта товаров."""

    def test_import_creates_and_updates_products(self):
        User = get_user_model()

        supplier = User.objects.create_user(
            username="celery_import_supplier",
            password="StrongPassword2026!",
            role=User.Role.SUPPLIER,
            is_active=True,
        )

        yaml_content = """
shop: Celery Test Shop
categories:
  - id: 1
    name: Celery Test Category
goods:
  - id: CELERY-001
    category: 1
    name: Celery Test Product
    price: 1500
    quantity: 10
"""

        # Первый запуск создаёт предложение.
        first = import_products_task.delay(
            yaml_content,
            supplier.pk,
        ).get()

        self.assertEqual(first["created"], 1)
        self.assertEqual(first["updated"], 0)

        # Второй запуск обновляет существующее предложение.
        second = import_products_task.delay(
            yaml_content,
            supplier.pk,
        ).get()

        self.assertEqual(second["created"], 0)
        self.assertEqual(second["updated"], 1)

        # Дубликатов быть не должно.
        self.assertEqual(
            SupplierProduct.objects.filter(
                supplier__user=supplier,
                supplier_article="CELERY-001",
            ).count(),
            1,
        )


class ProductImportAPITests(TestCase):
    """Проверки доступа к API импорта товаров."""

    def setUp(self):
        User = get_user_model()

        self.buyer = User.objects.create_user(
            username="import_api_buyer",
            password="StrongPassword2026!",
            role=User.Role.BUYER,
            is_active=True,
        )

        self.supplier = User.objects.create_user(
            username="import_api_supplier",
            password="StrongPassword2026!",
            role=User.Role.SUPPLIER,
            is_active=True,
        )

        self.client = APIClient()
        self.url = "/api/catalog/import/"

    @staticmethod
    def make_file():
        return SimpleUploadedFile(
            "catalog.yaml",
            b"shop: Test Shop\ncategories: []\ngoods: []\n",
            content_type="application/x-yaml",
        )

    def test_anonymous_cannot_import(self):
        response = self.client.post(
            self.url,
            {"file": self.make_file()},
            format="multipart",
        )

        self.assertIn(response.status_code, (401, 403))

    def test_buyer_cannot_import(self):
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            self.url,
            {"file": self.make_file()},
            format="multipart",
        )

        self.assertEqual(response.status_code, 403)

    @patch("products.views.import_products_task.delay")
    def test_supplier_can_queue_import(self, mock_delay):
        self.client.force_authenticate(user=self.supplier)
        mock_delay.return_value.id = "test-task-123"

        response = self.client.post(
            self.url,
            {"file": self.make_file()},
            format="multipart",
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.data["task_id"],
            "test-task-123",
        )

        mock_delay.assert_called_once()

        args = mock_delay.call_args.args
        self.assertEqual(args[1], self.supplier.pk)
        self.assertIn("shop: Test Shop", args[0])

    @patch("products.views.import_products_task.delay")
    def test_rejects_wrong_file_extension(self, mock_delay):
        self.client.force_authenticate(user=self.supplier)

        invalid_file = SimpleUploadedFile(
            "catalog.txt",
            b"shop: Test Shop",
        )

        response = self.client.post(
            self.url,
            {"file": invalid_file},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        mock_delay.assert_not_called()

    @patch("products.views.import_products_task.delay")
    def test_rejects_empty_file(self, mock_delay):
        """Пустой YAML нельзя отправить на импорт."""
        self.client.force_authenticate(user=self.supplier)

        empty_file = SimpleUploadedFile(
            "empty.yaml",
            b"",
            content_type="application/x-yaml",
        )

        response = self.client.post(
            self.url,
            {"file": empty_file},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        mock_delay.assert_not_called()

    @patch("products.views.import_products_task.delay")
    def test_rejects_oversized_file(self, mock_delay):
        """YAML больше 2 МБ отклоняется."""
        self.client.force_authenticate(user=self.supplier)

        large_file = SimpleUploadedFile(
            "large.yaml",
            b"x" * (2 * 1024 * 1024 + 1),
            content_type="application/x-yaml",
        )

        response = self.client.post(
            self.url,
            {"file": large_file},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        mock_delay.assert_not_called()

    @patch("products.views.import_products_task.delay")
    def test_returns_503_when_broker_unavailable(self, mock_delay):
        """Недоступный Redis не должен приводить к необработанной ошибке."""
        from kombu.exceptions import OperationalError

        self.client.force_authenticate(user=self.supplier)
        mock_delay.side_effect = OperationalError("Redis unavailable")

        response = self.client.post(
            self.url,
            {"file": self.make_file()},
            format="multipart",
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("detail", response.data)
        mock_delay.assert_called_once()