from django.conf import settings
from rest_framework import serializers


class ProductImportSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, file):
        if file.size == 0:
            raise serializers.ValidationError(
                "Файл пустой."
            )

        if file.size > settings.PRODUCT_IMPORT_MAX_FILE_SIZE:
            raise serializers.ValidationError(
                "Максимальный размер файла — 2 МБ."
            )

        if not file.name.lower().endswith((".yaml", ".yml")):
            raise serializers.ValidationError(
                "Допустимы только YAML-файлы."
            )

        return file