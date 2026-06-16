from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from sqlalchemy import CheckConstraint, UniqueConstraint, func
from flask_login import UserMixin
from sqlalchemy.dialects.postgresql import TSVECTOR
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=False)
    email_verified = db.Column(db.Boolean, default=False)
    avatar_url = db.Column(db.String(300), default='/static/default-avatar.png')
    bio = db.Column(db.Text, default='')
    reputation = db.Column(db.Integer, default=0)
    is_deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)

    role = db.Column(db.String(20), default='new_user')
    banned_until = db.Column(db.DateTime, nullable=True)
    ban_reason = db.Column(db.Text, nullable=True)

    # Статистика для расчёта кармы
    posts_count = db.Column(db.Integer, default=0)
    comments_count = db.Column(db.Integer, default=0)
    helpful_votes_received = db.Column(db.Integer, default=0)
    helpful_answers_given = db.Column(db.Integer, default=0)
    articles_written = db.Column(db.Integer, default=0)
    questions_asked = db.Column(db.Integer, default=0)

    achievements = db.relationship('UserAchievement', back_populates='user', cascade='all, delete-orphan')
    moderation_actions_done = db.relationship('ModerationAction',
                                              foreign_keys='ModerationAction.moderator_id',
                                              back_populates='moderator',
                                              lazy=True,
                                              cascade='all, delete-orphan')

    reports_created = db.relationship('Report',
                                      foreign_keys='Report.reporter_id',
                                      back_populates='reporter',
                                      lazy=True,
                                      cascade='all, delete-orphan')

    reports_resolved = db.relationship('Report',
                                       foreign_keys='Report.resolved_by',
                                       back_populates='resolver',
                                       lazy=True)

    articles = db.relationship('Article', backref='author', lazy=True,
                               foreign_keys='Article.author_id',
                               cascade='all')
    questions = db.relationship('Question', backref='author', lazy=True,
                                foreign_keys='Question.author_id',
                                cascade='all')
    comments = db.relationship('Comment', backref='author', lazy=True,
                               cascade='all')
    votes = db.relationship('Vote', backref='user', lazy=True,
                            cascade='all, delete-orphan')
    bookmarks = db.relationship('Bookmark', backref='user', lazy=True,
                                cascade='all, delete-orphan')
    subscriptions = db.relationship('Subscription', backref='user', lazy=True,
                                    cascade='all, delete-orphan')
    group_memberships = db.relationship('UserGroup', backref='user', lazy=True,
                                        cascade='all, delete-orphan')
    owned_groups = db.relationship('Group', backref='owner', lazy=True,
                                   cascade='all')

    __table_args__ = (
        CheckConstraint("role IN ('new_user', 'user', 'moderator', 'admin')", name='check_user_role'),
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        if self.is_deleted:
            return f'<User {self.id} (deleted)>'
        return f'<User {self.username}>'

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()
        self.is_active = False
        self.username = f"deleted_user_{self.id}"
        self.email = f"deleted_{self.id}@deleted.qarticle"
        self.avatar_url = '/static/default-avatar.png'
        self.bio = "Пользователь удалён"

    @property
    def is_new_user(self):
        return self.role == 'new_user'

    @property
    def is_regular_user(self):
        return self.role == 'user'

    @property
    def is_moderator(self):
        return self.role in ('moderator', 'admin')

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_banned(self):
        if self.banned_until and self.banned_until > datetime.utcnow():
            return True
        return False

    def can_create_post(self):
        if self.is_banned:
            return False, "Вы забанены до " + self.banned_until.strftime('%d.%m.%Y')
        return True, ""

    def can_comment(self):
        if self.is_banned:
            return False, "Вы забанены"
        return True, ""

    def can_vote(self):
        if self.is_banned:
            return False, "Забаненные пользователи не могут голосовать"
        if self.is_new_user:
            return False, "Новые пользователи не могут голосовать до получения 10 репутации"
        return True, ""

    def can_moderate(self, target_user=None):
        if self.is_admin:
            return True
        if self.is_moderator:
            if target_user and target_user.is_admin:
                return False
            return True
        return False

    def update_role_by_reputation(self):
        if self.reputation >= 500 and self.role != 'admin':
            self.role = 'moderator'
        elif self.reputation >= 100 and self.role not in ('moderator', 'admin'):
            self.role = 'user'
        elif self.reputation < 100 and self.role not in ('moderator', 'admin'):
            self.role = 'new_user'

    def add_reputation(self, points, reason=''):
        self.reputation += points
        self.update_role_by_reputation()

        rep_log = ReputationLog(
            user_id=self.id,
            points_change=points,
            reason=reason,
            new_reputation=self.reputation
        )
        db.session.add(rep_log)



class Group(db.Model):
    __tablename__ = 'groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    is_private = db.Column(db.Boolean, default=False)


    members = db.relationship('UserGroup', backref='group', lazy=True, cascade='all, delete-orphan')
    posts = db.relationship('Post', backref='group', lazy=True, cascade='all')

    def __repr__(self):
        return f'<Group {self.name}>'


class UserGroup(db.Model):
    __tablename__ = 'user_groups'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id', ondelete='CASCADE'), primary_key=True)
    role = db.Column(db.String(20), default='member')  # member, moderator, admin
    karma_in_group = db.Column(db.Integer, default=0)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    posts_count_in_group = db.Column(db.Integer, default=0)
    helpful_answers_in_group = db.Column(db.Integer, default=0)

    __table_args__ = (
        CheckConstraint("role IN ('member', 'moderator', 'admin')", name='check_user_group_role'),
    )

    def update_group_role(self):
        if self.karma_in_group >= 1000:
            self.role = 'admin'
        elif self.karma_in_group >= 500:
            self.role = 'moderator'
        else:
            self.role = 'member'

    def add_karma(self, points, session=None):
        self.karma_in_group += points
        self.update_group_role()
        if session:
            session.commit()


class Post(db.Model):
    __tablename__ = 'posts'

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status = db.Column(db.String(20), default='published')
    rating = db.Column(db.Integer, default=0)
    view_count = db.Column(db.Integer, default=0)

    search_vector = db.Column(TSVECTOR, nullable=True)

    comments = db.relationship('Comment', backref='post', lazy=True, cascade='all, delete-orphan')
    tags = db.relationship('PostTag', backref='post', lazy=True, cascade='all, delete-orphan')
    bookmarks = db.relationship('Bookmark', backref='post', lazy=True, cascade='all, delete-orphan')

    '''votes = db.relationship('Vote',
                            primaryjoin="and_(Vote.target_type=='post', Vote.target_id==Post.id)",
                            cascade='all, delete-orphan',
                            lazy='dynamic', viewonly=True)'''

    __table_args__ = (
        CheckConstraint("type IN ('article', 'question')", name='check_post_type'),
        CheckConstraint("status IN ('draft', 'published')", name='check_post_status'),
    )

    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'post'
    }


