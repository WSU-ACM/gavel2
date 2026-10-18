from gavel import app
from flask import send_from_directory
import os

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'hacktoberfest.svg',
        mimetype='image/svg+xml'
    )
