
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
from products.services import import_products_data


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
                stats = import_products_data(data, user)
            except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
                raise CommandError(f"Ошибка данных в {path}: {exc}") from exc
            self.stdout.write(self.style.SUCCESS(
                f"{path}: магазин «{stats['shop']}», "
                f"новых предложений: {stats['created']}, "
                f"обновлено: {stats['updated']}"
            ))
