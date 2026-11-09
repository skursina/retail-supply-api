
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from products.models import (
    Category, Product, ProductParameter, ProductParameterValue,
    SupplierProfile, SupplierProduct,
)


class Command(BaseCommand):
    help = "Импорт YAML-каталога для существующего пользователя-поставщика"

    def add_arguments(self, parser):
        parser.add_argument("files", nargs="+", help="Пути к YAML-файлам")
        parser.add_argument(
            "--supplier", required=True, metavar="USERNAME",
            help="Логин существующего пользователя с ролью supplier",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        try:
            user = User.objects.get(username=options["supplier"])
        except User.DoesNotExist as exc:
            raise CommandError("Пользователь-поставщик не найден") from exc
        if user.role != user.Role.SUPPLIER:
            raise CommandError("Пользователь должен иметь роль supplier")

        for filename in options["files"]:
            path = Path(filename)
            if not path.is_file():
                raise CommandError(f"Файл не найден: {path}")
            try:
                with path.open(encoding="utf-8") as stream:
                    data = yaml.safe_load(stream)
            except (OSError, yaml.YAMLError) as exc:
                raise CommandError(f"Не удалось прочитать {path}: {exc}") from exc
            try:
                stats = self.import_data(data, user)
            except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
                raise CommandError(f"Ошибка данных в {path}: {exc}") from exc
            self.stdout.write(self.style.SUCCESS(
                f"{path}: магазин «{stats['shop']}», "
                f"новых предложений: {stats['created']}, "
                f"обновлено: {stats['updated']}"
            ))

    @transaction.atomic
    def import_data(self, data, user):
        if not isinstance(data, dict):
            raise ValueError("Корень YAML должен быть словарём")
        shop = str(data.get("shop") or "").strip()
        if not shop:
            raise ValueError("Обязательное поле shop отсутствует")
        categories_data = data.get("categories", [])
        goods = data.get("goods", [])
        if not isinstance(categories_data, list) or not isinstance(goods, list):
            raise ValueError("categories и goods должны быть списками")

        # Один профиль на пользователя: существующий профиль нельзя молча
        # переименовывать из-за случайно выбранного YAML-файла.
        supplier, created_profile = SupplierProfile.objects.get_or_create(
            user=user, defaults={"company_name": shop}
        )
        if not created_profile and supplier.company_name != shop:
            raise ValueError(
                f"Профиль пользователя называется «{supplier.company_name}», "
                f"а в YAML указан «{shop}»"
            )

        # Сначала создаём все категории, затем связываем родителей.
        category_map = {}
        for item in categories_data:
            if not isinstance(item, dict) or "id" not in item or not item.get("name"):
                raise ValueError("У каждой категории должны быть id и name")
            external_id = str(item["id"])
            if external_id in category_map:
                raise ValueError(f"Повторяющийся id категории: {external_id}")
            category, _ = Category.objects.get_or_create(name=str(item["name"]))
            category_map[external_id] = category
        for item in categories_data:
            category = category_map[str(item["id"])]
            parent_id = item.get("parent")
            if parent_id is not None:
                parent = category_map.get(str(parent_id))
                if parent is None:
                    raise ValueError(f"Неизвестный parent={parent_id}")
                if parent.pk == category.pk:
                    raise ValueError("Категория не может быть родителем самой себе")
                # Проверяем и более длинные циклы, включая существующие связи.
                ancestor = parent
                visited = set()
                while ancestor is not None:
                    if ancestor.pk == category.pk or ancestor.pk in visited:
                        raise ValueError("Циклическая иерархия категорий")
                    visited.add(ancestor.pk)
                    ancestor = ancestor.parent
            else:
                parent = None
            if category.parent_id != (parent.pk if parent else None):
                category.parent = parent
                category.save(update_fields=["parent"])

        created = updated = 0
        seen_articles = set()
        for good in goods:
            if not isinstance(good, dict):
                raise ValueError("Элемент goods должен быть словарём")
            category = category_map.get(str(good.get("category")))
            if category is None:
                raise ValueError(f"Неизвестная категория: {good.get('category')}")
            name = str(good.get("name") or "").strip()
            if not name:
                raise ValueError("Товар без названия")
            article = str(good.get("id") or "").strip()
            if not article:
                raise ValueError(f"Для товара «{name}» обязателен id")
            if len(article) > 100:
                raise ValueError(f"Артикул слишком длинный: {article}")
            if article in seen_articles:
                raise ValueError(f"Дублирующийся артикул в файле: {article}")
            seen_articles.add(article)
            try:
                price = Decimal(str(good["price"]))
                quantity = int(good["quantity"])
            except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                raise ValueError(f"Некорректная цена или остаток: {name}") from exc
            if not price.is_finite() or price < 0 or price.as_tuple().exponent < -2 or price >= Decimal("10000000000"):
                raise ValueError(f"Недопустимая цена: {name}")
            if quantity < 0 or quantity > 18446744073709551615:
                raise ValueError(f"Недопустимый остаток: {name}")

            # При повторном импорте ищем предложение по артикулу поставщика.
            # При отсутствии артикула в БД используем существующий товар по
            # имени и категории (без создания дубликата).
            offers = list(SupplierProduct.objects.filter(
                supplier=supplier, supplier_article=article
            ).select_related("product"))
            if len(offers) > 1:
                raise ValueError(f"Артикул {article} неоднозначен в базе")
            offer = offers[0] if offers else None
            if offer:
                product = offer.product
                # Не меняем общую карточку товара, если она используется
                # предложениями других поставщиков.
                if product.name != name or product.category_id != category.pk:
                    raise ValueError(
                        f"Артикул {article} уже связан с другим товаром: {product.name}"
                    )
            else:
                matches = Product.objects.filter(name=name, category=category)
                if matches.count() > 1:
                    raise ValueError(f"Несколько товаров с названием «{name}»")
                product = matches.first()
                if product is None:
                    product = Product.objects.create(
                        name=name, category=category,
                        description=str(good.get("description") or ""),
                        image=str(good.get("image") or ""),
                        unit=str(good.get("unit") or "шт."),
                    )
                offer = SupplierProduct.objects.filter(
                    supplier=supplier, product=product
                ).first()
                if offer and offer.supplier_article not in ("", article):
                    raise ValueError(
                        f"Товар «{name}» уже имеет другой артикул "
                        f"({offer.supplier_article}) у поставщика"
                    )

            parameters = good.get("parameters") or {}
            if not isinstance(parameters, dict):
                raise ValueError(f"parameters должен быть словарём: {name}")
            # Параметры товара общие для всех поставщиков.
            for param_name, value in parameters.items():
                parameter, _ = ProductParameter.objects.get_or_create(
                    name=str(param_name)
                )
                parameter.categories.add(category)
                ProductParameterValue.objects.update_or_create(
                    product=product, parameter=parameter,
                    defaults={"value": str(value)},
                )

            if offer is None:
                SupplierProduct.objects.create(
                    supplier=supplier, product=product, supplier_article=article,
                    price=price, quantity=quantity, is_available=quantity > 0,
                )
                created += 1
            else:
                offer.supplier_article = article
                offer.price = price
                offer.quantity = quantity
                offer.is_available = quantity > 0
                offer.save(update_fields=[
                    "supplier_article", "price", "quantity", "is_available", "updated_at"
                ])
                updated += 1
        return {"shop": shop, "created": created, "updated": updated}
