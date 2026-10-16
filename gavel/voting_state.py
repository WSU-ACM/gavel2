from gavel.constants import SETTING_FALSE, SETTING_TRUE, SETTING_VOTING_STARTED
from gavel.models import BracketVote, Decision, Setting, db


def lock_voting_state():
    setting = Setting.query.filter_by(key=SETTING_VOTING_STARTED).with_for_update().first()
    if setting is None:
        has_votes = (
            Decision.query.first() is not None
            or BracketVote.query.first() is not None
        )
        setting = Setting(
            SETTING_VOTING_STARTED,
            SETTING_TRUE if has_votes else SETTING_FALSE,
        )
        db.session.add(setting)
        db.session.flush()
    return setting


def voting_has_started(setting=None):
    setting = setting or lock_voting_state()
    return setting.value == SETTING_TRUE


def mark_voting_started(setting):
    setting.value = SETTING_TRUE
