from rest_framework.exceptions import ValidationError

from .models import Address, Cart, CartItem
from .serializers import AddressSerializer, CartSerializer, CartItemSerializer


class AddressListCreateView(generics.ListCreateAPIView):
    """Список и создание адресов покупателя."""
    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Address.objects.filter(buyer=self.request.user)


class AddressDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Просмотр, изменение и удаление адреса."""
    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Address.objects.filter(buyer=self.request.user)


def get_active_cart(user) -> Cart:
    """Возвращает активную корзину пользователя, создаёт при отсутствии."""
    cart, _ = Cart.objects.get_or_create(buyer=user, is_active=True)
    return cart


class CartView(generics.RetrieveAPIView):
    """Текущая активная корзина покупателя."""
    serializer_class = CartSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return get_active_cart(self.request.user)


class CartItemCreateView(generics.CreateAPIView):
    """Добавить позицию в корзину (или увеличить количество)."""
    serializer_class = CartItemSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cart = get_active_cart(request.user)
        sp = serializer.validated_data["supplier_product"]
        qty = serializer.validated_data.get("quantity", 1)

        item, created = CartItem.objects.get_or_create(
            cart=cart, supplier_product=sp,
            defaults={"quantity": qty},
        )
        if not created:
            new_qty = item.quantity + qty
            if new_qty > sp.quantity:
                raise ValidationError(
                    {"quantity": f"На складе только {sp.quantity} шт."}
                )
            item.quantity = new_qty
            item.save(update_fields=["quantity"])

        out = CartItemSerializer(item, context=self.get_serializer_context())
        return Response(out.data, status=201 if created else 200)


class CartItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Изменить количество или удалить позицию."""
    serializer_class = CartItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CartItem.objects.filter(
            cart__buyer=self.request.user, cart__is_active=True
        ).select_related("supplier_product__product", "supplier_product__supplier")