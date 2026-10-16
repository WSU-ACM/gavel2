from datetime import datetime

from gavel.models import db
from gavel.models._basemodel import BaseModel


class MembershipRosterImport(BaseModel):
    id = db.Column(db.Integer, primary_key=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    administrator = db.Column(db.String(64), nullable=False, default='admin')
    projects_sha256 = db.Column(db.String(64), nullable=False)
    participants_sha256 = db.Column(db.String(64), nullable=False)

    projects_created = db.Column(db.Integer, nullable=False, default=0)
    projects_updated = db.Column(db.Integer, nullable=False, default=0)
    projects_unchanged = db.Column(db.Integer, nullable=False, default=0)
    projects_deactivated = db.Column(db.Integer, nullable=False, default=0)
    participants_created = db.Column(db.Integer, nullable=False, default=0)
    participants_updated = db.Column(db.Integer, nullable=False, default=0)
    participants_unchanged = db.Column(db.Integer, nullable=False, default=0)
    participants_deactivated = db.Column(db.Integer, nullable=False, default=0)


class InvitationDelivery(BaseModel):
    id = db.Column(db.Integer, primary_key=True, nullable=False)
    annotator_id = db.Column(
        db.Integer,
        db.ForeignKey('annotator.id', ondelete='CASCADE'),
        unique=True,
        nullable=False,
    )
    import_id = db.Column(
        db.Integer,
        db.ForeignKey('membership_roster_import.id', ondelete='SET NULL'),
        index=True,
        nullable=True,
    )
    status = db.Column(db.String(16), nullable=False, default='pending', index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    failure_code = db.Column(db.String(64), nullable=True)
    claim_token = db.Column(db.String(32), nullable=True)
    claimed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    sent_at = db.Column(db.DateTime, nullable=True)

    annotator = db.relationship('Annotator', uselist=False)
    roster_import = db.relationship('MembershipRosterImport', uselist=False)
