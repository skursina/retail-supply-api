import os

from celery import Celery

# Указываем файл настроек Django.
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

# Создаём приложение Celery.
app = Celery("retail_supply")

# Загружаем настройки Celery из settings.py.
# Все настройки должны начинаться с CELERY_.
app.config_from_object(
    "django.conf:settings",
    namespace="CELERY",
)

# Автоматически ищем tasks.py в приложениях Django.
app.autodiscover_tasks()