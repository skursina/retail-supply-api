import yaml
from django.http import HttpResponse
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView

from products.models import Category, SupplierProfile, SupplierProduct


def export_products_to_yaml_data(supplier_id: int) -> dict:
    """Возвращает совместимый с import_products словарь одного поставщика."""
    supplier = SupplierProfile.objects.get(pk=supplier_id)
    offers = list(
        SupplierProduct.objects.filter(supplier=supplier)
        .select_related("product__category")
        .prefetch_related("product__parameter_value__parameter")
        .order_by("id")
    )
    categories = {}

    def include_category(category):
        if category.pk in categories:
            return
        if category.parent_id:
            include_category(Category.objects.get(pk=category.parent_id))
        categories[category.pk] = {
            "id": category.pk,
            "name": category.name,
            "parent": category.parent_id,
        }

    goods = []
    for offer in offers:
        product = offer.product
        include_category(product.category)
        # Для обратного импорта нужен стабильный артикул.
        # Если он отсутствует, используем уникальный ID предложения.
        article = offer.supplier_article or f"offer-{offer.pk}"
        goods.append({
            "id": article,
            "category": product.category_id,
            "name": product.name,
            "price": float(offer.price),
            "quantity": offer.quantity,
            "unit": product.unit,
            "description": product.description,
            "image": product.image,
            "parameters": {
                value.parameter.name: value.value
                for value in product.parameter_value.all()
            },
        })
    return {
        "shop": supplier.company_name,
        "categories": list(categories.values()),
        "goods": goods,
    }


class ExportProductsView(APIView):
    """GET /api/catalog/export/?supplier_id=1 (только администратор)."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        raw_id = request.query_params.get("supplier_id")
        if not raw_id:
            raise ValidationError({"supplier_id": "Укажите ID поставщика"})
        try:
            supplier_id = int(raw_id)
        except ValueError as exc:
            raise ValidationError({"supplier_id": "Ожидается целое число"}) from exc
        if supplier_id < 1:
            raise ValidationError({"supplier_id": "ID должен быть положительным"})
        if not SupplierProfile.objects.filter(pk=supplier_id).exists():
            raise NotFound("Поставщик не найден")
        data = export_products_to_yaml_data(supplier_id)
        body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        response = HttpResponse(body, content_type="application/x-yaml; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="supplier_{supplier_id}.yaml"'
        )
        return response
