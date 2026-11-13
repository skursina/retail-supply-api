from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.db import IntegrityError
from rest_framework import status
from rest_framework.test import APITestCase

from unittest.mock import patch


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

        from products.models import SupplierProfile

        self.assertFalse(
            SupplierProfile.objects.filter(user=user).exists()
        )

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
                    "company_name": "Тестовая компания",
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = get_user_model().objects.get(username="test_supplier")

        self.assertEqual(user.role, "supplier")
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)

        from products.models import SupplierProfile

        profile = SupplierProfile.objects.get(user=user)

        self.assertEqual(
            profile.company_name,
            "Тестовая компания",
        )
        self.assertTrue(profile.is_accepting_orders)

    def test_supplier_registration_requires_company_name(self):
        response = self.client.post(
            "/api/users/register/",
            {
                "username": "supplier_without_company",
                "email": "no_company@example.com",
                "password": "StrongPassword2026!",
                "role": "supplier",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("company_name", response.data)
        self.assertFalse(
            get_user_model().objects.filter(
                username="supplier_without_company"
            ).exists()
        )

    def test_supplier_registration_rolls_back_on_profile_error(self):
        with patch(
            "users.serializers.SupplierProfile.objects.create",
            side_effect=IntegrityError("Profile creation failed"),
        ):
            with self.assertRaises(IntegrityError):
                self.client.post(
                    "/api/users/register/",
                    {
                        "username": "rollback_supplier",
                        "email": "rollback@example.com",
                        "password": "StrongPassword2026!",
                        "role": "supplier",
                        "company_name": "Rollback Company",
                    },
                    format="json",
                )

        self.assertFalse(
            get_user_model().objects.filter(
                username="rollback_supplier"
            ).exists()
        )

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


    def test_password_reset_email(self):
        """Активный пользователь может запросить сброс пароля."""

        User = get_user_model()

        User.objects.create_user(
            username="reset_test_user",
            email="reset_test@example.com",
            password="OldStrongPassword2026!",
            is_active=True,
        )

        response = self.client.post(
            "/api/auth/users/reset_password/",
            {"email": "reset_test@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("reset_test@example.com", mail.outbox[0].to)


    def test_password_reset_confirmation(self):
        """Пользователь может восстановить пароль через API."""
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        User = get_user_model()

        user = User.objects.create_user(
            username="password_reset_user",
            email="password_reset@example.com",
            password="OldStrongPassword2026!",
            is_active=True,
        )

        # 1. Запрашиваем письмо восстановления
        response = self.client.post(
            "/api/auth/users/reset_password/",
            {"email": user.email},
            format="json",
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(len(mail.outbox), 1)

        # 2. Генерируем токен для тестового пользователя
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        # 3. Устанавливаем новый пароль
        response = self.client.post(
            "/api/auth/users/reset_password_confirm/",
            {
                "uid": uid,
                "token": token,
                "new_password": "NewStrongPassword2026!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 204)

        # 4. Проверяем изменение пароля в базе
        user.refresh_from_db()
        self.assertTrue(
            user.check_password("NewStrongPassword2026!")
        )
        self.assertFalse(
            user.check_password("OldStrongPassword2026!")
        )

        # 5. Старый пароль больше не работает
        old_login = self.client.post(
            "/api/users/login/",
            {
                "username": user.username,
                "password": "OldStrongPassword2026!",
            },
            format="json",
        )
        self.assertEqual(old_login.status_code, 400)

        # 6. Новый пароль работает
        new_login = self.client.post(
            "/api/users/login/",
            {
                "username": user.username,
                "password": "NewStrongPassword2026!",
            },
            format="json",
        )

        self.assertEqual(new_login.status_code, 200)
        self.assertIn("token", new_login.data)