class Article(Post):
    __tablename__ = 'articles'

    id = db.Column(db.Integer, db.ForeignKey('posts.id', ondelete='CASCADE'), primary_key=True)
    is_curated = db.Column(db.Boolean, default=False)
    source_question_id = db.Column(db.Integer, db.ForeignKey('questions.id', ondelete='SET NULL'), nullable=True)

    source_question = db.relationship('Question', foreign_keys=[source_question_id], backref='source_article')

    __mapper_args__ = {
        'polymorphic_identity': 'article'
    }


class Question(Post):
    __tablename__ = 'questions'

    id = db.Column(db.Integer, db.ForeignKey('posts.id', ondelete='CASCADE'), primary_key=True)
    accepted_answer_id = db.Column(db.Integer, db.ForeignKey('comments.id', ondelete='SET NULL'), nullable=True)
    is_resolved = db.Column(db.Boolean, default=False)
    article_context_id = db.Column(db.Integer, db.ForeignKey('articles.id', ondelete='SET NULL'), nullable=True)
    fragment_ref = db.Column(db.String(100), nullable=True)

    accepted_answer = db.relationship('Comment', foreign_keys=[accepted_answer_id], backref='accepted_for_question')
    article_context = db.relationship('Article', foreign_keys=[article_context_id], backref='related_questions')
    answers = db.relationship('Comment', backref='question', lazy=True, foreign_keys='Comment.question_id', cascade='all, delete-orphan')

    __mapper_args__ = {
        'polymorphic_identity': 'question'
    }


class Tag(db.Model):
    __tablename__ = 'tags'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    description = db.Column(db.Text, default='')

    posts = db.relationship('PostTag', backref='tag', lazy=True)

    def __repr__(self):
        return f'<Tag {self.name}>'


class PostTag(db.Model):
    __tablename__ = 'post_tags'

    post_id = db.Column(db.Integer, db.ForeignKey('posts.id', ondelete='CASCADE'), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True)


