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
from models import db, User, Post, Tag, PostTag, Comment, Vote, Group, UserGroup, Article, Question, Bookmark, \
    Subscription
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
        if not re.match(r'^[a-zA-ZА-Яа-яЁё0-9_\-]+$', username):
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


@app.route('/user/<string:username>')
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    if current_user.is_authenticated and user.id == current_user.id:
        return redirect(url_for('profile'))
    user = User.query.filter_by(username=username).first_or_404()

    articles = Article.query.filter_by(author_id=user.id, status='published').order_by(Article.created_at.desc()).all()
    questions = Question.query.filter_by(author_id=user.id, status='published').order_by(
        Question.created_at.desc()).all()
    comments = Comment.query.filter_by(author_id=user.id).order_by(Comment.created_at.desc()).limit(20).all()

    total_rating = sum(a.rating for a in articles) + sum(q.rating for q in questions)
    total_views = sum(a.view_count for a in articles) + sum(q.view_count for q in questions)

    is_subscribed = False
    if current_user.is_authenticated and current_user.id != user.id:
        sub = Subscription.query.filter_by(
            user_id=current_user.id,
            target_type='author',
            target_id=user.id
        ).first()
        is_subscribed = sub is not None

    return render_template('user_profile.html',
                           profile_user=user,
                           articles=articles,
                           questions=questions,
                           comments=comments,
                           total_rating=total_rating,
                           total_views=total_views,
                           is_subscribed=is_subscribed)


@app.route('/subscribe_user/<int:user_id>', methods=['POST'])
@login_required
def subscribe_user(user_id):
    target_user = db.session.get(User, user_id)
    if not target_user:
        return jsonify({'error': 'User not found'}), 404

    if target_user.id == current_user.id:
        return jsonify({'error': 'Cannot subscribe to yourself'}), 400

    existing = Subscription.query.filter_by(
        user_id=current_user.id,
        target_type='author',
        target_id=user_id
    ).first()

    if existing:
        db.session.delete(existing)
        subscribed = False
    else:
        subscription = Subscription(
            user_id=current_user.id,
            target_type='author',
            target_id=user_id
        )
        db.session.add(subscription)
        subscribed = True

    db.session.commit()

    return jsonify({'subscribed': subscribed})

@app.route('/profile')
@login_required
def profile():
    active_tab = request.args.get('tab', 'articles')
    bookmarked_posts = Bookmark.query.filter_by(user_id=current_user.id).all()

    is_subscribed = False
    #  добавить логику подписки

    return render_template('profile.html',
                           user=current_user,
                           active_tab=active_tab,
                           bookmarked_posts=bookmarked_posts,
                           is_subscribed=is_subscribed)


@app.route('/edit_profile', methods=['POST'])
@login_required
def edit_profile():
    bio = request.form.get('bio', '').strip()
    current_user.bio = bio
    db.session.commit()
    flash('Профиль обновлен', 'success')
    return redirect(url_for('profile'))


@app.route('/upload_avatar', methods=['POST'])
@login_required
def upload_avatar():
    if 'avatar' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # нужно будет добавить логику сохранения файла


    return jsonify({'success': True})




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
    page = request.args.get('page', 1, type=int)
    filter_type = request.args.get('filter', 'all')

    query = Post.query.filter_by(status='published')

    if filter_type == 'article':
        query = query.filter_by(type='article')
    elif filter_type == 'question':
        query = query.filter_by(type='question')

    posts = query.order_by(Post.created_at.desc()).paginate(page=page, per_page=10)
    groups = Group.query.limit(5).all()
    popular_tags = db.session.query(Tag).join(PostTag).group_by(Tag.id).order_by(
        func.count(PostTag.post_id).desc()).limit(10).all()
    top_users = User.query.order_by(User.reputation.desc()).limit(5).all()
    bookmarked_post_ids = []
    if current_user.is_authenticated:
        bookmarked_post_ids = [b.post_id for b in Bookmark.query.filter_by(user_id=current_user.id).all()]

    return render_template('index.html',
                           posts=posts,
                           groups=groups,
                           popular_tags=popular_tags,
                           top_users=top_users,
                           bookmarked_post_ids=bookmarked_post_ids)


@app.route('/groups')
def groups():
    page = request.args.get('page', 1, type=int)
    groups_list = Group.query.filter_by(is_private=False).paginate(page=page, per_page=20)
    return render_template('groups.html', groups=groups_list)


