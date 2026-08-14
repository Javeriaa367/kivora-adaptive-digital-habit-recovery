import os

# Load variables from a local .env file (GEMINI_API_KEY, SECRET_KEY, etc.)
# into the process environment before anything else reads them. Must run
# before `from config import Config`, since Config reads os.environ.get(...)
# at class-definition time. load_dotenv() silently does nothing if no .env
# file exists (e.g. in production, where real env vars/secrets are used
# instead) -- so this is safe to leave in for every environment.
from dotenv import load_dotenv
load_dotenv()

from flask import Flask

from config import Config
from database.db import init_db


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Durable persistence (database/persistence.py): backup the SQLite DB
    # to a durable store and restore on boot so a Cloud Run redeploy can't
    # wipe user data. Runs before init_db so restore-on-boot can find the
    # store. Fails closed in production without a store configured.
    from database.persistence import configure_persistence
    configure_persistence(app)

    init_db(app)

    from routes.auth import auth_bp
    from routes.main import main_bp
    from routes.api import api_bp
    from routes.journal import journal_bp
    from routes.chat import chat_bp
    from routes.habits import habits_bp
    from routes.billing import billing_bp
    from routes.admin import admin_bp
    from routes.feedback import feedback_bp
    from routes.tools import tools_bp
    from routes.notifications import notifications_bp
    from routes.faq import faq_bp
    from routes.student import student_bp
    from routes.companion import companion_bp
    from routes.memory import memory_bp
    from routes.risk import risk_bp
    from routes.recovery import recovery_bp
    from routes.brain import brain_bp
    from routes.settings import settings_bp
    from routes.recovery_demo import demo_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(journal_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(habits_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(tools_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(faq_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(companion_bp)
    app.register_blueprint(memory_bp)
    app.register_blueprint(risk_bp)
    app.register_blueprint(recovery_bp)
    app.register_blueprint(brain_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(demo_bp)

    # CSRF: every state-changing request must echo a session token (see
    # security.py). Runs first so no view can be reached without passing it.
    from security import validate_csrf

    app.before_request(validate_csrf)

    # Journal emotion analysis: switch from the plain lexical analyzer to
    # the hybrid (lexical + VADER + transformer) pipeline. This is safe to
    # call even when vaderSentiment/transformers/torch aren't installed --
    # HybridEmotionAnalyzer probes each one lazily and falls back cleanly
    # (see ml/emotion_analyzer_hybrid.py). Model loading happens on a
    # background thread so app startup and the first request aren't
    # blocked on a potentially slow HF model download.
    from ml.emotion_analyzer_hybrid import use_hybrid_analyzer
    hybrid_analyzer = use_hybrid_analyzer(warm_up=False)
    if not app.config.get("TESTING"):
        import threading
        threading.Thread(target=hybrid_analyzer.warm_up, daemon=True).start()

    @app.context_processor
    def inject_current_user_name():
        from auth_utils import current_user
        from security import get_csrf_token
        user = current_user()
        return {
            "current_user_name": user["name"] if user else None,
            "current_user_is_admin": bool(user["is_admin"]) if user else False,
            "csrf_token": get_csrf_token,
        }

    return app


app = create_app()

if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=debug_mode, host="0.0.0.0", port=port)
