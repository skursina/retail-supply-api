import yaml
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from products.models import (
    Category,
    Product,
    ProductParameter,
    ProductParameterValue,
    SupplierProfile,
    SupplierProduct,
)


class Command(BaseCommand):
    help = "Импорт товаров из YAML-файлов"

    def add_arguments(self, parser):
        parser.add_argument(
            "files",
            nargs="+",
            type=str,
            help="Пути к YAML-файлам для импорта",
        )

    def handle(self, *args, **options):
        for file_path in options["files"]:
            path = Path(file_path)
            if not path.exists():
                self.stderr.write(f"Файл не найден: {path}")
                continue
            self.stdout.write(f"Импорт из {path}...")
            stats = self.import_file(path)
            self.stdout.write(
                f"  магазин: {stats['shop']}, "
                f"создано: {stats['created']}, обновлено: {stats['updated']}"
            )
        self.stdout.write(self.style.SUCCESS("Импорт завершён"))

    @transaction.atomic
    def import_file(self, path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        shop_name = data.get("shop", "Неизвестный магазин")

        # 1. Поставщик
        supplier, _ = SupplierProfile.objects.get_or_create(
            company_name=shop_name,
            defaults={"is_accepting_orders": True},
        )

        # 2. Категории (поддержка вложенности через parent)
        category_map = {}
        for cat_data in data.get("categories", []):
            parent = category_map.get(cat_data.get("parent"))
            category, _ = Category.objects.update_or_create(
                name=cat_data["name"],
                defaults={"parent": parent},
            )
            category_map[cat_data["id"]] = category

        # 3. Товары
        created, updated = 0, 0
        for good in data.get("goods", []):
            category = category_map.get(good["category"])
            if category is None:
                self.stderr.write(
                    f"Категория {good['category']} не найдена для {good['name']}"
                )
                continue

            product, is_new = Product.objects.update_or_create(
                name=good["name"],
                category=category,
                defaults={
                    "description": good.get("description", ""),
                    "image": good.get("image", ""),
                    "is_active": True,
                },
            )
            if is_new:
                created += 1
            else:
                updated += 1

            # 4. Характеристики
            for param_name, param_value in (good.get("parameters") or {}).items():
                parameter, _ = ProductParameter.objects.get_or_create(
                    name=param_name,
                )
                parameter.categories.add(category)
                ProductParameterValue.objects.update_or_create(
                    product=product,
                    parameter=parameter,
                    defaults={"value": str(param_value)},
                )

            # 5. Предложение поставщика
            SupplierProduct.objects.update_or_create(
                supplier=supplier,
                product=product,
                defaults={
                    "supplier_article": str(good.get("id", good.get("model", ""))),
                    "price": good["price"],
                    "quantity": good.get("quantity", 0),
                    "is_available": good.get("quantity", 0) > 0,
                },
            )

        return {"shop": shop_name, "created": created, "updated": updated}