import os
from dotenv import load_dotenv
from enum import Enum

load_dotenv()


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
                              'postgresql://postgres:marslon@localhost:5432/qarticle?client_encoding=utf8'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'

    POSTS_PER_PAGE = 20
    COMMENTS_PER_PAGE = 50

    REDIS_ENABLED = os.environ.get('REDIS_ENABLED', 'true').lower() == 'true'
    REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
    REDIS_DB = int(os.environ.get('REDIS_DB', 0))
    REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', None)
    REDIS_SOCKET_TIMEOUT = int(os.environ.get('REDIS_SOCKET_TIMEOUT', 2))

    RATING_CACHE_TTL = 3600
    VIEWS_CACHE_TTL = 86400
    POPULAR_CACHE_TTL = 300
    FEED_CACHE_TTL = 180
    POST_DETAIL_CACHE_TTL = 600
    COMMENTS_CACHE_TTL = 300
    USER_PROFILE_CACHE_TTL = 600
    SEARCH_CACHE_TTL = 120
    TOP_WEEK_CACHE_TTL = 1800


class EmailProvider(Enum):
    GMAIL = "gmail"
    YANDEX = "yandex"
    MAIL_RU = "mailru"
    OUTLOOK = "outlook"
    RAMBLER = "rambler"
    YAHOO = "yahoo"
    CUSTOM = "custom"


class SMTPConfig:

    PROVIDERS = {
        EmailProvider.GMAIL: {
            'server': 'smtp.gmail.com',
            'port': 587,
            'use_tls': True,
            'use_ssl': False,
            'auth_required': True
        },
        EmailProvider.YANDEX: {
            'server': 'smtp.yandex.ru',
            'port': 465,
            'use_tls': False,
            'use_ssl': True,
            'auth_required': True
        },
        EmailProvider.MAIL_RU: {
            'server': 'smtp.mail.ru',
            'port': 465,
            'use_tls': False,
            'use_ssl': True,
            'auth_required': True
        },
        EmailProvider.OUTLOOK: {
            'server': 'smtp-mail.outlook.com',
            'port': 587,
            'use_tls': True,
            'use_ssl': False,
            'auth_required': True
        },
        EmailProvider.RAMBLER: {
            'server': 'smtp.rambler.ru',
            'port': 465,
            'use_tls': False,
            'use_ssl': True,
            'auth_required': True
        },
        EmailProvider.YAHOO: {
            'server': 'smtp.mail.yahoo.com',
            'port': 587,
            'use_tls': True,
            'use_ssl': False,
            'auth_required': True
        }
    }

    @classmethod
    def get_config(cls, provider=None):
        if provider and provider in cls.PROVIDERS:
            return cls.PROVIDERS[provider].copy()

        return {
            'server': os.environ.get('SMTP_SERVER', 'smtp.mail.ru'),
            'port': int(os.environ.get('SMTP_PORT', 465)),
            'use_tls': os.environ.get('SMTP_USE_TLS', 'false').lower() == 'true',
            'use_ssl': os.environ.get('SMTP_USE_SSL', 'true').lower() == 'true',
            'auth_required': True
        }

