from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
)
class UserRegistrationTests(APITestCase):
    """Тесты регистрации и подтверждения email."""

    def test_buyer_registration(self):
        """Покупатель регистрируется, но не активируется сразу."""
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/users/register/",
                {
                    "username": "test_buyer",
                    "email": "buyer@example.com",
                    "password": "StrongPassword2026!",
                    "role": "buyer",
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = get_user_model().objects.get(username="test_buyer")

        self.assertEqual(user.role, "buyer")
        self.assertFalse(user.is_active)
        self.assertTrue(user.check_password("StrongPassword2026!"))
        self.assertEqual(len(mail.outbox), 1)

    def test_supplier_registration(self):
        """Поставщик может выбрать свою роль при регистрации."""
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/users/register/",
                {
                    "username": "test_supplier",
                    "email": "supplier@example.com",
                    "password": "StrongPassword2026!",
                    "role": "supplier",
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = get_user_model().objects.get(username="test_supplier")

        self.assertEqual(user.role, "supplier")
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)

    def test_inactive_user_cannot_login(self):
        """До подтверждения email авторизация запрещена."""
        get_user_model().objects.create_user(
            username="inactive_user",
            email="inactive@example.com",
            password="StrongPassword2026!",
            is_active=False,
        )

        response = self.client.post(
            "/api/users/login/",
            {
                "username": "inactive_user",
                "password": "StrongPassword2026!",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertNotIn("token", response.data)

    def test_activation_and_login(self):
        """После активации пользователь может авторизоваться."""
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        from django.contrib.auth.tokens import default_token_generator

        # 1. Регистрируем пользователя
        with self.captureOnCommitCallbacks(execute=True):
            register_response = self.client.post(
                "/api/users/register/",
                {
                    "username": "activation_buyer",
                    "email": "activation@example.com",
                    "password": "StrongPassword2026!",
                    "role": "buyer",
                },
                format="json",
            )

        self.assertEqual(register_response.status_code, 201)

        user = get_user_model().objects.get(
            username="activation_buyer"
        )
        self.assertFalse(user.is_active)

        # 2. Проверяем, что до активации вход запрещён
        login_data = {
            "username": "activation_buyer",
            "password": "StrongPassword2026!",
        }

        before_activation = self.client.post(
            "/api/users/login/",
            login_data,
            format="json",
        )
        self.assertEqual(before_activation.status_code, 400)

        # 3. Генерируем данные активации
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        # 4. Активируем аккаунт через Djoser
        activation_response = self.client.post(
            "/api/auth/users/activation/",
            {"uid": uid, "token": token},
            format="json",
        )
        self.assertEqual(activation_response.status_code, 204)

        user.refresh_from_db()
        self.assertTrue(user.is_active)

        # 5. Авторизуемся после активации
        after_activation = self.client.post(
            "/api/users/login/",
            login_data,
            format="json",
        )

        self.assertEqual(after_activation.status_code, 200)
        self.assertIn("token", after_activation.data)
        self.assertEqual(after_activation.data["role"], "buyer")        