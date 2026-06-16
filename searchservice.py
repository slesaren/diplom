from models import db, User, Post, Tag, PostTag, Comment, Vote, Group, UserGroup, Article, Question, Bookmark, \
    Subscription, UserAchievement, Report, ModerationAction
from redis_utils import RedisBookStats

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, UniqueConstraint, func
from datetime import datetime

from sqlalchemy import func, cast, String
from sqlalchemy.dialects.postgresql import TSVECTOR, TSQUERY


class SearchService:
    @staticmethod
    def search_posts(query, filters=None, page=1, per_page=20):
        if filters is None:
            filters = {}
        search_query = Post.query.filter(Post.status == 'published')
        if query and query.strip():
            search_vector = func.to_tsvector('russian',
                                             func.concat(Post.title, ' ', Post.content))
            search_query_text = func.plainto_tsquery('russian', query)
            search_query = search_query.filter(search_vector.op('@@')(search_query_text))

            search_query = search_query.order_by(
                func.ts_rank(search_vector, search_query_text).desc())

        if filters.get('post_type'):
            search_query = search_query.filter(Post.type == filters['post_type'])

        if filters.get('tags'):
            tags = filters['tags'] if isinstance(filters['tags'], list) else [filters['tags']]
            for tag_name in tags:
                search_query = search_query.join(PostTag).join(Tag).filter(Tag.name == tag_name)

        if filters.get('author'):
            search_query = search_query.join(User).filter(
                User.username.ilike(f"%{filters['author']}%") |
                User.id == filters['author'] if isinstance(filters['author'], int) else False
            )

        if filters.get('group_id'):
            search_query = search_query.filter(Post.group_id == filters['group_id'])
        if filters.get('date_from'):
            search_query = search_query.filter(Post.created_at >= filters['date_from'])
        if filters.get('date_to'):
            search_query = search_query.filter(Post.created_at <= filters['date_to'])

        if filters.get('is_resolved') is not None and filters['post_type'] == 'question':
            search_query = search_query.join(Question).filter(
                Question.is_resolved == filters['is_resolved'])

        sort_by = filters.get('sort_by', 'relevance')
        if sort_by == 'newest':
            search_query = search_query.order_by(Post.created_at.desc())
        elif sort_by == 'oldest':
            search_query = search_query.order_by(Post.created_at.asc())
        elif sort_by == 'popular':
            search_query = search_query.order_by(Post.rating.desc(), Post.view_count.desc())
        elif sort_by == 'most_commented':
            search_query = search_query.outerjoin(Comment).group_by(Post.id).order_by(
                func.count(Comment.id).desc())
        elif sort_by == 'relevance' and (not query or not query.strip()):
            search_query = search_query.order_by(Post.created_at.desc())

        return search_query.paginate(page=page, per_page=per_page, error_out=False)

    @staticmethod
    def get_search_suggestions(query, limit=5):
        if not query or len(query) < 2:
            return []
# zagolovki
        suggestions = db.session.query(
            Post.title,
            func.similarity(Post.title, query).label('similarity')
        ).filter(
            Post.status == 'published',
            func.similarity(Post.title, query) > 0.1
        ).order_by(
            func.similarity(Post.title, query).desc()
        ).limit(limit).all()

        tag_suggestions = Tag.query.filter(
            Tag.name.ilike(f"%{query}%")
        ).limit(limit).all()

        return {
            'titles': [s[0] for s in suggestions],
            'tags': [t.name for t in tag_suggestions]
        }

    @staticmethod
    def get_popular_searches(limit=10):
        popular_tags = db.session.query(
            Tag.name,
            func.count(PostTag.post_id).label('count')
        ).join(PostTag).join(Post).filter(
            Post.status == 'published'
        ).group_by(Tag.id, Tag.name).order_by(
            func.count(PostTag.post_id).desc()
        ).limit(limit).all()

        return [tag_name for tag_name, count in popular_tags]




