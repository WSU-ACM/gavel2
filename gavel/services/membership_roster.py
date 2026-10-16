import csv
import hashlib
import io
from dataclasses import dataclass
from urllib.parse import urlparse

from email_validator import EmailNotValidError, validate_email

from gavel.models import (
    Annotator,
    InvitationDelivery,
    Item,
    MembershipRosterImport,
    db,
    with_retries,
)
from gavel.voting_state import lock_voting_state, voting_has_started


MANAGED_SOURCE = 'membership_bot'
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10000
MAX_EXTERNAL_ID = 255
MAX_PROJECT_NAME = 255
MAX_PARTICIPANT_NAME = 120
MAX_EMAIL = 120
MAX_DESCRIPTION = 5000
MAX_URL = 2048

PROJECT_HEADERS = (
    'external_id',
    'name',
    'description',
    'submission_url',
)
PARTICIPANT_HEADERS = (
    'external_id',
    'name',
    'email',
    'description',
    'project_external_id',
)

class RosterValidationError(ValueError):
    def __init__(self, code, row=None, field=None):
        super().__init__(code)
        self.code = code
        self.row = row
        self.field = field


@dataclass(frozen=True)
class ProjectRow:
    row_number: int
    external_id: str
    name: str
    description: str
    submission_url: str


@dataclass(frozen=True)
class ParticipantRow:
    row_number: int
    external_id: str
    name: str
    email: str
    description: str
    project_external_id: str


@dataclass(frozen=True)
class RosterSnapshot:
    projects: tuple
    participants: tuple
    projects_sha256: str
    participants_sha256: str


def read_upload(upload):
    if upload is None:
        raise RosterValidationError('missing_file')
    data = upload.stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise RosterValidationError('file_too_large')
    return data


def parse_snapshot(project_bytes, participant_bytes):
    projects = _parse_projects(project_bytes)
    participants = _parse_participants(participant_bytes)

    project_ids = {row.external_id for row in projects}
    participant_ids = {row.external_id for row in participants}
    if project_ids & participant_ids:
        raise RosterValidationError('resource_type_conflict')

    for row in participants:
        if row.project_external_id not in project_ids:
            raise RosterValidationError(
                'unknown_project_external_id',
                row=row.row_number,
                field='project_external_id',
            )

    return RosterSnapshot(
        projects=tuple(projects),
        participants=tuple(participants),
        projects_sha256=hashlib.sha256(project_bytes).hexdigest(),
        participants_sha256=hashlib.sha256(participant_bytes).hexdigest(),
    )


def _csv_rows(data, expected_headers):
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        raise RosterValidationError('invalid_utf8')

    try:
        rows = csv.reader(io.StringIO(text, newline=''), strict=True)
        header = next(rows, None)
        if header is None:
            raise RosterValidationError('missing_header', row=1)
        if tuple(header) != expected_headers:
            raise RosterValidationError('invalid_header', row=1)

        parsed = []
        for row_number, row in enumerate(rows, 2):
            if row_number > MAX_ROWS + 1:
                raise RosterValidationError('too_many_rows')
            if not row or all(not cell.strip() for cell in row):
                raise RosterValidationError('blank_row', row=row_number)
            if len(row) < len(expected_headers):
                raise RosterValidationError('missing_cell', row=row_number)
            if len(row) > len(expected_headers):
                raise RosterValidationError('extra_cell', row=row_number)
            values = tuple(cell.strip() for cell in row)
            for index, value in enumerate(values):
                if not value:
                    raise RosterValidationError(
                        'blank_value',
                        row=row_number,
                        field=expected_headers[index],
                    )
            parsed.append((row_number, values))
        return parsed
    except csv.Error:
        raise RosterValidationError('invalid_csv')


def _require_length(value, maximum, row_number, field):
    if len(value) > maximum:
        raise RosterValidationError('field_too_long', row=row_number, field=field)


