from decimal import Decimal

from django.core import mail
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
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