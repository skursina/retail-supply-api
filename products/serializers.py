from rest_framework import serializers

from .models import (
    Category,
    Product,
    ProductParameter,
    ProductParameterValue,
    SupplierProfile,
    SupplierProduct,
)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "description", "parent"]


class ProductParameterValueSerializer(serializers.ModelSerializer):
    parameter_name = serializers.CharField(
        source="parameter.name",
        read_only=True,
    )

    class Meta:
        model = ProductParameterValue
        fields = ["id", "parameter", "parameter_name", "value"]


class SupplierProductSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(
        source="supplier.company_name",
        read_only=True,
    )

    class Meta:
        model = SupplierProduct
        fields = [
            "id",
            "supplier",
            "supplier_name",
            "supplier_article",
            "price",
            "quantity",
            "is_available",
            "updated_at",
        ]


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
    )
    parameter_value = ProductParameterValueSerializer(
        many=True,
        read_only=True,
    )
    supplier_offers = SupplierProductSerializer(
        many=True,
        read_only=True,
    )

    class Meta:
        model = Product
        fields = [
            "id",
            "category",
            "category_name",
            "name",
            "description",
            "unit",
            "image",
            "is_active",
            "parameter_value",
            "supplier_offers",
        ]


class SupplierOrderSettingsSerializer(serializers.ModelSerializer):
    """Настройки приёма заказов поставщиком."""

    class Meta:
        model = SupplierProfile
        fields = ["id", "company_name", "is_accepting_orders"]
        read_only_fields = ["id", "company_name"]
        