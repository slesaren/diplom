from venv import logger

from flask import app
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from sqlalchemy import func, desc
from datetime import datetime, timedelta
import redis
import json
import logging
import re
import sys
import os
from flask_login import UserMixin, LoginManager, login_user, current_user, login_required, logout_user
from config import Config
from models import db, User
from redis_utils import RedisBookStats

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, UniqueConstraint, func
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

import logging
from logging.handlers import RotatingFileHandler

from emailregister import  VerificationEmailService, EmailProvider #send_verification_email
import sys
from flask import session as flask_session

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите для доступа к этой странице.'
login_manager.login_message_category = 'info'

serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
    #return User.query.get(int(user_id))


def get_email_provider():
    provider_str = os.environ.get('SMTP_PROVIDER', 'gmail').lower()
    try:
        return EmailProvider(provider_str)
    except ValueError:
        return None


email_provider = get_email_provider()
email_service = VerificationEmailService(provider=email_provider)

def send_verification_email(email, username, token):
    try:
        verification_url = url_for('verify_email', token=token, _external=True)
        success = email_service.send_verification(email, username, verification_url)
        if success:
            logger.info(
                f"Verification email sent to {email} via {email_provider.value if email_provider else 'custom'} provider")
        else:
            logger.error(f"Failed to send verification email to {email}")
        return success

    except Exception as e:
        logger.error(f"Error sending verification email: {str(e)}", exc_info=True)
        return False

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        terms = request.form.get('terms') == 'on'

        errors = []
        if not username or len(username) < 3:
            errors.append('Имя пользователя должно содержать минимум 3 символа.')
        if not re.match(r'^[a-zA-Z0-9_\-]+$', username):
            errors.append('Имя пользователя может содержать только буквы, цифры, _ и -.')
        if not email or '@' not in email:
            errors.append('Введите корректный email.')
        if not password or len(password) < 6:
            errors.append('Пароль должен быть не менее 6 символов.')
        if password != confirm:
            errors.append('Пароли не совпадают.')
        if not terms:
            errors.append('Необходимо согласиться с правилами платформы.')
        if User.query.filter_by(username=username).first():
            errors.append('Пользователь с таким именем уже существует.')
        if User.query.filter_by(email=email).first():
            errors.append('Этот email уже зарегистрирован.')

        if errors:
            for err in errors:
                flash(err, 'danger')
                logger.warning(f"Registration validation failed for {email}: {err}")
            return render_template('register.html')

        new_user = User(
            username=username,
            email=email,
            is_active=False,
            email_verified=False
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        token = serializer.dumps(email, salt='email-verification')
        email_sent = send_verification_email(email, username, token)

        if email_sent:
            flash(
                'Регистрация успешна! На ваш email отправлено письмо с подтверждением. Пожалуйста, подтвердите email, чтобы войти.',
                'info')
            logger.info(f"User registered: {username} ({email})")
        else:
            flash(
                'Регистрация успешна, но не удалось отправить письмо с подтверждением. Пожалуйста, свяжитесь с администратором.',
                'warning')
            logger.error(f"User registered but email not sent: {username} ({email})")

        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/verify_email/<token>')
def verify_email(token):
    try:
        email = serializer.loads(token, salt='email-verification', max_age=86400)  # 24 часа
        user = User.query.filter_by(email=email).first()

        if user:
            if user.email_verified:
                flash('Email уже был подтвержден. Вы можете войти в систему.', 'info')
            else:
                user.email_verified = True
                user.is_active = True
                db.session.commit()
                flash('Email успешно подтвержден! Теперь вы можете войти в систему.', 'success')
                logger.info(f"Email verified for user: {user.username} ({email})")
        else:
            flash('Пользователь не найден.', 'danger')

    except SignatureExpired:
        flash('Ссылка для подтверждения истекла (действительна 24 часа). Пожалуйста, запросите новое письмо.',
              'warning')
    except BadSignature:
        flash('Недействительная ссылка подтверждения.', 'danger')

    return redirect(url_for('login'))


@app.route('/resend_verification', methods=['POST'])
def resend_verification():
    email = request.form.get('email')
    user = User.query.filter_by(email=email).first()

    if user and not user.email_verified:
        token = serializer.dumps(email, salt='email-verification')
        send_verification_email(email, user.username, token)
        flash('Новое письмо с подтверждением отправлено на ваш email.', 'info')
        logger.info(f"Resent verification email to {email}")
    else:
        flash('Пользователь с таким email не найден или уже подтвержден.', 'warning')
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        login_input = request.form.get('login', '').strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))
        user = User.query.filter(
            (User.email == login_input) | (User.username == login_input)
        ).first()

        if user:
            if not user.email_verified:
                flash(
                    'Пожалуйста, подтвердите ваш email перед входом в систему. <a href="#" onclick="showResendForm()">Отправить письмо повторно</a>',
                    'warning')
                logger.warning(f"Login attempt with unverified email: {login_input}")
                return render_template('login.html')

            if user.check_password(password):
                login_user(user, remember=remember)
                flash(f'С возвращением, {user.username}!', 'success')
                logger.info(f"User logged in: {user.username} ({user.email})")
                next_page = request.args.get('next')
                return redirect(next_page or url_for('index'))
            else:
                flash('Неверный логин или пароль.', 'danger')
                logger.warning(f"Failed login attempt for {login_input}: wrong password")
        else:
            flash('Пользователь не найден.', 'danger')
            logger.warning(f"Login attempt for non-existent user: {login_input}")

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logger.info(f"User logged out: {current_user.username}")
    logout_user()
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user)

@app.route('/delete_profile', methods=['POST'])
@login_required
def delete_profile():
    user_id = current_user.id
    username = current_user.username
    email = current_user.email
    try:
        user_to_delete = db.session.get(User, int(user_id))
        # return User.query.get(int(user_id))

        if not user_to_delete:
            flash('Пользователь не найден.', 'danger')
            return redirect(url_for('index'))

        logout_user()

        db.session.delete(user_to_delete)
        db.session.commit()

        logger.info(f"User account deleted: {username} ({email}), ID: {user_id}")
        flash('Ваш профиль был полностью удалён.', 'warning')

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting user {user_id}: {str(e)}", exc_info=True)
        flash('Произошла ошибка при удалении профиля. Пожалуйста, попробуйте позже.', 'danger')

    return redirect(url_for('index'))


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/debug_session')
@login_required
def debug_session():

    debug_info = {
        'current_user_type': str(type(current_user)),
        'current_user_repr': repr(current_user),
        'is_authenticated': current_user.is_authenticated if hasattr(current_user, 'is_authenticated') else 'N/A',
        'session_keys': list(flask_session.keys()),
        'sqlalchemy_version': str(sys.modules.get('sqlalchemy', None)),
        'flask_login_version': str(sys.modules.get('flask_login', None))
    }

    try:
        if current_user.is_authenticated:
            debug_info['user_id'] = current_user.id
            debug_info['username'] = current_user.username
    except Exception as e:
        debug_info['user_error'] = str(e)

    return jsonify(debug_info)

if __name__ == '__main__':
    logger.info("Starting Flask application...")
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='127.0.0.1', port=5000)



