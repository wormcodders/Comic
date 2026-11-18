"""Security configuration and explicit administrator setup."""

import os
import secrets

import click
from flask import current_app
from sqlalchemy import or_

from models import db, User
from security_utils import validate_username, validate_email, validate_password


KNOWN_SECRET_KEYS = {
    'dev-secret-key-change-in-production',
    'change-this-secret-key-in-production',
    'isolated-testing-key-never-use-in-production',
}


def configure_security(app):
    production = app.config.get('ENV_NAME') == 'production'
    secret = app.config.get('SECRET_KEY')
    if not secret:
        if production:
            raise RuntimeError('Production requires a generated SECRET_KEY of at least 32 characters.')
        if app.testing:
            secret = secrets.token_urlsafe(32)
        else:
            os.makedirs(app.instance_path, mode=0o700, exist_ok=True)
            secret_path = os.path.join(app.instance_path, '.secret_key')
            try:
                fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                with open(secret_path, encoding='utf-8') as handle:
                    secret = handle.read().strip()
            else:
                secret = secrets.token_urlsafe(32)
                with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                    handle.write(secret)
        app.config['SECRET_KEY'] = secret
    if not isinstance(secret, (str, bytes)) or len(secret) < 32 or (secret in KNOWN_SECRET_KEYS and not app.testing):
        raise RuntimeError('SECRET_KEY must be a generated value of at least 32 characters, not a placeholder.')
    if production and not app.testing:
        storage = app.config.get('RATELIMIT_STORAGE_URI')
        if not storage or storage.startswith('memory:'):
            raise RuntimeError('Production requires shared RATELIMIT_STORAGE_URI storage, such as Redis.')
        if app.debug:
            raise RuntimeError('Debug mode must be disabled in production.')


def _validate_admin(username, email, password):
    for value, validator in ((username, validate_username), (email, validate_email), (password, validate_password)):
        valid, message = validator(value)
        if not valid:
            raise ValueError(message)
    if password == 'admin123':
        raise ValueError('The legacy default administrator password is not allowed.')


def create_configured_admin():
    values = [current_app.config.get(key) for key in ('ADMIN_USERNAME', 'ADMIN_EMAIL', 'ADMIN_PASSWORD')]
    if not any(values) or User.query.filter_by(is_admin=True).first():
        return None
    if not all(values):
        raise RuntimeError('Supply ADMIN_USERNAME, ADMIN_EMAIL, and ADMIN_PASSWORD together, or use the create-admin command.')
    username, email, password = values
    username, email = username.strip(), email.strip().lower()
    _validate_admin(username, email, password)
    if User.query.filter(or_(db.func.lower(User.username) == username.lower(), db.func.lower(User.email) == email)).first():
        raise RuntimeError('The configured administrator identity already belongs to an existing account.')
    admin = User(username=username, email=email, is_admin=True)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    return admin


def register_admin_command(app):
    @app.cli.command('create-admin')
    @click.option('--username', prompt=True)
    @click.option('--email', prompt=True)
    @click.option('--reset-password', is_flag=True, help='Reset an existing administrator password.')
    def create_admin(username, email, reset_password):
        """Create an administrator, or recover an existing administrator locally."""
        password = click.prompt('Password', hide_input=True, confirmation_prompt=True)
        username, email = username.strip(), email.strip().lower()
        try:
            _validate_admin(username, email, password)
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        user = User.query.filter(or_(db.func.lower(User.username) == username.lower(), db.func.lower(User.email) == email)).first()
        if user:
            if not reset_password or not user.is_admin or user.username.lower() != username.lower() or user.email.lower() != email:
                raise click.ClickException('This identity already exists. Use --reset-password with the existing administrator username and email.')
        elif reset_password:
            raise click.ClickException('Administrator not found.')
        else:
            user = User(username=username, email=email, is_admin=True)
            db.session.add(user)
        user.set_password(password)
        user.security_answer_hash = None
        db.session.commit()
        click.echo(f'Administrator account saved: {user.username}')
