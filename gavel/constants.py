ANNOTATOR_ID = 'annotator_id'
TELEMETRY_URL = 'https://telemetry.anish.io/api/v1/submit'

# Socket events
CONNECT = 'connected'

ANNOTATOR_INSERTED = 'annotator.inserted'
ANNOTATOR_UPDATED = 'annotator.updated'
ANNOTATOR_DELETED = 'annotator.deleted'

ITEM_INSERTED = 'item.inserted'
ITEM_UPDATED = 'item.updated'
ITEM_DELETED = 'item.deleted'

FLAG_INSERTED = 'flag.inserted'
FLAG_UPDATED = 'flag.updated'
FLAG_DELETED = 'flag.deleted'

SETTING_INSERTED = 'setting.inserted'
SETTING_UPDATED = 'setting.updated'
SETTING_DELETED = 'setting.deleted'

SESSION_UPDATED = 'session.updated'

# Setting
# keys
SETTING_CLOSED = 'closed' # boolean
SETTING_STOP_QUEUE = 'queued' # boolean
SETTING_PHASE = 'phase'
SETTING_VOTING_STARTED = 'voting_started'
# values
SETTING_TRUE = 'true'
SETTING_FALSE = 'false'

PHASE_INITIAL = 'initial'
PHASE_BRACKET = 'bracket'
PHASE_CLOSED = 'closed'

# Defaults
# these can be overridden via the config file
DEFAULT_WELCOME_MESSAGE = '''
Welcome to hackathon voting.

As a hackathon participant, you'll help rank projects by comparing them one at
a time. Your first project gives you a starting point. After that, you'll
compare each new project with the one you reviewed immediately before it.

Use the criteria provided by the hackathon organizers and make each choice
independently. Gavel combines your comparisons with those from other
participants to produce the project rankings.

You will never be asked to vote on your own team's project. If your project is
part of an elimination-bracket matchup, you will sit out that matchup.

Please consider each comparison carefully. **After you submit a choice, you
cannot change it.**
'''.strip()

DEFAULT_EMAIL_SUBJECT = 'Your Gavel participant voting link'

DEFAULT_EMAIL_BODY = '''
Hi {name},

You're invited to vote on hackathon projects using Gavel. This personal link
signs you in to your participant voting account:

{link}

Do not share this link. Anyone who has it can vote from your account.

Before voting, please read the welcome message and instructions in Gavel. Ask a
hackathon organizer if you have questions about the voting criteria or process.
'''.strip()

DEFAULT_CLOSED_MESSAGE = '''
Hackathon voting is closed. No more choices can be submitted. Follow any next steps provided by the organizers.
'''.strip()

DEFAULT_CLOSING_MESSAGE = '''
Hackathon voting is ending. Your completed choices have been saved. Please wait for instructions from the organizers.
'''.strip()

DEFAULT_DISABLED_MESSAGE = '''
Your participant voting access is paused. Contact a hackathon organizer if you believe this is a mistake.
'''.strip()

DEFAULT_LOGGED_OUT_MESSAGE = '''
You are signed out of participant voting. Open your personal Gavel link to sign in again, or ask a hackathon organizer for help.
'''.strip()

DEFAULT_WAIT_MESSAGE = '''
You have reviewed every project currently available to you. Follow the organizers' instructions while you wait for the next stage of hackathon voting.
'''.strip()
