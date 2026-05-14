from flask import Flask


def create_app():
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False

    from . import routes

    app.register_blueprint(routes.bp)
    return app
