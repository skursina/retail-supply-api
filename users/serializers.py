
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

from products.models import SupplierProfile
from .models import User


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        validators=[validate_password],
    )
    company_name = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=255,
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "password",
            "first_name",
            "last_name",
            "role",
            "company_name",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        role = attrs.get("role", User.Role.BUYER)
        company_name = attrs.get("company_name")

        if role == User.Role.SUPPLIER and not company_name:
            raise serializers.ValidationError({
                "company_name": "Укажите название компании поставщика."
            })

        if role == User.Role.BUYER and company_name:
            raise serializers.ValidationError({
                "company_name": "Покупателю не нужно указывать компанию."
            })

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        company_name = validated_data.pop("company_name", None)

        user = User.objects.create_user(**validated_data)

        if user.role == User.Role.SUPPLIER:
            SupplierProfile.objects.create(
                user=user,
                company_name=company_name,
            )

        return user


class UserLoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
        ]
        read_only_fields = fields
        