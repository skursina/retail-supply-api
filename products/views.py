from rest_framework import generics
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import PermissionDenied, NotFound

from .models import Category, Product, SupplierProfile
from .serializers import CategorySerializer, ProductSerializer, SupplierOrderSettingsSerializer


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