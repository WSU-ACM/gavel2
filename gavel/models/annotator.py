from gavel.models import db, ma
from marshmallow_sqlalchemy import ModelSchema, TableSchema
import gavel.utils as utils
import gavel.crowd_bt as crowd_bt
from sqlalchemy.orm.exc import NoResultFound
from datetime import datetime
from sqlalchemy.ext.hybrid import hybrid_property

from gavel.models._basemodel import BaseModel

ignore_table = db.Table('ignore',
                        db.Column('annotator_id', db.Integer, db.ForeignKey('annotator.id')),
                        db.Column('item_id', db.Integer, db.ForeignKey('item.id'))
                        )


class Annotator(BaseModel):
    __table_args__ = (
        db.CheckConstraint(
            '(external_id IS NULL) = (managed_source IS NULL)',
            name='ck_annotator_integration_identity',
        ),
        db.Index('ix_annotator_managed_source_external_id', 'managed_source', 'external_id'),
        db.Index('ix_annotator_managed_source_roster_active', 'managed_source', 'roster_active'),
    )

    id = db.Column(db.Integer, primary_key=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    external_id = db.Column(db.String(255), unique=True, nullable=True)
    managed_source = db.Column(db.String(64), nullable=True)
    roster_active = db.Column(db.Boolean, nullable=True)
    stop_next = db.Column(db.Boolean, default=False, nullable=False)
    read_welcome = db.Column(db.Boolean, default=False, nullable=False)
    description = db.Column(db.Text, nullable=False)
    secret = db.Column(db.String(32), unique=True, nullable=False)
    next_id = db.Column(db.Integer, db.ForeignKey('item.id'))
    next = db.relationship('Item', foreign_keys=[next_id], uselist=False)
    updated = db.Column(db.DateTime, onupdate=datetime.utcnow)
    prev_id = db.Column(db.Integer, db.ForeignKey('item.id'))
    prev = db.relationship('Item', foreign_keys=[prev_id], uselist=False)
    ignore = db.relationship('Item', secondary=ignore_table)
    project_id = db.Column(db.Integer, db.ForeignKey('item.id', ondelete='SET NULL'), index=True)
    project = db.relationship(
        'Item',
        foreign_keys=[project_id],
        back_populates='members',
        uselist=False,
    )

    alpha = db.Column(db.Float)
    beta = db.Column(db.Float)

    _default_fields = ["name",
                       "email",
                       "active",
                       "roster_active",
                       "effectively_active",
                       "stop_next",
                       "read_welcome",
                       "description",
                       "next_id",
                       "prev_id",
                       "project_id",
                       "ignore",
                       "updated"]
    _secret_fields = ["secret"]

    relations_keys = ("next", "prev", "project", "ignore")

    @hybrid_property
    def effectively_active(self):
        return self.active and self.roster_active is not False

    @effectively_active.expression
    def effectively_active(cls):
        return cls.active.is_(True) & (
            cls.roster_active.is_(None) | cls.roster_active.is_(True)
        )

    def __init__(self, name, email, description):
        self.name = name
        self.email = email
        self.description = description
        self.alpha = crowd_bt.ALPHA_PRIOR
        self.beta = crowd_bt.BETA_PRIOR
        self.secret = utils.gen_secret(32)

    def update_next(self, new_next):
        if new_next is not None:
            new_next.prioritized = False  # it's now assigned, so cancel the prioritization
            # it could happen that the judge skips the project, but that
            # doesn't re-prioritize the project
            self.updated = datetime.utcnow()
        self.next = new_next

    @classmethod
    def by_secret(cls, secret):
        try:
            annotator = cls.query.filter(cls.secret == secret).one()
        except NoResultFound:
            annotator = None
        return annotator

    @classmethod
    def by_id(cls, uid):
        if uid is None:
            return None
        try:
            annotator = cls.query.with_for_update().get(uid)
        except NoResultFound:
            annotator = None
        return annotator
