from django.db import transaction

from rest_framework import generics, status
from rest_framework.views import APIView, Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError

from .models import (
    Address, 
    Cart, CartItem, 
    Order, OrderItem
    )
from .serializers import (
    AddressSerializer, 
    CartSerializer, CartItemSerializer,
    OrderSerializer, OrderConfirmSerializer
    )
from .emails import (
    send_order_confirmation_to_buyer,
    send_order_invoice_to_supplier,
)


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


class OrderConfirmView(APIView):
    """Подтверждение заказа: разбивает корзину по поставщикам."""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = OrderConfirmSerializer(
            data=request.data, context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        address = Address.objects.get(pk=serializer.validated_data["address_id"])

        if not request.user.email:
            return Response(
                {"error": "Укажите email в профиле, чтобы получить подтверждение"},
                status=400,
            )

        cart = (
            Cart.objects
            .filter(buyer=request.user, is_active=True)
            .prefetch_related(
                "items__supplier_product__product",
                "items__supplier_product__supplier",
            )
            .first()
        )
        if not cart or not cart.items.exists():
            return Response(
                {"error": "Корзина пуста"},
                status=status.HTTP_400_BAD_REQUEST,
            )
                
        # Валидация и группировка по поставщикам
        grouped: dict = {}
        for item in cart.items.select_related(
            "supplier_product__supplier",
            "supplier_product__product",
        ):
            sp = item.supplier_product
            if not sp.is_available:
                return Response(
                    {"error": f"Товар «{sp.product.name}» недоступен"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if item.quantity > sp.quantity:
                return Response(
                    {"error": (
                        f"«{sp.product.name}»: на складе только "
                        f"{sp.quantity} шт., в корзине {item.quantity}"
                    )},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            grouped.setdefault(sp.supplier, []).append(item)

        created_orders = []
        for supplier, items in grouped.items():
            order = Order.objects.create(
                buyer=request.user,
                supplier=supplier,
                status=Order.Status.NEW,
                delivery_address=address,
            )
            total = 0
            for item in items:
                sp = item.supplier_product
                OrderItem.objects.create(
                    order=order,
                    supplier_product=sp,
                    product=sp.product,
                    product_name=sp.product.name,
                    unit=sp.product.unit,
                    quantity=item.quantity,
                    price=sp.price,
                )
                total += sp.price * item.quantity
                # Списание остатка
                sp.quantity -= item.quantity
                sp.is_available = sp.quantity > 0
                sp.save(update_fields=["quantity", "is_available"])

            order.total_amount = total
            order.save(update_fields=["total_amount"])
            
            send_order_confirmation_to_buyer(order)
            send_order_invoice_to_supplier(order)
            
            created_orders.append(order)

        # Закрываем корзину
        cart.items.all().delete()
        cart.is_active = False
        cart.save(update_fields=["is_active"])

        return Response(
            OrderSerializer(created_orders, many=True).data,
            status=status.HTTP_201_CREATED,
        )    