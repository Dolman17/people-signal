from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import User, Organisation

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        organisation_name = request.form.get("organisation_name")
        email = request.form.get("email")
        password = request.form.get("password")

        if not organisation_name or not email or not password:
            flash("All fields are required.", "error")
            return redirect(url_for("auth.register"))

        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            flash("An account with that email already exists.", "error")
            return redirect(url_for("auth.register"))

        organisation = Organisation(name=organisation_name)

        db.session.add(organisation)

        db.session.flush()

        user = User(
            organisation_id=organisation.id,
            email=email,
            password_hash=generate_password_hash(password),
            role="admin"
        )

        db.session.add(user)

        db.session.commit()

        login_user(user)

        flash("Account created successfully.", "success")

        return redirect(url_for("dashboard.dashboard"))

    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid credentials.", "error")
            return redirect(url_for("auth.login"))

        login_user(user)

        flash("Logged in successfully.", "success")

        return redirect(url_for("dashboard.dashboard_home"))

    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()

    flash("Logged out successfully.", "success")

    return redirect(url_for("auth.login"))