def _parse_projects(data):
    projects = []
    external_ids = set()
    names = set()
    for row_number, values in _csv_rows(data, PROJECT_HEADERS):
        external_id, name, description, submission_url = values
        _require_length(external_id, MAX_EXTERNAL_ID, row_number, 'external_id')
        _require_length(name, MAX_PROJECT_NAME, row_number, 'name')
        _require_length(description, MAX_DESCRIPTION, row_number, 'description')
        _require_length(submission_url, MAX_URL, row_number, 'submission_url')

        if external_id in external_ids:
            raise RosterValidationError('duplicate_external_id', row=row_number, field='external_id')
        normalized_name = name.casefold()
        if normalized_name in names:
            raise RosterValidationError('duplicate_project_name', row=row_number, field='name')
        try:
            parsed_url = urlparse(submission_url)
        except ValueError:
            parsed_url = None
        if parsed_url is None or parsed_url.scheme not in ('http', 'https') or not parsed_url.netloc:
            raise RosterValidationError('invalid_url', row=row_number, field='submission_url')

        external_ids.add(external_id)
        names.add(normalized_name)
        projects.append(ProjectRow(row_number, *values))
    return projects


def _parse_participants(data):
    participants = []
    external_ids = set()
    emails = set()
    for row_number, values in _csv_rows(data, PARTICIPANT_HEADERS):
        external_id, name, email, description, project_external_id = values
        _require_length(external_id, MAX_EXTERNAL_ID, row_number, 'external_id')
        _require_length(name, MAX_PARTICIPANT_NAME, row_number, 'name')
        _require_length(email, MAX_EMAIL, row_number, 'email')
        _require_length(description, MAX_DESCRIPTION, row_number, 'description')
        _require_length(project_external_id, MAX_EXTERNAL_ID, row_number, 'project_external_id')

        if external_id in external_ids:
            raise RosterValidationError('duplicate_external_id', row=row_number, field='external_id')
        normalized_email = email.casefold()
        if normalized_email in emails:
            raise RosterValidationError('duplicate_email', row=row_number, field='email')
        try:
            validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            raise RosterValidationError('invalid_email', row=row_number, field='email')

        external_ids.add(external_id)
        emails.add(normalized_email)
        participants.append(ParticipantRow(row_number, *values))
    return participants


def import_snapshot(snapshot):
    def transaction():
        return _apply_snapshot(snapshot)

    db.session.info['suppress_socket_events'] = True
    try:
        return with_retries(transaction)
    except Exception:
        db.session.rollback()
        raise
    finally:
        db.session.info.pop('suppress_socket_events', None)