@app.route('/group/<int:group_id>')
def group_detail(group_id):
    group = db.session.get(Group, group_id)
    if not group:
        abort(404)

    if group.is_private and not current_user.is_authenticated:
        flash('Это приватное сообщество. Войдите для доступа.', 'warning')
        return redirect(url_for('login'))

    if group.is_private:
        membership = UserGroup.query.filter_by(user_id=current_user.id, group_id=group_id).first()
        if not membership and group.owner_id != current_user.id:
            abort(403)

    posts = Post.query.filter_by(group_id=group_id, status='published').order_by(Post.created_at.desc()).all()
    members = UserGroup.query.filter_by(group_id=group_id).limit(20).all()

    return render_template('group_detail.html', group=group, posts=posts, members=members)


@app.route('/group/<int:group_id>/join', methods=['POST'])
@login_required
def join_group(group_id):
    group = db.session.get(Group, group_id)
    if not group:
        abort(404)

    existing = UserGroup.query.filter_by(user_id=current_user.id, group_id=group_id).first()
    if existing:
        flash('Вы уже состоите в этом сообществе', 'info')
        return redirect(url_for('group_detail', group_id=group_id))

    membership = UserGroup(user_id=current_user.id, group_id=group_id, role='member')
    db.session.add(membership)
    db.session.commit()

    flash(f'Вы присоединились к сообществу "{group.name}"', 'success')
    return redirect(url_for('group_detail', group_id=group_id))


@app.route('/group/create', methods=['GET', 'POST'])
@login_required
def create_group():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        is_private = request.form.get('is_private') == 'on'

        if not name:
            flash('Название группы обязательно', 'danger')
            return render_template('create_group.html')

        existing = Group.query.filter_by(name=name).first()
        if existing:
            flash('Группа с таким названием уже существует', 'danger')
            return render_template('create_group.html')

        group = Group(
            name=name,
            description=description,
            owner_id=current_user.id,
            is_private=is_private
        )
        db.session.add(group)
        db.session.commit()

        membership = UserGroup(user_id=current_user.id, group_id=group.id, role='admin', karma_in_group=0)
        db.session.add(membership)
        db.session.commit()

        flash(f'Группа "{name}" успешно создана!', 'success')
        return redirect(url_for('group_detail', group_id=group.id))

    return render_template('create_group.html')


@app.route('/post/<int:post_id>')
def post_detail(post_id):
    post = db.session.get(Post, post_id)
    if not post:
        abort(404)

    post.view_count += 1
    db.session.commit()

    comments = Comment.query.filter_by(post_id=post_id, parent_comment_id=None).order_by(Comment.created_at).all()

    answers = []
    if post.type == 'question':
        answers = Comment.query.filter_by(question_id=post_id, is_answer=True).order_by(Comment.rating.desc()).all()

    post_user_vote = 0
    comment_user_votes = {}
    answer_user_votes = {}
    reply_user_votes = {}

    if current_user.is_authenticated:
        post_vote = Vote.query.filter_by(
            user_id=current_user.id,
            target_type='post',
            target_id=post_id
        ).first()
        post_user_vote = post_vote.value if post_vote else 0

        for comment in comments:
            vote = Vote.query.filter_by(
                user_id=current_user.id,
                target_type='comment',
                target_id=comment.id
            ).first()
            comment_user_votes[comment.id] = vote.value if vote else 0

            for reply in comment.replies:
                reply_vote = Vote.query.filter_by(
                    user_id=current_user.id,
                    target_type='comment',
                    target_id=reply.id
                ).first()
                reply_user_votes[reply.id] = reply_vote.value if reply_vote else 0

        for answer in answers:
            vote = Vote.query.filter_by(
                user_id=current_user.id,
                target_type='comment',
                target_id=answer.id
            ).first()
            answer_user_votes[answer.id] = vote.value if vote else 0

            for reply in answer.replies:
                reply_vote = Vote.query.filter_by(
                    user_id=current_user.id,
                    target_type='comment',
                    target_id=reply.id
                ).first()
                reply_user_votes[reply.id] = reply_vote.value if reply_vote else 0

    similar_posts = []
    if post.tags:
        tag_ids = [pt.tag_id for pt in post.tags]
        similar_posts = Post.query.join(PostTag).filter(
            PostTag.tag_id.in_(tag_ids),
            Post.id != post_id,
            Post.status == 'published'
        ).distinct().limit(5).all()

    is_subscribed = False
    if current_user.is_authenticated and post.author.id != current_user.id:
        sub = Subscription.query.filter_by(
            user_id=current_user.id,
            target_type='author',
            target_id=post.author.id
        ).first()
        is_subscribed = sub is not None

    bookmarked_post_ids = []
    if current_user.is_authenticated:
        bookmarked_post_ids = [b.post_id for b in Bookmark.query.filter_by(user_id=current_user.id).all()]

    return render_template('post_detail.html',
                           post=post,
                           comments=comments,
                           answers=answers,
                           post_user_vote=post_user_vote,
                           comment_user_votes=comment_user_votes,
                           answer_user_votes=answer_user_votes,
                           reply_user_votes=reply_user_votes,
                           similar_posts=similar_posts,
                           is_subscribed=is_subscribed,
                           bookmarked_post_ids=bookmarked_post_ids)



