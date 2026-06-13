from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from sqlalchemy import CheckConstraint, UniqueConstraint, func
from flask_login import UserMixin
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

    articles = db.relationship('Article', backref='author', lazy=True, foreign_keys='Article.author_id', cascade='all')
    questions = db.relationship('Question', backref='author', lazy=True, foreign_keys='Question.author_id', cascade='all')
    comments = db.relationship('Comment', backref='author', lazy=True, cascade='all')
    votes = db.relationship('Vote', backref='user', lazy=True, cascade='all, delete-orphan')
    bookmarks = db.relationship('Bookmark', backref='user', lazy=True, cascade='all, delete-orphan')
    subscriptions = db.relationship('Subscription', backref='user', lazy=True, cascade='all, delete-orphan')
    group_memberships = db.relationship('UserGroup', backref='user', lazy=True, cascade='all, delete-orphan')
    owned_groups = db.relationship('Group', backref='owner', lazy=True, cascade='all')

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

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), primary_key=True)
    role = db.Column(db.String(20), default='member')
    karma_in_group = db.Column(db.Integer, default=0)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("role IN ('member', 'moderator', 'admin')", name='check_user_group_role'),
    )


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