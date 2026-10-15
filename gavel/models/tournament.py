from datetime import datetime

from gavel.models import db
from gavel.models._basemodel import BaseModel


class Tournament(BaseModel):
    id = db.Column(db.Integer, primary_key=True, nullable=False)
    size = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(16), nullable=False, default='active', index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    champion_id = db.Column(db.Integer, db.ForeignKey('item.id', ondelete='RESTRICT'))
    champion = db.relationship('Item', foreign_keys=[champion_id])

    entries = db.relationship(
        'TournamentEntry',
        back_populates='tournament',
        cascade='all, delete-orphan',
        order_by='TournamentEntry.seed',
    )
    matches = db.relationship(
        'BracketMatch',
        back_populates='tournament',
        cascade='all, delete-orphan',
        order_by='(BracketMatch.round_number, BracketMatch.position)',
    )


class TournamentEntry(BaseModel):
    id = db.Column(db.Integer, primary_key=True, nullable=False)
    tournament_id = db.Column(
        db.Integer,
        db.ForeignKey('tournament.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    item_id = db.Column(
        db.Integer,
        db.ForeignKey('item.id', ondelete='RESTRICT'),
        nullable=False,
    )
    seed = db.Column(db.Integer, nullable=False)
    initial_mu = db.Column(db.Float, nullable=False)
    initial_sigma_sq = db.Column(db.Float, nullable=False)

    tournament = db.relationship('Tournament', back_populates='entries')
    item = db.relationship('Item')

    __table_args__ = (
        db.UniqueConstraint('tournament_id', 'item_id'),
        db.UniqueConstraint('tournament_id', 'seed'),
    )


class BracketMatch(BaseModel):
    id = db.Column(db.Integer, primary_key=True, nullable=False)
    tournament_id = db.Column(
        db.Integer,
        db.ForeignKey('tournament.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    round_number = db.Column(db.Integer, nullable=False)
    position = db.Column(db.Integer, nullable=False)
    item_a_id = db.Column(db.Integer, db.ForeignKey('item.id', ondelete='RESTRICT'))
    item_b_id = db.Column(db.Integer, db.ForeignKey('item.id', ondelete='RESTRICT'))
    winner_id = db.Column(db.Integer, db.ForeignKey('item.id', ondelete='RESTRICT'))
    status = db.Column(db.String(16), nullable=False, default='pending', index=True)
    opened_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)

    tournament = db.relationship('Tournament', back_populates='matches')
    item_a = db.relationship('Item', foreign_keys=[item_a_id])
    item_b = db.relationship('Item', foreign_keys=[item_b_id])
    winner = db.relationship('Item', foreign_keys=[winner_id])
    votes = db.relationship(
        'BracketVote',
        back_populates='match',
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        db.UniqueConstraint('tournament_id', 'round_number', 'position'),
        db.CheckConstraint('item_a_id IS NULL OR item_b_id IS NULL OR item_a_id <> item_b_id'),
    )

    @property
    def ready(self):
        return self.item_a_id is not None and self.item_b_id is not None


class BracketVote(BaseModel):
    id = db.Column(db.Integer, primary_key=True, nullable=False)
    match_id = db.Column(
        db.Integer,
        db.ForeignKey('bracket_match.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    annotator_id = db.Column(
        db.Integer,
        db.ForeignKey('annotator.id', ondelete='RESTRICT'),
        nullable=False,
        index=True,
    )
    item_id = db.Column(
        db.Integer,
        db.ForeignKey('item.id', ondelete='RESTRICT'),
        nullable=False,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    match = db.relationship('BracketMatch', back_populates='votes')
    annotator = db.relationship('Annotator')
    item = db.relationship('Item')

    __table_args__ = (
        db.UniqueConstraint('match_id', 'annotator_id'),
    )
