# API Documentation --- Retail Supply API

Документ основан на предоставленных `config/urls.py`, URL-файлах
приложений, сериализаторах, моделях и фрагментах представлений.

Base URL локального Docker-запуска: `http://localhost:8000`.

Для защищённых запросов передавайте `Authorization: Token <token>`. DRF
также поддерживает `SessionAuthentication`.

## 1. Пользователи и авторизация

Роли: `buyer` (покупатель) и `supplier` (поставщик).

### `POST /api/users/register/`

Регистрация. Поля сериализатора:

  Поле           Тип      Примечание
  -------------- -------- ---------------------------------
  `username`     string   Имя пользователя
  `email`        string   Email
  `password`     string   Проверяется валидаторами Django
  `first_name`   string   Необязательно
  `last_name`    string   Необязательно
  `role`         string   `buyer` или `supplier`

Пример:

``` json
{
  "username": "buyer_demo",
  "email": "buyer@example.com",
  "password": "StrongPassword2026!",
  "first_name": "Demo",
  "last_name": "Buyer",
  "role": "buyer"
}
```

В настройках Djoser включена отправка письма активации.

### `POST /api/users/login/`

Тело:

``` json
{
  "username": "buyer_demo",
  "password": "StrongPassword2026!"
}
```

При успехе ответ содержит `token`, `user_id`, `username`, `role`. При
неверных учётных данных представление возвращает HTTP 400.

### `GET /api/users/me/`

Возвращает профиль текущего пользователя: `id`, `username`, `email`,
`first_name`, `last_name`, `role`. Требуется авторизация.

### Djoser: `/api/auth/`

Корневой URL подключает `djoser.urls`. В настройках заданы шаблоны
ссылок активации `activate/{uid}/{token}` и подтверждения сброса пароля
`password/reset/confirm/{uid}/{token}`. Полный список встроенных
маршрутов и точные payload зависят от установленной версии Djoser;
проверьте их через Django URL resolver.

## 2. Каталог и поставщики

### `GET /api/catalog/categories/`

Публичный список категорий. Поля: `id`, `name`, `description`, `parent`.

### `GET /api/catalog/products/`

Публичный список активных товаров. Поля товара: `id`, `category`,
`category_name`, `name`, `description`, `unit`, `image`, `is_active`,
`parameter_value`, `supplier_offers`.

Вложенные `supplier_offers` содержат `id`, `supplier`, `supplier_name`,
`supplier_article`, `price`, `quantity`, `is_available`, `updated_at`.

### `GET /api/catalog/products/{id}`

Получение активного товара по ID. В текущем URLconf завершающий `/` не
указан.

### `GET /api/catalog/supplier/settings/`

Получение настроек собственного магазина. Требуется авторизация и роль
`supplier`. Если профиль не найден, возвращается 404.

### `PATCH /api/catalog/supplier/settings/`

Изменение настроек. Подтверждённое поле для изменения ---
`is_accepting_orders`; `id` и `company_name` только для чтения.

``` json
{
  "is_accepting_orders": false
}
```

## 3. Импорт и экспорт YAML

### `POST /api/catalog/import/`

Загрузка YAML поставщиком. Требуется авторизация и роль `supplier`.
Формат --- `multipart/form-data`, поле `file`.

Проверки файла: непустой; размер не более 2 МБ; расширение `.yaml` или
`.yml`; кодировка UTF-8.

Успешная постановка задачи возвращает HTTP 202:

``` json
{
  "task_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "queued",
  "message": "Каталог поставлен в очередь на импорт."
}
```

При недоступности брокера предусмотрен HTTP 503.

### `GET /api/catalog/import/status/{task_id}`

Проверка статуса задачи. Требуется авторизация. Поставщик может
просматривать только собственную задачу; для чужой или неизвестной
задачи используется 404. Завершающий `/` в URL pattern не указан.

### `GET /api/catalog/export/?supplier_id={id}`

Экспорт YAML. В предоставленном коде `ExportProductsView` использует
`IsAdminUser`, поэтому маршрут доступен администратору. `supplier_id`
обязателен, должен быть положительным целым числом и соответствовать
существующему профилю поставщика. Успешный ответ --- YAML-файл.

## 4. Корзина

Добавление, изменение и удаление позиции ограничены ролью `buyer`.

