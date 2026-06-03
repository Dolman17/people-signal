from flask import Flask, redirect, url_for

from config import Config

from app.extensions import (
    db,
    migrate,
    login_manager
)


def create_app():
    app = Flask(__name__)

    app.config.from_object(Config)

    db.init_app(app)

    migrate.init_app(app, db)

    login_manager.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.context_processor
    def inject_ingestion_profiles():
        try:
            from app.services.ingestion_profile_service import get_active_ingestion_profiles

            return {
                "active_ingestion_profiles": get_active_ingestion_profiles()
            }
        except Exception:
            return {
                "active_ingestion_profiles": []
            }

    from app.blueprints.auth.routes import auth_bp
    from app.blueprints.dashboard.routes import dashboard_bp
    from app.blueprints.companies.routes import companies_bp
    from app.blueprints.signals.routes import signals_bp
    from app.blueprints.admin.job_routes import admin_jobs_bp
    from app.blueprints.admin.routes import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(companies_bp)
    app.register_blueprint(signals_bp)
    app.register_blueprint(admin_jobs_bp)
    app.register_blueprint(admin_bp)

    @app.route("/")
    def index():
        return redirect(url_for("dashboard.dashboard_home"))

    return app