def _apply_snapshot(snapshot):
    voting_setting = lock_voting_state()
    all_items = Item.query.filter(Item.external_id.isnot(None)).with_for_update().all()
    all_annotators = Annotator.query.filter(Annotator.external_id.isnot(None)).with_for_update().all()
    items_by_id = {item.external_id: item for item in all_items}
    annotators_by_id = {annotator.external_id: annotator for annotator in all_annotators}

    incoming_project_ids = {row.external_id for row in snapshot.projects}
    incoming_participant_ids = {row.external_id for row in snapshot.participants}

    for row in snapshot.projects:
        if row.external_id in annotators_by_id:
            raise RosterValidationError('resource_type_conflict', row=row.row_number, field='external_id')
        existing = items_by_id.get(row.external_id)
        if existing is not None and existing.managed_source != MANAGED_SOURCE:
            raise RosterValidationError('source_conflict', row=row.row_number, field='external_id')
    for row in snapshot.participants:
        if row.external_id in items_by_id:
            raise RosterValidationError('resource_type_conflict', row=row.row_number, field='external_id')
        existing = annotators_by_id.get(row.external_id)
        if existing is not None and existing.managed_source != MANAGED_SOURCE:
            raise RosterValidationError('source_conflict', row=row.row_number, field='external_id')

    managed_items = {
        item.external_id: item
        for item in all_items
        if item.managed_source == MANAGED_SOURCE
    }
    managed_annotators = {
        annotator.external_id: annotator
        for annotator in all_annotators
        if annotator.managed_source == MANAGED_SOURCE
    }

    project_plans = []
    participant_plans = []
    eligibility_change = False
    counts = {
        'projects_created': 0,
        'projects_updated': 0,
        'projects_unchanged': 0,
        'projects_deactivated': 0,
        'participants_created': 0,
        'participants_updated': 0,
        'participants_unchanged': 0,
        'participants_deactivated': 0,
    }

    for row in snapshot.projects:
        item = managed_items.get(row.external_id)
        if item is None:
            counts['projects_created'] += 1
            eligibility_change = True
            changed = True
        else:
            changed = (
                item.name != row.name
                or item.description != row.description
                or item.submission_reference != row.submission_url
                or item.roster_active is not True
            )
            if item.roster_active is not True:
                eligibility_change = True
            counts['projects_updated' if changed else 'projects_unchanged'] += 1
        project_plans.append((row, item, changed))

    for external_id, item in managed_items.items():
        if external_id not in incoming_project_ids and item.roster_active is not False:
            counts['projects_deactivated'] += 1
            eligibility_change = True

    for row in snapshot.participants:
        annotator = managed_annotators.get(row.external_id)
        target_item = managed_items.get(row.project_external_id)
        if annotator is None:
            counts['participants_created'] += 1
            eligibility_change = True
            changed = True
            project_changed = True
        else:
            project_changed = (
                target_item is None
                or annotator.project_id != target_item.id
            )
            changed = (
                annotator.name != row.name
                or annotator.email != row.email
                or annotator.description != row.description
                or annotator.roster_active is not True
                or project_changed
            )
            if annotator.roster_active is not True or project_changed:
                eligibility_change = True
            counts['participants_updated' if changed else 'participants_unchanged'] += 1
        participant_plans.append((row, annotator, changed, project_changed))

    for external_id, annotator in managed_annotators.items():
        if external_id not in incoming_participant_ids and annotator.roster_active is not False:
            counts['participants_deactivated'] += 1
            eligibility_change = True

    if eligibility_change and voting_has_started(voting_setting):
        raise RosterValidationError('roster_locked_after_voting')

    resolved_projects = {}
    for row, item, changed in project_plans:
        if item is None:
            item = Item(
                row.name,
                'N/A',
                row.description,
                submission_reference=row.submission_url,
            )
            item.external_id = row.external_id
            item.managed_source = MANAGED_SOURCE
            item.roster_active = True
            db.session.add(item)
        elif changed:
            item.name = row.name
            item.description = row.description
            item.submission_reference = row.submission_url
            item.roster_active = True
        resolved_projects[row.external_id] = item

    new_annotators = []
    for row, annotator, changed, project_changed in participant_plans:
        project = resolved_projects[row.project_external_id]
        if annotator is None:
            annotator = Annotator(row.name, row.email, row.description)
            annotator.external_id = row.external_id
            annotator.managed_source = MANAGED_SOURCE
            annotator.roster_active = True
            annotator.project = project
            db.session.add(annotator)
            new_annotators.append(annotator)
        elif changed:
            annotator.name = row.name
            annotator.email = row.email
            annotator.description = row.description
            annotator.roster_active = True
            if project_changed:
                annotator.project = project
                annotator.prev = None
                annotator.update_next(None)

    for external_id, annotator in managed_annotators.items():
        if external_id not in incoming_participant_ids:
            annotator.roster_active = False
    for external_id, item in managed_items.items():
        if external_id not in incoming_project_ids:
            item.roster_active = False

    audit = MembershipRosterImport(
        projects_sha256=snapshot.projects_sha256,
        participants_sha256=snapshot.participants_sha256,
        **counts
    )
    db.session.add(audit)
    db.session.flush()

    invitation_rows = []
    for annotator in new_annotators:
        delivery = InvitationDelivery(
            annotator=annotator,
            roster_import=audit,
            status='pending',
        )
        db.session.add(delivery)
        invitation_rows.append(delivery)
    db.session.flush()
    invitation_ids = [delivery.id for delivery in invitation_rows]
    db.session.commit()

    result = dict(counts)
    result['import_id'] = audit.id
    result['invitation_ids'] = invitation_ids
    return result