### `GET /api/cart/`

Получение активной корзины текущего пользователя; при отсутствии
активная корзина создаётся.

### `POST /api/cart/items/`

Добавление предложения поставщика или увеличение его количества:

``` json
{
  "supplier_product": 12,
  "quantity": 2
}
```

`quantity` по умолчанию равно 1. Недоступное предложение, неактивный
товар, закрытый для заказов поставщик и превышение остатка отклоняются.
Повторное добавление того же предложения увеличивает количество.

### `GET /api/cart/items/{id}/`

Получение позиции активной корзины текущего покупателя.

### `PATCH /api/cart/items/{id}/`

Изменение позиции. Нельзя заменить `supplier_product` у существующей
позиции: удалите её и добавьте другое предложение.

### `DELETE /api/cart/items/{id}/`

Удаление позиции активной корзины.

## 5. Адреса

Все операции требуют авторизации; queryset ограничен адресами текущего
пользователя.

### `GET /api/addresses/`

Список адресов.

### `POST /api/addresses/`

Создание адреса. Поля: `title` (необязательно), `city`, `street`,
`house`, `building` (необязательно), `apartment` (необязательно),
`postal_code` (необязательно), `is_default`.

Если адрес помечен основным, флаг снимается с остальных адресов
пользователя.

### `GET /api/addresses/{id}/`, `PATCH /api/addresses/{id}/`, `DELETE /api/addresses/{id}/`

Получение, изменение и удаление собственного адреса.

## 6. Заказы

### `POST /api/orders/confirm/`

Оформление заказа. Требуется авторизация и роль `buyer`.

``` json
{
  "address_id": 3
}
```

Адрес должен принадлежать текущему покупателю; email пользователя должен
быть указан; корзина должна быть непустой. Если в корзине товары разных
поставщиков, создаётся отдельный заказ для каждого поставщика. При
оформлении фиксируются данные позиции и цена на момент заказа,
уменьшаются остатки, позиции корзины удаляются, корзина закрывается.

### `GET /api/orders/`

Список заказов. Точные ограничения по ролям определяются
`OrderListView`.

### `GET /api/orders/{id}/`

Детали заказа. Проверка доступа определяется `OrderDetailView`.

Поля заказа: `id`, `number`, `status`, `supplier`, `supplier_name`,
`total_amount`, `delivery_address`, `delivery_address_text`,
`created_at`, `items`.

Позиция заказа: `id`, `product`, `product_name`, `unit`, `quantity`,
`price`, `line_total`.

### `PATCH /api/orders/{id}/status/`

Изменение статуса. Сериализатор разрешает переходы:

  Текущий статус   Допустимые следующие статусы
  ---------------- --------------------------------------
  `new`            `confirmed`, `rejected`, `cancelled`
  `confirmed`      `processing`, `cancelled`
  `processing`     `shipped`, `cancelled`
  `shipped`        `completed`
  `completed`      Нет
  `rejected`       Нет
  `cancelled`      Нет

Пример:

``` json
{
  "status": "confirmed"
}
```

Права на изменение конкретного заказа дополнительно определяются
представлением.

## 7. Заголовки и форматы

Защищённый запрос:

``` http
Authorization: Token <token>
```

JSON-запрос:

``` http
Content-Type: application/json
```

Для загрузки YAML используйте `multipart/form-data`; boundary должен
формировать HTTP-клиент.

## 8. HTTP-статусы

В зависимости от endpoint и результата могут использоваться: - `200 OK`
--- успешное чтение/обновление; - `201 Created` --- создание; -
`202 Accepted` --- задача импорта поставлена в очередь; -
`400 Bad Request` --- ошибка данных или неверные учётные данные; -
`403 Forbidden` --- недостаточно прав или неподходящая роль; -
`404 Not Found` --- ресурс отсутствует или недоступен; -
`503 Service Unavailable` --- брокер задач недоступен при постановке
импорта.

## 9. Что проверить перед публикацией

В предоставленных материалах не было полного актуального кода
`ProductImportStatusView`, `OrderListView`, `OrderDetailView` и
`OrderStatusUpdateView`. Поэтому точные схемы их ответов и все
ограничения доступа здесь намеренно не выдуманы. Перед публикацией
проверьте эти представления в рабочей копии.
