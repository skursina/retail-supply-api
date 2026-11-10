import yaml

from celery import shared_task
from django.contrib.auth import get_user_model

from products.services import import_products_data


@shared_task(name="products.import_products")
def import_products_task(yaml_content, supplier_id):
    """
    Импорт каталога поставщика в фоновом режиме.

    yaml_content — содержимое YAML-файла.
    supplier_id — ID пользователя-поставщика.
    """
    data = yaml.safe_load(yaml_content)

    User = get_user_model()
    user = User.objects.get(pk=supplier_id)

    if user.role != User.Role.SUPPLIER:
        raise ValueError("Пользователь должен иметь роль supplier")

    return import_products_data(data, user)