@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    if request.method == 'POST':
        post_type = request.form.get('type')
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        group_id = request.form.get('group_id')
        tags_input = request.form.get('tags', '').strip()

        if not title or not content:
            flash('Заполните заголовок и содержание', 'danger')
            return render_template('create_post.html')

        group_id = int(group_id) if group_id and group_id.isdigit() else None
        if group_id:
            group = db.session.get(Group, group_id)
            if group and group.is_private:
                membership = UserGroup.query.filter_by(user_id=current_user.id, group_id=group_id).first()
                if not membership and group.owner_id != current_user.id:
                    flash('У вас нет доступа к этой группе', 'danger')
                    return render_template('create_post.html')

        if post_type == 'article':
            post = Article(
                type='article',
                title=title,
                content=content,
                author_id=current_user.id,
                group_id=group_id,
                is_curated=False
            )
        else:
            post = Question(
                type='question',
                title=title,
                content=content,
                author_id=current_user.id,
                group_id=group_id,
                is_resolved=False
            )

        db.session.add(post)
        db.session.commit()

        if tags_input:
            tags = [t.strip().lower() for t in tags_input.split(',') if t.strip()]
            for tag_name in tags:
                tag = Tag.query.filter_by(name=tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.session.add(tag)
                    db.session.flush()
                post_tag = PostTag(post_id=post.id, tag_id=tag.id)
                db.session.add(post_tag)
            db.session.commit()

        flash('Пост успешно создан!', 'success')
        return redirect(url_for('post_detail', post_id=post.id))

    groups = Group.query.all() if current_user.is_authenticated else []
    return render_template('create_post.html', groups=groups)


@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = db.session.get(Post, post_id)
    if not post or post.author_id != current_user.id:
        abort(404)

    if request.method == 'POST':
        post.title = request.form.get('title', '').strip()
        post.content = request.form.get('content', '').strip()
        post.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Пост обновлен', 'success')
        return redirect(url_for('post_detail', post_id=post.id))

    return render_template('edit_post.html', post=post)


@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment(post_id):
    post = db.session.get(Post, post_id)
    if not post:
        abort(404)

    content = request.form.get('content', '').strip()
    parent_id = request.form.get('parent_id')
    is_answer = request.form.get('is_answer') == 'on' and post.type == 'question'

    if not content:
        flash('Комментарий не может быть пустым', 'danger')
        return redirect(url_for('post_detail', post_id=post_id))

    comment = Comment(
        content=content,
        author_id=current_user.id,
        post_id=post_id,
        parent_comment_id=int(parent_id) if parent_id else None,
        is_answer=is_answer,
        question_id=post_id if is_answer else None
    )

    db.session.add(comment)
    db.session.commit()

    flash('Комментарий добавлен', 'success')
    return redirect(url_for('post_detail', post_id=post_id))

@app.route('/comment/<int:comment_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_comment(comment_id):
    comment = db.session.get(Comment, comment_id)
    if not comment or comment.author_id != current_user.id:
        abort(404)

    if request.method == 'POST':
        new_content = request.form.get('content', '').strip()
        if not new_content:
            flash('Комментарий не может быть пустым', 'danger')
            return redirect(url_for('edit_comment', comment_id=comment_id))

        comment.content = new_content
        comment.updated_at = datetime.utcnow()  # если добавите поле updated_at в модель
        db.session.commit()
        flash('Комментарий обновлён', 'success')
        return redirect(url_for('post_detail', post_id=comment.post_id))

    return render_template('edit_comment.html', comment=comment)


@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = db.session.get(Comment, comment_id)
    if not comment or comment.author_id != current_user.id:
        abort(404)
    post_id = comment.post_id
    db.session.delete(comment)
    db.session.commit()
    flash('Комментарий удалён', 'success')
    return redirect(url_for('post_detail', post_id=post_id))



@app.route('/vote', methods=['POST'])
@login_required
def vote():
    data = request.get_json()
    target_type = data.get('target_type')
    target_id = data.get('target_id')
    value = int(data.get('value'))

    if target_type not in ['post', 'comment'] or value not in [-1, 0, 1]:
        return jsonify({'error': 'Invalid request'}), 400

    if target_type == 'post':
        target = db.session.get(Post, target_id)
    else:
        target = db.session.get(Comment, target_id)

    if not target:
        return jsonify({'error': 'Target not found'}), 404

    if target.author_id == current_user.id:
        return jsonify({'error': 'You cannot vote on your own content'}), 400

    existing_vote = Vote.query.filter_by(
        user_id=current_user.id,
        target_type=target_type,
        target_id=target_id
    ).first()

    delta = 0

    if value == 0:
        if existing_vote:
            delta = -existing_vote.value
            db.session.delete(existing_vote)
    else:
        if existing_vote:
            if existing_vote.value == value:
                delta = -value
                db.session.delete(existing_vote)
                value = 0
            else:
                delta = 2 * value
                existing_vote.value = value
        else:
            vote = Vote(
                user_id=current_user.id,
                target_type=target_type,
                target_id=target_id,
                value=value
            )
            db.session.add(vote)
            delta = value

    if delta != 0:
        target.rating += delta

        author = db.session.get(User, target.author_id)
        if author:
            author.reputation += delta

    db.session.commit()

    current_vote = 0
    if value != 0:
        current_vote = value
    elif existing_vote and existing_vote.value == value:
        current_vote = 0
    elif existing_vote:
        current_vote = existing_vote.value

    return jsonify({
        'success': True,
        'new_rating': target.rating,
        'user_vote': current_vote
    })




@app.route('/tag/<string:tag_name>')
def tag_posts(tag_name):
    tag = Tag.query.filter_by(name=tag_name).first_or_404()
    page = request.args.get('page', 1, type=int)
    posts = db.session.query(Post).join(PostTag).filter(PostTag.tag_id == tag.id).paginate(page=page, per_page=20)
    return render_template('tag_posts.html', tag=tag, posts=posts)


@app.route('/tags')
def tags_list():
    tags = Tag.query.order_by(Tag.name).all()
    return render_template('tags.html', tags=tags)

@app.route('/bookmark/<int:post_id>', methods=['POST'])
@login_required
def toggle_bookmark(post_id):
    post = db.session.get(Post, post_id)
    if not post:
        return jsonify({'error': 'Post not found'}), 404

    bookmark = Bookmark.query.filter_by(user_id=current_user.id, post_id=post_id).first()

    if bookmark:
        db.session.delete(bookmark)
        bookmarked = False
    else:
        bookmark = Bookmark(user_id=current_user.id, post_id=post_id)
        db.session.add(bookmark)
        bookmarked = True

    db.session.commit()

    return jsonify({'bookmarked': bookmarked})




@app.route('/bookmarks')
@login_required
def bookmarks():
    page = request.args.get('page', 1, type=int)
    filter_type = request.args.get('filter', 'all')
    query = Bookmark.query.filter_by(user_id=current_user.id)

    if filter_type == 'article':
        query = query.join(Post, Bookmark.post_id == Post.id).filter(Post.type == 'article')
    elif filter_type == 'question':
        query = query.join(Post, Bookmark.post_id == Post.id).filter(Post.type == 'question')

    bookmarked_posts = query.order_by(Bookmark.saved_at.desc()).paginate(page=page, per_page=20)

    tag_stats = db.session.query(
        Tag.name,
        func.count(PostTag.tag_id).label('count')
    ).select_from(Bookmark).join(
        Post, Bookmark.post_id == Post.id
    ).join(
        PostTag, Post.id == PostTag.post_id
    ).join(
        Tag, PostTag.tag_id == Tag.id
    ).filter(
        Bookmark.user_id == current_user.id
    ).group_by(
        Tag.id, Tag.name
    ).order_by(
        func.count(PostTag.tag_id).desc()
    ).limit(15).all()

    return render_template('bookmarks.html',
                           bookmarks=bookmarked_posts,
                           tag_stats=tag_stats)


@app.route('/subscribe', methods=['POST'])
@login_required
def subscribe():
    data = request.get_json()
    target_type = data.get('target_type')  # author, tag, group
    target_id = data.get('target_id')

    if target_type not in ['author', 'tag', 'group']:
        return jsonify({'error': 'Invalid target type'}), 400

    existing = Subscription.query.filter_by(
        user_id=current_user.id,
        target_type=target_type,
        target_id=target_id
    ).first()

    if existing:
        db.session.delete(existing)
        subscribed = False
    else:
        subscription = Subscription(user_id=current_user.id, target_type=target_type, target_id=target_id)
        db.session.add(subscription)
        subscribed = True

    db.session.commit()

    return jsonify({'subscribed': subscribed})



@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post = db.session.get(Post, post_id)
    if not post or post.author_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    db.session.delete(post)
    db.session.commit()

    return jsonify({'success': True})


@app.route('/accept_answer/<int:answer_id>', methods=['POST'])
@login_required
def accept_answer(answer_id):
    answer = db.session.get(Comment, answer_id)
    if not answer or not answer.is_answer:
        return jsonify({'error': 'Invalid answer'}), 400

    question = db.session.get(Question, answer.question_id)
    if not question or question.author_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    question.accepted_answer_id = answer_id
    question.is_resolved = True
    db.session.commit()

    return jsonify({'success': True})


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



