from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from rest_framework.test import APIClient

from products.models import (
    Category,
    Product,
    SupplierProfile,
    SupplierProduct,
)

from .models import (
    Cart, CartItem, Address, 
    Order, OrderItem,
)
from .services import change_order_status


class DisabledSupplierTests(TestCase):
    """Проверяем запрет заказов у отключённого поставщика."""

    def setUp(self):
        User = get_user_model()

        # Создаём покупателя
        self.buyer = User.objects.create_user(
            username="order_test_buyer",
            email="order_buyer@example.com",
            password="StrongPassword2026!",
            role=User.Role.BUYER,
            is_active=True,
        )

        # Создаём поставщика
        self.supplier_user = User.objects.create_user(
            username="order_test_supplier",
            password="StrongPassword2026!",
            role=User.Role.SUPPLIER,
            is_active=True,
        )

        self.supplier = SupplierProfile.objects.create(
            user=self.supplier_user,
            company_name="Тестовый поставщик",
            is_accepting_orders=False,
        )

        self.category = Category.objects.create(
            name="Тестовая категория заказов",
        )

        self.product = Product.objects.create(
            category=self.category,
            name="Тестовый товар",
            is_active=True,
        )

        self.offer = SupplierProduct.objects.create(
            supplier=self.supplier,
            product=self.product,
            supplier_article="ORDER-TEST-001",
            price="1500.00",
            quantity=10,
            is_available=True,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.buyer)

    def test_cannot_add_product_from_disabled_supplier(self):
        """Нельзя добавить товар отключённого поставщика."""

        response = self.client.post(
            "/api/cart/items/",
            {
                "supplier_product": self.offer.id,
                "quantity": 2,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(CartItem.objects.count(), 0)

    def test_cannot_confirm_order_from_disabled_supplier(self):
        """Нельзя оформить заказ после отключения поставщика."""
        from .models import Address, Order

        # Товар уже находится в корзине.
        cart = Cart.objects.create(buyer=self.buyer)

        CartItem.objects.create(
            cart=cart,
            supplier_product=self.offer,
            quantity=2,
        )

        # Создаём адрес доставки.
        address = Address.objects.create(
            buyer=self.buyer,
            city="Москва",
            street="Тестовая",
            house="10",
        )

        response = self.client.post(
            "/api/orders/confirm/",
            {"address_id": address.id},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

        # Проверяем, что остатки не списались.
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.quantity, 10)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class MultiSupplierOrderTests(TestCase):
    """Проверки оформления заказов от нескольких поставщиков."""

    def setUp(self):
        User = get_user_model()

        self.buyer = User.objects.create_user(
            username="multi_order_buyer",
            email="multi_buyer@example.com",
            password="StrongPassword2026!",
            role=User.Role.BUYER,
            is_active=True,
        )

        self.category = Category.objects.create(
            name="Продукты для тестирования заказов"
        )

        self.cart = Cart.objects.create(buyer=self.buyer)

        self.address = Address.objects.create(
            buyer=self.buyer,
            city="Москва",
            street="Ленина",
            house="15",
        )

        self.offers = []

        # Создаём двух независимых поставщиков.
        for number, price in enumerate(("100.00", "250.00"), start=1):
            supplier_user = User.objects.create_user(
                username=f"multi_supplier_{number}",
                password="StrongPassword2026!",
                role=User.Role.SUPPLIER,
                is_active=True,
            )

            supplier = SupplierProfile.objects.create(
                user=supplier_user,
                company_name=f"Поставщик №{number}",
                is_accepting_orders=True,
            )

            product = Product.objects.create(
                category=self.category,
                name=f"Товар №{number}",
                is_active=True,
            )

            offer = SupplierProduct.objects.create(
                supplier=supplier,
                product=product,
                supplier_article=f"MULTI-{number}",
                price=Decimal(price),
                quantity=10,
                is_available=True,
            )

            self.offers.append(offer)

            CartItem.objects.create(
                cart=self.cart,
                supplier_product=offer,
                quantity=2,
            )

        self.client = APIClient()
        self.client.force_authenticate(user=self.buyer)

    def test_order_is_split_by_supplier(self):
        """Одна корзина превращается в два отдельных заказа."""

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/orders/confirm/",
                {"address_id": self.address.id},
                format="json",
            )

        self.assertEqual(response.status_code, 201)

        orders = Order.objects.filter(buyer=self.buyer)

        # Каждый поставщик получает отдельный заказ.
        self.assertEqual(orders.count(), 2)

        # Проверяем итоговые суммы.
        amounts = sorted(
            order.total_amount for order in orders
        )

        self.assertEqual(
            amounts,
            [Decimal("200.00"), Decimal("500.00")],
        )

        # Проверяем списание остатков.
        for offer in self.offers:
            offer.refresh_from_db()
            self.assertEqual(offer.quantity, 8)

        # Корзина закрыта после оформления.
        self.cart.refresh_from_db()
        self.assertFalse(self.cart.is_active)

        # Позиции оформленной корзины удалены.
        self.assertEqual(
            CartItem.objects.filter(cart=self.cart).count(),
            0,
        )

    def test_rejected_order_restores_stock(self):
        """При отклонении заказа товары возвращаются на склад."""

        # Оформляем заказы от двух поставщиков.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/orders/confirm/",
                {"address_id": self.address.id},
                format="json",
            )

        self.assertEqual(response.status_code, 201)

        # Берём заказ первого поставщика.
        offer = self.offers[0]

        order = Order.objects.get(
            buyer=self.buyer,
            supplier=offer.supplier,
        )

        offer.refresh_from_db()
        self.assertEqual(offer.quantity, 8)

        # Авторизуем поставщика этого заказа.
        self.client.force_authenticate(
            user=offer.supplier.user
        )

        # Поставщик отклоняет заказ.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                f"/api/orders/{order.id}/status/",
                {"status": "rejected"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)

        # Проверяем новый статус.
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.REJECTED)

        # Остаток должен восстановиться.
        offer.refresh_from_db()
        self.assertEqual(offer.quantity, 10)

        # Остаток второго поставщика не изменяется.
        self.offers[1].refresh_from_db()
        self.assertEqual(self.offers[1].quantity, 8)        

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ORDER_ADMIN_EMAIL="admin@example.com",
    )
    def test_order_sends_email_notifications(self):
        """Покупатель и администратор получают письма о заказах."""

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/orders/confirm/",
                {"address_id": self.address.id},
                format="json",
            )

        self.assertEqual(response.status_code, 201)

        # Два поставщика — два отдельных заказа.
        self.assertEqual(
            Order.objects.filter(buyer=self.buyer).count(),
            2,
        )

        # На каждый заказ отправляются два письма:
        # покупателю и администратору.
        self.assertEqual(len(mail.outbox), 4)

        recipients = [
            email
            for message in mail.outbox
            for email in message.to
        ]

        self.assertEqual(
            recipients.count("multi_buyer@example.com"),
            2,
        )

        self.assertEqual(
            recipients.count("admin@example.com"),
            2,
        )

        # Проверяем темы писем.
        self.assertEqual(
            sum("Заказ" in message.subject for message in mail.outbox),
            2,
        )

        self.assertEqual(
            sum("Накладная" in message.subject for message in mail.outbox),
            2,
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_order_status_change_sends_email(self):
        """При изменении статуса покупатель получает уведомление."""

        # Оформляем два заказа.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/orders/confirm/",
                {"address_id": self.address.id},
                format="json",
            )

        self.assertEqual(response.status_code, 201)

        # Очищаем письма, отправленные при оформлении.
        mail.outbox.clear()

        offer = self.offers[0]

        order = Order.objects.get(
            buyer=self.buyer,
            supplier=offer.supplier,
        )

        # Авторизуемся как поставщик заказа.
        self.client.force_authenticate(
            user=offer.supplier.user
        )

        # Меняем статус заказа.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                f"/api/orders/{order.id}/status/",
                {"status": "confirmed"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)

        order.refresh_from_db()
        self.assertEqual(
            order.status,
            Order.Status.CONFIRMED,
        )

        # Покупателю должно прийти одно уведомление.
        self.assertEqual(len(mail.outbox), 1)

        message = mail.outbox[0]

        self.assertIn(
            self.buyer.email,
            message.to,
        )

        self.assertIn(
            order.number,
            message.subject,
        )        

    def test_buyer_cannot_view_other_users_order(self):
        """Покупатель не может просматривать чужой заказ."""

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/orders/confirm/",
                {"address_id": self.address.id},
                format="json",
            )

        self.assertEqual(response.status_code, 201)

        order = Order.objects.filter(buyer=self.buyer).first()

        other_buyer = get_user_model().objects.create_user(
            username="other_order_buyer",
            email="other_buyer@example.com",
            password="StrongPassword2026!",
            role="buyer",
            is_active=True,
        )

        self.client.force_authenticate(user=other_buyer)

        response = self.client.get(
            f"/api/orders/{order.id}/"
        )

        self.assertEqual(response.status_code, 404)

    def test_supplier_cannot_change_other_suppliers_order(self):
        """Поставщик не может менять статус чужого заказа."""

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/orders/confirm/",
                {"address_id": self.address.id},
                format="json",
            )

        self.assertEqual(response.status_code, 201)

        first_offer = self.offers[0]
        second_offer = self.offers[1]

        first_order = Order.objects.get(
            buyer=self.buyer,
            supplier=first_offer.supplier,
        )

        # Авторизуемся как второй поставщик.
        self.client.force_authenticate(
            user=second_offer.supplier.user
        )

        response = self.client.patch(
            f"/api/orders/{first_order.id}/status/",
            {"status": "confirmed"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

        first_order.refresh_from_db()
        self.assertEqual(first_order.status, Order.Status.NEW)

    def test_order_address_survives_address_deletion(self):
        """Адрес доставки сохраняется в истории заказа."""

        # Оформляем заказ с существующим адресом.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/orders/confirm/",
                {"address_id": self.address.id},
                format="json",
            )

        self.assertEqual(response.status_code, 201)

        order = Order.objects.filter(
            buyer=self.buyer
        ).first()

        original_address = str(self.address)

        # Удаляем адрес через API.
        delete_response = self.client.delete(
            f"/api/addresses/{self.address.id}/"
        )

        self.assertEqual(delete_response.status_code, 204)

        # Проверяем заказ после удаления адреса.
        order.refresh_from_db()

        self.assertIsNone(order.delivery_address)
        self.assertEqual(
            order.delivery_address_text,
            original_address,
        )

        # Проверяем, что сохранённый адрес виден через API.
        detail_response = self.client.get(
            f"/api/orders/{order.id}/"
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(
            detail_response.data["delivery_address_text"],
            original_address,
        )

    @patch("orders.views.send_order_notifications_task.delay")
    def test_order_notifications_are_queued_after_commit(self, mock_delay):
        """Уведомления ставятся в очередь после подтверждения транзакции."""

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self.client.post(
                "/api/orders/confirm/",
                {"address_id": self.address.id},
                format="json",
            )

        self.assertEqual(response.status_code, 201)

        # Пока on_commit не выполнен, задач в очереди нет.
        mock_delay.assert_not_called()

        # Два поставщика — два заказа и две отложенные задачи.
        self.assertEqual(len(callbacks), 2)

        # Имитируем успешное завершение транзакции.
        for callback in callbacks:
            callback()

        order_ids = set(
            Order.objects.filter(buyer=self.buyer).values_list(
                "id", flat=True
            )
        )

        self.assertEqual(mock_delay.call_count, 2)

        queued_ids = {
            call.args[0]
            for call in mock_delay.call_args_list
        }

        self.assertEqual(queued_ids, order_ids)


class CartSecurityTests(TestCase):
    """Проверки безопасности редактирования корзины."""

    def setUp(self):
        User = get_user_model()

        self.buyer = User.objects.create_user(
            username="cart_security_buyer",
            email="cart_security@example.com",
            password="StrongPassword2026!",
            role=User.Role.BUYER,
            is_active=True,
        )

        supplier_user = User.objects.create_user(
            username="cart_security_supplier",
            password="StrongPassword2026!",
            role=User.Role.SUPPLIER,
            is_active=True,
        )

        supplier = SupplierProfile.objects.create(
            user=supplier_user,
            company_name="Поставщик для теста корзины",
        )

        category = Category.objects.create(
            name="Категория теста безопасности"
        )

        self.offers = []

        for number in (1, 2):
            product = Product.objects.create(
                category=category,
                name=f"Товар безопасности №{number}",
                is_active=True,
            )

            offer = SupplierProduct.objects.create(
                supplier=supplier,
                product=product,
                supplier_article=f"SECURITY-{number}",
                price="100.00",
                quantity=10,
                is_available=True,
            )

            self.offers.append(offer)

        self.cart = Cart.objects.create(buyer=self.buyer)

        self.item = CartItem.objects.create(
            cart=self.cart,
            supplier_product=self.offers[0],
            quantity=2,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.buyer)

    def test_cannot_replace_product_in_cart(self):
        """PATCH не должен позволять подменять товар."""

        response = self.client.patch(
            f"/api/cart/items/{self.item.id}/",
            {
                "supplier_product": self.offers[1].id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.item.refresh_from_db()

        self.assertEqual(
            self.item.supplier_product_id,
            self.offers[0].id,
        )

    def test_can_update_cart_item_quantity(self):
        """Покупатель может изменить количество товара."""

        response = self.client.patch(
            f"/api/cart/items/{self.item.id}/",
            {"quantity": 5},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 5)

    def test_cannot_exceed_available_stock(self):
        """Количество товара не может превышать остаток."""

        response = self.client.patch(
            f"/api/cart/items/{self.item.id}/",
            {"quantity": 20},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 2)

    def test_can_delete_cart_item(self):
        """Покупатель может удалить товар из своей корзины."""

        response = self.client.delete(
            f"/api/cart/items/{self.item.id}/"
        )

        self.assertEqual(response.status_code, 204)

        self.assertFalse(
            CartItem.objects.filter(pk=self.item.id).exists()
        )

        # Удаление из корзины не списывает складской остаток.
        self.offers[0].refresh_from_db()
        self.assertEqual(self.offers[0].quantity, 10)

    def test_cannot_modify_other_users_cart(self):
        """Покупатель не может изменять чужую корзину."""

        User = get_user_model()

        other_buyer = User.objects.create_user(
            username="another_cart_buyer",
            email="another_cart@example.com",
            password="StrongPassword2026!",
            role=User.Role.BUYER,
            is_active=True,
        )

        # Авторизуемся под другим покупателем.
        self.client.force_authenticate(user=other_buyer)

        # Пытаемся изменить чужую позицию.
        response = self.client.patch(
            f"/api/cart/items/{self.item.id}/",
            {"quantity": 5},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

        # Пытаемся удалить чужую позицию.
        response = self.client.delete(
            f"/api/cart/items/{self.item.id}/"
        )

        self.assertEqual(response.status_code, 404)

        # Исходная позиция не изменилась.
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 2)

    def test_cannot_update_cart_when_supplier_disabled(self):
        """Нельзя менять количество после отключения поставщика."""

        # Поставщик отключает приём заказов.
        supplier = self.offers[0].supplier
        supplier.is_accepting_orders = False
        supplier.save(update_fields=["is_accepting_orders"])

        # Покупатель пытается увеличить количество.
        response = self.client.patch(
            f"/api/cart/items/{self.item.id}/",
            {"quantity": 5},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        # В корзине остаётся прежнее количество.
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 2)
        

class AddressAPITests(TestCase):
    """Проверки API адресов доставки."""

    def setUp(self):
        User = get_user_model()

        self.buyer = User.objects.create_user(
            username="address_buyer",
            email="address_buyer@example.com",
            password="StrongPassword2026!",
            role=User.Role.BUYER,
            is_active=True,
        )

        self.other_buyer = User.objects.create_user(
            username="other_address_buyer",
            password="StrongPassword2026!",
            role=User.Role.BUYER,
            is_active=True,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.buyer)

        self.url = "/api/addresses/"

    def test_create_address(self):
        """Покупатель может добавить адрес доставки."""

        response = self.client.post(
            self.url,
            {
                "title": "Дом",
                "city": "Москва",
                "street": "Ленина",
                "house": "10",
                "is_default": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        address = Address.objects.get(buyer=self.buyer)

        self.assertEqual(address.city, "Москва")
        self.assertTrue(address.is_default)

    def test_update_address(self):
        """Покупатель может изменить свой адрес."""

        address = Address.objects.create(
            buyer=self.buyer,
            city="Москва",
            street="Ленина",
            house="10",
        )

        response = self.client.patch(
            f"/api/addresses/{address.id}/",
            {"street": "Пушкина"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        address.refresh_from_db()
        self.assertEqual(address.street, "Пушкина")

    def test_delete_address(self):
        """Покупатель может удалить свой адрес."""

        address = Address.objects.create(
            buyer=self.buyer,
            city="Москва",
            street="Ленина",
            house="10",
        )

        response = self.client.delete(
            f"/api/addresses/{address.id}/"
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            Address.objects.filter(pk=address.id).exists()
        )

    def test_cannot_access_other_users_address(self):
        """Чужие адреса недоступны."""

        address = Address.objects.create(
            buyer=self.buyer,
            city="Москва",
            street="Ленина",
            house="10",
        )

        self.client.force_authenticate(user=self.other_buyer)

        response = self.client.get(
            f"/api/addresses/{address.id}/"
        )

        self.assertEqual(response.status_code, 404)

        response = self.client.delete(
            f"/api/addresses/{address.id}/"
        )

        self.assertEqual(response.status_code, 404)

        self.assertTrue(
            Address.objects.filter(pk=address.id).exists()
        )

    def test_only_one_default_address(self):
        """Новый основной адрес заменяет предыдущий."""

        # Создаём первый адрес по умолчанию.
        first_response = self.client.post(
            "/api/addresses/",
            {
                "title": "Дом",
                "city": "Москва",
                "street": "Ленина",
                "house": "10",
                "is_default": True,
            },
            format="json",
        )

        self.assertEqual(first_response.status_code, 201)

        first_id = first_response.data["id"]

        # Создаём второй адрес и делаем его основным.
        second_response = self.client.post(
            "/api/addresses/",
            {
                "title": "Работа",
                "city": "Москва",
                "street": "Пушкина",
                "house": "20",
                "is_default": True,
            },
            format="json",
        )

        self.assertEqual(second_response.status_code, 201)

        # Проверяем состояние адресов.
        first_address = Address.objects.get(pk=first_id)
        second_address = Address.objects.get(
            pk=second_response.data["id"]
        )

        self.assertFalse(first_address.is_default)
        self.assertTrue(second_address.is_default)

        # У пользователя ровно один основной адрес.
        self.assertEqual(
            Address.objects.filter(
                buyer=self.buyer,
                is_default=True,
            ).count(),
            1,
        )        


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class OrderStatusServiceTests(TestCase):
    """Тесты общего сервиса изменения статусов."""

    def setUp(self):
        User = get_user_model()

        self.buyer = User.objects.create_user(
            username="service_buyer",
            email="service_buyer@example.com",
            password="StrongPassword2026!",
            role=User.Role.BUYER,
            is_active=True,
        )

        supplier_user = User.objects.create_user(
            username="service_supplier",
            password="StrongPassword2026!",
            role=User.Role.SUPPLIER,
            is_active=True,
        )

        self.supplier = SupplierProfile.objects.create(
            user=supplier_user,
            company_name="Тестовый магазин сервиса",
        )

        self.category = Category.objects.create(
            name="Категория сервиса",
        )

        self.product = Product.objects.create(
            category=self.category,
            name="Товар сервиса",
        )

        self.offer = SupplierProduct.objects.create(
            supplier=self.supplier,
            product=self.product,
            supplier_article="SERVICE-001",
            price="100.00",
            quantity=8,
            is_available=True,
        )

        self.order = Order.objects.create(
            buyer=self.buyer,
            supplier=self.supplier,
            total_amount="200.00",
        )

        OrderItem.objects.create(
            order=self.order,
            supplier_product=self.offer,
            product=self.product,
            product_name=self.product.name,
            unit="шт.",
            quantity=2,
            price="100.00",
        )

    def test_valid_status_transition(self):
        """Разрешённый переход изменяет статус."""

        with self.captureOnCommitCallbacks(execute=True):
            change_order_status(
                self.order.id,
                Order.Status.CONFIRMED,
            )

        self.order.refresh_from_db()
        self.assertEqual(
            self.order.status,
            Order.Status.CONFIRMED,
        )

    @patch("orders.services.send_order_status_email_task.delay")
    def test_status_email_queued_after_commit(self, mock_delay):
        """Уведомление ставится в очередь после коммита."""

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            change_order_status(
                self.order.id,
                Order.Status.CONFIRMED,
            )

        self.order.refresh_from_db()
        self.assertEqual(
            self.order.status,
            Order.Status.CONFIRMED,
        )

        # Пока транзакция не подтверждена, Celery не вызывается.
        mock_delay.assert_not_called()

        # Проверяем наличие отложенного вызова.
        self.assertEqual(len(callbacks), 1)

        # Имитируем успешное завершение транзакции.
        callbacks[0]()

        # В очередь передаётся ID нужного заказа.
        mock_delay.assert_called_once_with(self.order.id)
        
    def test_invalid_status_transition(self):
        """Недопустимый переход отклоняется."""

        self.order.status = Order.Status.COMPLETED
        self.order.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            change_order_status(
                self.order.id,
                Order.Status.NEW,
            )

        self.order.refresh_from_db()
        self.assertEqual(
            self.order.status,
            Order.Status.COMPLETED,
        )

    def test_rejected_order_restores_stock(self):
        """При отклонении заказа возвращаются остатки."""

        change_order_status(
            self.order.id,
            Order.Status.REJECTED,
        )

        self.order.refresh_from_db()
        self.offer.refresh_from_db()

        self.assertEqual(
            self.order.status,
            Order.Status.REJECTED,
        )
        self.assertEqual(self.offer.quantity, 10)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CELERY_TASK_ALWAYS_EAGER=True,
)
class OrderAdminTests(TestCase):
    """Проверка изменения статусов через Django Admin."""

    def setUp(self):
        User = get_user_model()

        self.admin_user = User.objects.create_superuser(
            username="admin_order_test",
            email="admin_test@example.com",
            password="StrongAdminPassword2026!",
        )

        self.buyer = User.objects.create_user(
            username="admin_test_buyer",
            email="buyer_admin_test@example.com",
            password="StrongPassword2026!",
            role=User.Role.BUYER,
        )

        supplier_user = User.objects.create_user(
            username="admin_test_supplier",
            password="StrongPassword2026!",
            role=User.Role.SUPPLIER,
        )

        self.supplier = SupplierProfile.objects.create(
            user=supplier_user,
            company_name="Тестовый магазин админки",
        )

        self.order = Order.objects.create(
            buyer=self.buyer,
            supplier=self.supplier,
            total_amount="500.00",
        )

        self.client.force_login(self.admin_user)

    def test_admin_can_confirm_order_and_send_email(self):
        """Администратор меняет статус, покупатель получает письмо."""

        url = reverse(
            "admin:orders_order_change",
            args=[self.order.pk],
        )

        # Передаём поля формы заказа.
        data = {
            "status": Order.Status.CONFIRMED,
            "delivery_address": "",
            "delivery_address_text": "",
            "_save": "Save",
            "items-TOTAL_FORMS": "0",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, data)

        self.order.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.order.status,
            Order.Status.CONFIRMED,
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            self.buyer.email,
            mail.outbox[0].to,
        )

    def test_admin_cannot_change_completed_order_to_new(self):
        """Админка запрещает недопустимый переход статуса."""

        # Завершённый заказ.
        self.order.status = Order.Status.COMPLETED
        self.order.save(update_fields=["status"])

        url = reverse(
            "admin:orders_order_change",
            args=[self.order.pk],
        )

        data = {
            "status": Order.Status.NEW,
            "delivery_address": "",
            "delivery_address_text": "",
            "_save": "Save",
            "items-TOTAL_FORMS": "0",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, data)

        # Форма должна показать ошибку, а не перенаправление.
        self.assertEqual(response.status_code, 200)

        # Статус в базе должен остаться прежним.
        self.order.refresh_from_db()
        self.assertEqual(
            self.order.status,
            Order.Status.COMPLETED,
        )

        # Письмо не должно отправляться.
        self.assertEqual(len(mail.outbox), 0)

    def test_admin_rejection_restores_stock(self):
        """Отклонение заказа через админку возвращает остатки."""

        # Создаём категорию и товар.
        category = Category.objects.create(
            name="Категория для проверки админки"
        )

        product = Product.objects.create(
            category=category,
            name="Товар для возврата",
        )

        # Изначально на складе уже осталось 8 штук
        # после оформления заказа на 2 штуки.
        offer = SupplierProduct.objects.create(
            supplier=self.supplier,
            product=product,
            supplier_article="ADMIN-RETURN-001",
            price="100.00",
            quantity=8,
            is_available=True,
        )

        OrderItem.objects.create(
            order=self.order,
            supplier_product=offer,
            product=product,
            product_name=product.name,
            unit="шт.",
            quantity=2,
            price="100.00",
        )

        url = reverse(
            "admin:orders_order_change",
            args=[self.order.pk],
        )

        # Отклоняем заказ через административную панель.
        data = {
            "status": Order.Status.REJECTED,
            "delivery_address": "",
            "delivery_address_text": "",
            "_save": "Save",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "1",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-id": str(self.order.items.first().pk),
            "items-0-order": str(self.order.pk),
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, data)

        self.assertEqual(response.status_code, 302)

        self.order.refresh_from_db()
        offer.refresh_from_db()

        # Заказ отклонён.
        self.assertEqual(
            self.order.status,
            Order.Status.REJECTED,
        )

        # Остаток восстановился с 8 до 10.
        self.assertEqual(offer.quantity, 10)