class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id', ondelete='CASCADE'), nullable=False)
    parent_comment_id = db.Column(db.Integer, db.ForeignKey('comments.id', ondelete='CASCADE'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    rating = db.Column(db.Integer, default=0)
    is_answer = db.Column(db.Boolean, default=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id', ondelete='CASCADE'), nullable=True)

    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), lazy=True, cascade='all, delete-orphan')

    '''votes = db.relationship('Vote',
                            primaryjoin="and_(Vote.target_type=='comment', Vote.target_id==Comment.id)",
                            cascade='all, delete-orphan',
                            lazy='dynamic')'''

    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]),
                              lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Comment {self.id} by {self.author_id}>'


class Vote(db.Model):
    __tablename__ = 'votes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    target_type = db.Column(db.String(20), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    value = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("value IN (1, -1)", name='check_vote_value'),
        CheckConstraint("target_type IN ('post', 'comment')", name='check_vote_target_type'),
        db.UniqueConstraint('user_id', 'target_type', 'target_id', name='unique_vote'),
    )


class Bookmark(db.Model):
    __tablename__ = 'bookmarks'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id', ondelete='CASCADE'), primary_key=True)
    saved_at = db.Column(db.DateTime, default=datetime.utcnow)


class Subscription(db.Model):
    __tablename__ = 'subscriptions'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    target_type = db.Column(db.String(20), primary_key=True)
    target_id = db.Column(db.Integer, primary_key=True)
    subscribed_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("target_type IN ('author', 'tag', 'group')", name='check_subscription_target_type'),
    )


class ReputationLog(db.Model):
    __tablename__ = 'reputation_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    points_change = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(200))
    new_reputation = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='reputation_logs')


class UserAchievement(db.Model):
    __tablename__ = 'user_achievements'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    achievement_type = db.Column(db.String(50), nullable=False)
    achieved_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='achievements')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'achievement_type', name='unique_user_achievement'),
    )

    ACHIEVEMENTS = {
        'first_post': 'Первый пост',
        'first_comment': 'Первый комментарий',
        'first_upvote': 'Первый лайк',
        'helper_10': 'Помощник (10 ответов)',
        'helper_100': 'Эксперт (100 ответов)',
        'popular_article': 'Популярная статья (100+ лайков)',
        'question_expert': 'Мастер вопросов (50 вопросов)',
    }


class ModerationAction(db.Model):
    __tablename__ = 'moderation_actions'

    id = db.Column(db.Integer, primary_key=True)
    moderator_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)
    target_type = db.Column(db.String(20), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.Text)
    duration_days = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    moderator = db.relationship('User', foreign_keys=[moderator_id], back_populates='moderation_actions_done')


class Report(db.Model):
    __tablename__ = 'reports'

    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=False)
    target_type = db.Column(db.String(20), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending')
    resolved_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    resolution_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)

    reporter = db.relationship('User', foreign_keys=[reporter_id], back_populates='reports_created')
    resolver = db.relationship('User', foreign_keys=[resolved_by], back_populates='reports_resolved')

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'reviewed', 'rejected', 'resolved')", name='check_report_status'),
    )


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # comment, answer, vote, mention, follow, system
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(500), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)

    target_type = db.Column(db.String(20), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    actor_username = db.Column(db.String(80), nullable=True)

    user = db.relationship('User', foreign_keys=[user_id], backref='notifications')
    actor = db.relationship('User', foreign_keys=[actor_id], backref='acted_notifications')

    __table_args__ = (
        CheckConstraint(
            "type IN ('comment', 'answer', 'vote', 'mention', 'follow', 'system', 'moderation', 'achievement')",
            name='check_notification_type'
        ),
    )

    @classmethod
    def create_notification(cls, user_id, type, title, message, link=None,
                            target_type=None, target_id=None, actor_id=None):
        notification = cls(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            link=link,
            target_type=target_type,
            target_id=target_id,
            actor_id=actor_id
        )
        if actor_id:
            actor = db.session.get(User, actor_id)
            if actor and not actor.is_deleted:
                notification.actor_username = actor.username
        db.session.add(notification)
        db.session.commit()
        return notification

    def mark_as_read(self):
        self.is_read = True
        self.read_at = datetime.utcnow()
        db.session.commit()

    def mark_as_unread(self):
        self.is_read = False
        self.read_at = None
        db.session.commit()

    @classmethod
    def mark_all_as_read(cls, user_id):
        cls.query.filter_by(user_id=user_id, is_read=False).update(
            {'is_read': True, 'read_at': datetime.utcnow()}
        )
        db.session.commit()

    @classmethod
    def get_unread_count(cls, user_id):
        return cls.query.filter_by(user_id=user_id, is_read=False).count()