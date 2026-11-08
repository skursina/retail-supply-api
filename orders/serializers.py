from rest_framework import serializers

from .models import Address, Cart, CartItem, Order, OrderItem
from products.models import SupplierProduct


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = [
            "id", "title", "city", "street", "house",
            "building", "apartment", "postal_code",
            "is_default", "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data):
        validated_data["buyer"] = self.context["request"].user
        # Если адрес помечен дефолтным — снимаем флаг с остальных
        if validated_data.get("is_default"):
            Address.objects.filter(
                buyer=validated_data["buyer"], is_default=True
            ).update(is_default=False)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if validated_data.get("is_default") and not instance.is_default:
            Address.objects.filter(
                buyer=instance.buyer, is_default=True
            ).update(is_default=False)
        return super().update(instance, validated_data)


class CartItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="supplier_product.product.name", read_only=True
    )
    supplier_name = serializers.CharField(
        source="supplier_product.supplier.company_name", read_only=True
    )
    price = serializers.DecimalField(
        source="supplier_product.price",
        max_digits=12, decimal_places=2, read_only=True,
    )
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = [
            "id", "supplier_product", "product_name",
            "supplier_name", "price", "quantity", "line_total",
        ]
        read_only_fields = ["id", "price", "product_name", "supplier_name", "line_total"]

    def get_line_total(self, obj):
        return obj.supplier_product.price * obj.quantity

    def validate(self, attrs):
        sp = attrs.get("supplier_product") or (
            self.instance.supplier_product if self.instance else None
        )
        qty = attrs.get("quantity", self.instance.quantity if self.instance else 1)
        if sp and not sp.is_available:
            raise serializers.ValidationError(
                "Товар недоступен для заказа у этого поставщика."
            )
        if sp and qty > sp.quantity:
            raise serializers.ValidationError(
                f"На складе только {sp.quantity} шт."
            )
        return attrs


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ["id", "is_active", "created_at", "updated_at", "items", "total"]

    def get_total(self, obj):
        return sum(
            (item.supplier_product.price * item.quantity for item in obj.items.all()),
            0,
        )


class OrderConfirmSerializer(serializers.Serializer):
    address_id = serializers.IntegerField()

    def validate_address_id(self, value):
        user = self.context["request"].user
        if not Address.objects.filter(pk=value, buyer=user).exists():
            raise serializers.ValidationError(
                "Адрес не найден или принадлежит другому пользователю."
            )
        return value


class OrderItemSerializer(serializers.ModelSerializer):
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id", "product", "product_name", "unit",
            "quantity", "price", "line_total",
        ]
        read_only_fields = fields

    def get_line_total(self, obj):
        return obj.price * obj.quantity


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(
        source="supplier.company_name", read_only=True
    )
    delivery_address = AddressSerializer(read_only=True)

    class Meta:
        model = Order
        fields = [
            "id", "number", "status", "supplier", "supplier_name",
            "total_amount", "delivery_address", "created_at", "items",
        ]
        read_only_fields = fields