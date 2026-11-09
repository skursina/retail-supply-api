from django.db import transaction
from djoser.conf import settings as djoser_settings
from django.contrib.auth import authenticate, login
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated

from .serializers import (
    UserRegistrationSerializer, 
    UserLoginSerializer,
    UserProfileSerializer,
    )


class UserRegistrationView(generics.CreateAPIView):
    """Регистрация с обязательным подтверждением email."""

    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        # Создаём пользователя с выбранной ролью,
        # но запрещаем вход до подтверждения email.
        user = serializer.save(is_active=False)

        # Отправляем письмо только после успешного
        # сохранения изменений в базе данных.
        def send_activation_email():
            djoser_settings.EMAIL.activation(
                self.request,
                {"user": user},
            ).send([user.email])

        transaction.on_commit(send_activation_email)
        

class UserLoginView(generics.GenericAPIView):
    serializer_class = UserLoginSerializer
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        user = authenticate(
            request,
            username=username,
            password=password,
        )

        if user is None:
            return Response(
                {"error": "Неверный логин или пароль"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        login(request, user)

        token, created = Token.objects.get_or_create(user=user)

        return Response({
            "token": token.key,
            "user_id": user.id,
            "username": user.username,
            "role": user.role
        })


class UserProfileView(generics.RetrieveAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user