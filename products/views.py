import logging
from kombu.exceptions import OperationalError
from uuid import UUID

from django.contrib.auth import get_user_model
from django.conf import settings
from rest_framework import generics, permissions, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView

from celery.result import AsyncResult

from .models import (
    Category, 
    Product, 
    SupplierProfile,
    ProductImportJob,
)
from .serializers import CategorySerializer, ProductSerializer, SupplierOrderSettingsSerializer
from .serializers_import import ProductImportSerializer
from .tasks import import_products_task


logger = logging.getLogger(__name__)


class CategoryListView(generics.ListAPIView):
    """Список категорий товаров."""
    
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [AllowAny]


class ProductListView(generics.ListAPIView):
    """Список активных товаров каталога"""

    queryset = (
        Product.objects
        .filter(is_active=True)
        .select_related("category")
        .prefetch_related(
            "parameter_value__parameter",
            "supplier_offers__supplier",
        )
    )
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]


class ProductDetailView(generics.RetrieveAPIView):
    """Подробно о товаре."""

    queryset = (
        Product.objects
        .filter(is_active=True)
        .select_related("category")
        .prefetch_related(
            "parameter_value__parameter",
            "supplier_offers__supplier",
        )
    )
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]



class SupplierOrderSettingsView(generics.RetrieveUpdateAPIView):
    """
    Просмотр и изменение настроек приёма заказов.
    Поставщик может управлять только собственным магазином.
    """

    serializer_class = SupplierOrderSettingsSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        user = self.request.user

        # Проверяем, что пользователь является поставщиком.
        if user.role != user.Role.SUPPLIER:
            raise PermissionDenied(
                "Управление магазином доступно только поставщикам."
            )

        # Находим магазин, привязанный к текущему пользователю.
        try:
            return SupplierProfile.objects.get(user=user)
        except SupplierProfile.DoesNotExist:
            raise NotFound(
                "Профиль поставщика не найден. "
                "Сначала необходимо создать профиль магазина."
            )


class ProductImportView(APIView):
    """
    Загрузка YAML-каталога поставщика.
    Обработка выполняется через Celery.
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        User = get_user_model()

        if request.user.role != User.Role.SUPPLIER:
            return Response(
                {"detail": "Импорт доступен только поставщикам."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ProductImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded_file = serializer.validated_data["file"]

        try:
            yaml_content = uploaded_file.read().decode("utf-8")
        except UnicodeDecodeError:
            return Response(
                {"detail": "Файл должен быть в кодировке UTF-8."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            task = import_products_task.apply_async(
                args=[yaml_content, request.user.pk],
            )

            ProductImportJob.objects.create(
                task_id=task.id,
                supplier=request.user,
            )
        except (OperationalError, ConnectionError, TimeoutError):
            logger.exception("Не удалось поставить импорт товаров в очередь")

            return Response(
                {
                    "detail": (
                        "Сервис импорта временно недоступен. "
                        "Попробуйте позже."
                    )
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "task_id": task.id,
                "status": "queued",
                "message": "Каталог поставлен в очередь на импорт.",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ProductImportStatusView(APIView):
    """
    Проверка состояния фонового импорта YAML.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        if request.user.role != request.user.Role.SUPPLIER:
            return Response(
                {"detail": "Доступно только поставщикам."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            UUID(str(task_id))
        except (ValueError, TypeError):
            return Response(
                {"detail": "Некорректный идентификатор задачи."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job = ProductImportJob.objects.filter(
            task_id=str(task_id),
            supplier=request.user,
        ).first()

        if job is None:
            return Response(
                {"detail": "Задача импорта не найдена."},
                status=status.HTTP_404_NOT_FOUND,
            )

        task = AsyncResult(job.task_id)

        response_data = {
            "task_id": str(task_id),
            "status": task.status,
        }

        if task.successful():
            response_data["result"] = task.result

        elif task.failed():
            response_data["error"] = "Импорт завершился ошибкой."

        return Response(response_data)
