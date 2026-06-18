# QArticle — Платформа совместного обучения

##  Описание дипломного проекта
QArticle — это веб-платформа для обмена знаниями, где пользователи могут:
- Публиковать статьи и задавать вопросы
- Комментировать и голосовать за контент
- Создавать тематические сообщества
- Сохранять посты в закладки
- Получать уведомления

##  Технологии
- **Backend:** Flask 2.3.3
- **База данных:** PostgreSQL (Render) / SQLite (локально)
- **Кэширование:** Redis
- **ORM:** SQLAlchemy 2.0
- **Аутентификация:** Flask-Login
- **Фронтенд:** TailwindCSS, Font Awesome

##  Деплой
### На Render.com (production)
Приложение доступно по адресу: https://qarticle.onrender.com

### Локальный запуск
```bash
# Клонировать репозиторий
git clone https://github.com/ваш-логин/qarticle.git
cd qarticle

# Создать виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate     # Windows

# Установить зависимости
pip install -r requirements.txt

# Создать .env файл из .env.example
cp .env.example .env

# Запустить приложение
python main.py