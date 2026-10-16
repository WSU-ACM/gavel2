from gavel import app
from flask import render_template


@app.errorhandler(400)
def error_400(e):
    return (
        render_template(
            'error.html',
            message='Gavel could not submit that response. Return and try again.',
        ),
        400
    )


@app.errorhandler(404)
def error_404(e):
    return (
        render_template(
            'error.html',
            message='This page could not be found. Return to Gavel to continue.',
        ),
        404
    )


@app.errorhandler(403)
def error_403(e):
    return (
        render_template(
            'error.html',
            message='Gavel could not verify this request. Return and try again.',
        ),
        403
    )


@app.errorhandler(500)
def error_500(e):
    return (
        render_template(
            'error.html',
            message=(
                'Something went wrong, and your latest action may not have been '
                'saved. Return to Gavel and check the current state.'
            ),
        ),
        500
    )
