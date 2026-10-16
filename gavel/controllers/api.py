import hmac
from urllib.parse import urlparse

from gavel import app
from gavel.models import *
from gavel.services.membership_roster import MANAGED_SOURCE
import gavel.settings as settings
import gavel.utils as utils
from flask import jsonify, request, Response


def _membership_api_error(message, status):
    response = jsonify({'error': message})
    response.status_code = status
    response.headers['Cache-Control'] = 'no-store'
    if status == 401:
        response.headers['WWW-Authenticate'] = 'Bearer'
    return response


@app.route('/api/membership-login-links')
def membership_login_links():
    expected_token = settings.MEMBERSHIP_LINK_EXPORT_TOKEN
    if not expected_token:
        return _membership_api_error('membership_link_export_not_configured', 503)

    authorization = request.headers.get('Authorization', '')
    scheme, separator, supplied_token = authorization.partition(' ')
    if (
        not separator
        or scheme.lower() != 'bearer'
        or not hmac.compare_digest(
            supplied_token.encode('utf-8'),
            str(expected_token).encode('utf-8'),
        )
    ):
        return _membership_api_error('unauthorized', 401)

    base_url = settings.BASE_URL.rstrip('/')
    try:
        parsed_base_url = urlparse(base_url)
    except (TypeError, ValueError):
        parsed_base_url = None
    if (
        parsed_base_url is None
        or parsed_base_url.scheme not in ('http', 'https')
        or not parsed_base_url.netloc
        or parsed_base_url.path
        or parsed_base_url.params
        or parsed_base_url.query
        or parsed_base_url.fragment
    ):
        return _membership_api_error('membership_link_base_url_invalid', 503)

    annotators = Annotator.query.filter(
        Annotator.managed_source == MANAGED_SOURCE,
        Annotator.external_id.isnot(None),
        Annotator.effectively_active,
    ).order_by(Annotator.external_id).all()
    response = jsonify({
        'participants': [
            {
                'external_id': annotator.external_id,
                'login_url': base_url + '/login/' + annotator.secret + '/',
            }
            for annotator in annotators
        ],
    })
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.route('/api/items.csv')
@utils.requires_auth
def item_dump():
    items = Item.query.order_by(desc(Item.mu)).all()
    data = [['Mu', 'Sigma Squared', 'Name', 'Location', 'Description', 'Submission URL', 'Active']]
    data += [[
        str(item.mu),
        str(item.sigma_sq),
        item.name,
        item.location,
        item.description,
        item.submission_reference,
        item.effectively_active
    ] for item in items]
    return Response(utils.data_to_csv_string(data), mimetype='text/csv')

@app.route('/api/annotators.csv')
@utils.requires_auth
def annotator_dump():
    annotators = Annotator.query.all()
    data = [['Name', 'Email', 'Description', 'Secret']]
    data += [[
        str(a.name),
        a.email,
        a.description,
        a.secret
    ] for a in annotators]
    return Response(utils.data_to_csv_string(data), mimetype='text/csv')

@app.route('/api/decisions.csv')
@utils.requires_auth
def decisions_dump():
    decisions = Decision.query.all()
    data = [['Annotator ID', 'Winner ID', 'Loser ID', 'Time']]
    data += [[
        str(d.annotator.id),
        str(d.winner.id),
        str(d.loser.id),
        str(d.time)
    ] for d in decisions]
    return Response(utils.data_to_csv_string(data), mimetype='text/csv')
