# Copyright (c) 2015-2018 Anish Athalye (me@anishathalye.com)
#
# This software is released under AGPLv3. See the included LICENSE.txt for
# details.

if __name__ == '__main__':
    from gavel.constants import (
        PHASE_INITIAL,
        SETTING_FALSE,
        SETTING_PHASE,
        SETTING_VOTING_STARTED,
    )
    from gavel.models import Setting, db
    db.create_all()
    if Setting.value_of(SETTING_VOTING_STARTED) is None:
        Setting.set(SETTING_VOTING_STARTED, SETTING_FALSE)
    if Setting.value_of(SETTING_PHASE) is None:
        Setting.set(SETTING_PHASE, PHASE_INITIAL)
    db.session.commit()
