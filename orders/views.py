from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from collections import defaultdict

from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.exceptions import ValidationError

from products.models import SupplierProduct
from .models import (
    Address, 
    Cart, CartItem, 
    Order, OrderItem
    )
from .serializers import (
    AddressSerializer, 
    CartSerializer, CartItemSerializer,
    OrderSerializer, OrderConfirmSerializer, OrderStatusSerializer
    )
from .emails import (
    send_order_notifications, 
    send_order_status_email,
)
from .services import change_order_status


class IsBuyer(BasePermission):
    message = "Доступно только покупателям."

    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and
                    request.user.role == request.user.Role.BUYER)


class AddressListCreateView(generics.ListCreateAPIView):
    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Address.objects.filter(buyer=self.request.user)


class AddressDetailView(generics.RetrieveUpdateDestroyAPIView):
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
    permission_classes = [IsAuthenticated, IsBuyer]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Сериализатор проверяет предложение, но проверяем его повторно под блокировкой.
        sp = SupplierProduct.objects.select_for_update().select_related(
            "product", "supplier"
        ).get(pk=serializer.validated_data["supplier_product"].pk)

        qty = serializer.validated_data.get("quantity", 1)
        if not (sp.is_available and sp.product.is_active and sp.supplier.is_accepting_orders):
            raise ValidationError({"supplier_product": "Предложение недоступно"})
        
        cart = get_active_cart(request.user)
        item, created = CartItem.objects.get_or_create(
            cart=cart, supplier_product=sp, defaults={"quantity": qty}
        )

        new_qty = qty if created else item.quantity + qty
        if new_qty > sp.quantity:
            raise ValidationError({"quantity": f"На складе только {sp.quantity} шт."})
        if not created:
            item.quantity = new_qty
            item.save(update_fields=["quantity"])

        return Response(
            CartItemSerializer(item, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class CartItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Изменить количество или удалить позицию."""
    serializer_class = CartItemSerializer
    permission_classes = [IsAuthenticated, IsBuyer]

    def get_queryset(self):
        return CartItem.objects.filter(
            cart__buyer=self.request.user, cart__is_active=True
        ).select_related("supplier_product__product", "supplier_product__supplier")


class OrderConfirmView(APIView):
    """Подтверждение заказа: разбивает корзину по поставщикам."""
    permission_classes = [IsAuthenticated, IsBuyer]

    @transaction.atomic
    def post(self, request):
        serializer = OrderConfirmSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        address = Address.objects.get(
            pk=serializer.validated_data["address_id"], buyer=request.user
        )
        if not request.user.email:
            raise ValidationError({"email": "Укажите email в профиле"})

        # Блокируем корзину, чтобы два подтверждения не создали два набора заказов.
        cart = Cart.objects.select_for_update().filter(
            buyer=request.user, is_active=True
        ).first()
        if cart is None:
            raise ValidationError({"cart": "Корзина пуста"})
        cart_items = list(CartItem.objects.filter(cart=cart).order_by("id"))
        if not cart_items:
            raise ValidationError({"cart": "Корзина пуста"})

        # Блокировки предложений в едином порядке уменьшают риск взаимных блокировок.
        offer_ids = sorted({item.supplier_product_id for item in cart_items})
        offers = {
            sp.pk: sp for sp in SupplierProduct.objects.select_for_update()
            .select_related("product", "supplier")
            .filter(pk__in=offer_ids).order_by("pk")
        }
        grouped = defaultdict(list)
        for item in cart_items:
            sp = offers.get(item.supplier_product_id)
            if sp is None or not (sp.is_available and sp.product.is_active
                                  and sp.supplier.is_accepting_orders):
                raise ValidationError({"cart": "Один из товаров недоступен для заказа"})
            if item.quantity > sp.quantity:
                raise ValidationError({
                    "quantity": f"«{sp.product.name}»: на складе {sp.quantity} шт."
                })
            grouped[sp.supplier_id].append((item, sp))

        created_orders = []
        for supplier_id, items in grouped.items():
            order = Order.objects.create(
                buyer=request.user, supplier_id=supplier_id,
                delivery_address=address, delivery_address_text=str(address),
                status=Order.Status.NEW,
            )
            total = 0
            for item, sp in items:
                OrderItem.objects.create(
                    order=order, supplier_product=sp, product=sp.product,
                    product_name=sp.product.name, unit=sp.product.unit,
                    quantity=item.quantity, price=sp.price,
                )
                total += sp.price * item.quantity
                sp.quantity -= item.quantity
                sp.is_available = sp.quantity > 0
                sp.save(update_fields=["quantity", "is_available"])

            order.total_amount = total
            order.save(update_fields=["total_amount"])
            created_orders.append(order)

        CartItem.objects.filter(cart=cart).delete()
        cart.is_active = False
        cart.save(update_fields=["is_active"])

        for order in created_orders:
            transaction.on_commit(lambda order_id=order.pk: send_order_notifications(order_id))
        
        return Response(
            OrderSerializer(created_orders, many=True).data,
            status=status.HTTP_201_CREATED,
        )    


class IsSupplierOfOrderOrAdmin(BasePermission):
    """Статус может менять поставщик заказа или админ."""

    def has_object_permission(self, request, view, obj):
        return bool(request.user.is_staff or (
            request.user.role == request.user.Role.SUPPLIER
            and obj.supplier.user_id == request.user.pk
        ))


def visible_orders(user):
    qs = Order.objects.select_related(
        "supplier", "delivery_address", "buyer"
    ).prefetch_related("items")

    if user.is_staff:
        return qs
    
    if user.role == user.Role.SUPPLIER:
        return qs.filter(supplier__user=user)
    
    return qs.filter(buyer=user)


class OrderListView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return visible_orders(self.request.user)


class OrderDetailView(generics.RetrieveAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return visible_orders(self.request.user)


class OrderStatusUpdateView(generics.UpdateAPIView):
    """Изменение статуса заказа через общий сервис."""

    serializer_class = OrderStatusSerializer
    permission_classes = [
        IsAuthenticated,
        IsSupplierOfOrderOrAdmin,
    ]
    http_method_names = ["patch", "put"]

    def get_queryset(self):
        return Order.objects.select_related("supplier")

    def update(self, request, *args, **kwargs):
        # Проверяем существование заказа и права пользователя.
        order = self.get_object()

        # Проверяем входные данные через DRF.
        serializer = self.get_serializer(
            order,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data.get(
            "status",
            order.status,
        )

        try:
            # Общий сервис выполняет изменение статуса,
            # возврат остатков и отправку уведомления.
            order = change_order_status(
                order.id,
                new_status,
            )

        except DjangoValidationError as exc:
            # Преобразуем ошибку Django в HTTP 400.
            raise ValidationError(
                exc.messages
            ) from exc

        return Response(
            self.get_serializer(order).data
        )