from .models import Address


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