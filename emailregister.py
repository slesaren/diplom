import os
from venv import logger

from dotenv import load_dotenv

import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, desc
import redis
import json
import re
import os
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

from config import Config
from redis_utils import RedisBookStats

import smtplib
import ssl
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from typing import Optional, List, Dict
import os
from pathlib import Path

from config import SMTPConfig, EmailProvider

logger = logging.getLogger(__name__)


class EmailService:

    def __init__(self, provider: Optional[EmailProvider] = None):
        self.provider = provider
        self.config = SMTPConfig.get_config(provider)
        self.smtp_username = os.environ.get('SMTP_USERNAME')
        self.smtp_password = os.environ.get('SMTP_PASSWORD')

        if provider == EmailProvider.GMAIL:
            self._check_gmail_app_password()

    def _check_gmail_app_password(self):
        if self.smtp_password and len(self.smtp_password) < 16:
            logger.warning("Для Gmail рекомендуется использовать пароль приложения, а не обычный пароль")

    def send_email(
            self,
            to_email: str,
            subject: str,
            body_text: str,
            body_html: Optional[str] = None,
            from_name: str = "QArticle",
            attachments: Optional[List[str]] = None,
            cc: Optional[List[str]] = None,
            bcc: Optional[List[str]] = None
    ) -> bool:
        try:
            if not self.smtp_username or not self.smtp_password:
                logger.error("SMTP credentials not configured")
                return False

            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{from_name} <{self.smtp_username}>"
            msg['To'] = to_email

            if cc:
                msg['Cc'] = ', '.join(cc)
            if bcc:
                msg['Bcc'] = ', '.join(bcc)

            part_text = MIMEText(body_text, 'plain', 'utf-8')
            msg.attach(part_text)

            if body_html:
                part_html = MIMEText(body_html, 'html', 'utf-8')
                msg.attach(part_html)

            if attachments:
                for file_path in attachments:
                    self._attach_file(msg, file_path)

            recipients = [to_email]
            if cc:
                recipients.extend(cc)
            if bcc:
                recipients.extend(bcc)

            self._send_smtp(msg, recipients)
            logger.info(f"Email sent successfully to {to_email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}", exc_info=True)
            return False

    def _attach_file(self, msg: MIMEMultipart, file_path: str):
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                logger.warning(f"Attachment not found: {file_path}")
                return

            with open(file_path, 'rb') as f:
                file_data = f.read()
                file_name = file_path.name

                if file_path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif']:
                    mime_type = 'image'
                    sub_type = file_path.suffix[1:]
                    attachment = MIMEImage(file_data, _subtype=sub_type)
                else:
                    from email.mime.base import MIMEBase
                    from email import encoders
                    attachment = MIMEBase('application', 'octet-stream')
                    attachment.set_payload(file_data)
                    encoders.encode_base64(attachment)

                attachment.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{file_name}"'
                )
                msg.attach(attachment)

        except Exception as e:
            logger.error(f"Failed to attach file {file_path}: {str(e)}")

    def _send_smtp(self, msg: MIMEMultipart, recipients: List[str]):
        server = None

        try:
            if self.config['use_ssl']:
                context = ssl.create_default_context()
                server = smtplib.SMTP_SSL(
                    self.config['server'],
                    self.config['port'],
                    context=context
                )
            else:
                server = smtplib.SMTP(
                    self.config['server'],
                    self.config['port']
                )
                if self.config['use_tls']:
                    server.starttls()

            if self.config.get('auth_required', True):
                server.login(self.smtp_username, self.smtp_password)

            server.send_message(msg, from_addr=self.smtp_username, to_addrs=recipients)

        finally:
            if server:
                server.quit()


class VerificationEmailService(EmailService):

    def send_verification(self, to_email: str, username: str, verification_url: str) -> bool:
        subject = "Подтверждение регистрации на QArticle"
        body_text = f"""
        Здравствуйте, {username}!

        Спасибо за регистрацию на платформе QArticle.

        Для подтверждения вашего email-адреса, пожалуйста, перейдите по ссылке:
        {verification_url}

        Ссылка действительна в течение 24 часов.

        Если вы не регистрировались на нашем сайте, просто проигнорируйте это письмо.

        С уважением,
        Команда QArticle
        """


        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                .container {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                    max-width: 560px;
                    margin: 0 auto;
                    background: #ffffff;
                    border-radius: 12px;
                    overflow: hidden;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    padding: 32px 24px;
                    text-align: center;
                }}
                .header h1 {{
                    color: white;
                    margin: 0;
                    font-size: 28px;
                }}
                .content {{
                    padding: 32px 24px;
                }}
                .greeting {{
                    font-size: 18px;
                    color: #2d3748;
                    margin-bottom: 20px;
                }}
                .message {{
                    color: #4a5568;
                    line-height: 1.6;
                    margin-bottom: 24px;
                }}
                .button-container {{
                    text-align: center;
                    margin: 32px 0;
                }}
                .button {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 14px 32px;
                    text-decoration: none;
                    border-radius: 8px;
                    display: inline-block;
                    font-weight: 600;
                    transition: transform 0.2s;
                }}
                .button:hover {{
                    transform: translateY(-2px);
                }}
                .link {{
                    background: #f7fafc;
                    padding: 12px;
                    border-radius: 6px;
                    font-size: 12px;
                    word-break: break-all;
                    color: #4a5568;
                    margin: 16px 0;
                }}
                .footer {{
                    background: #f7fafc;
                    padding: 24px;
                    text-align: center;
                    color: #718096;
                    font-size: 12px;
                }}
                .warning {{
                    background: #fef5e7;
                    border-left: 4px solid #f39c12;
                    padding: 12px;
                    margin: 20px 0;
                    font-size: 13px;
                }}
            </style>
        </head>
        <body style="margin: 0; padding: 20px; background: #f7fafc;">
            <div class="container">
                <div class="header">
                    <h1>QArticle</h1>
                    <p style="color: rgba(255,255,255,0.9); margin: 8px 0 0;">Сообщество совместного обучения</p>
                </div>

                <div class="content">
                    <div class="greeting">
                        <strong>Здравствуйте, {username}!</strong>
                    </div>

                    <div class="message">
                        Спасибо за регистрацию на платформе <strong>QArticle</strong>!
                        Для завершения регистрации и активации аккаунта, пожалуйста, подтвердите ваш email адрес.
                    </div>

                    <div class="button-container">
                        <a href="{verification_url}" class="button">Подтвердить email</a>
                    </div>

                    <div class="link">
                        Или скопируйте ссылку в браузер:<br>
                        {verification_url}
                    </div>

                    <div class="warning">
                         Ссылка действительна в течение 24 часов.
                    </div>

                    <div class="message" style="font-size: 14px; color: #718096;">
                        Если вы не регистрировались на QArticle, просто проигнорируйте это письмо.
                    </div>
                </div>

                <div class="footer">
                    <p>© 2026 QArticle — платформа совместного обучения</p>
                </div>
            </div>
        </body>
        </html>
        """

        return self.send_email(to_email, subject, body_text, body_html)


class PasswordResetEmailService(EmailService):

    def send_password_reset(self, to_email: str, username: str, reset_url: str) -> bool:

        subject = "Восстановление пароля на QArticle"

        body_text = f"""
        Здравствуйте, {username}!

        Мы получили запрос на восстановление пароля для вашей учетной записи на QArticle.

        Для создания нового пароля, пожалуйста, перейдите по ссылке:
        {reset_url}

        Ссылка действительна в течение 1 часа.

        Если вы не запрашивали восстановление пароля, просто проигнорируйте это письмо. 
        Ваш пароль останется без изменений.

        С уважением,
        Команда QArticle
        """

        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                .container {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                    max-width: 560px;
                    margin: 0 auto;
                    background: #ffffff;
                    border-radius: 12px;
                    overflow: hidden;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    padding: 32px 24px;
                    text-align: center;
                }}
                .header h1 {{
                    color: white;
                    margin: 0;
                    font-size: 28px;
                }}
                .content {{
                    padding: 32px 24px;
                }}
                .greeting {{
                    font-size: 18px;
                    color: #2d3748;
                    margin-bottom: 20px;
                }}
                .message {{
                    color: #4a5568;
                    line-height: 1.6;
                    margin-bottom: 24px;
                }}
                .button-container {{
                    text-align: center;
                    margin: 32px 0;
                }}
                .button {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 14px 32px;
                    text-decoration: none;
                    border-radius: 8px;
                    display: inline-block;
                    font-weight: 600;
                    transition: transform 0.2s;
                }}
                .button:hover {{
                    transform: translateY(-2px);
                }}
                .link {{
                    background: #f7fafc;
                    padding: 12px;
                    border-radius: 6px;
                    font-size: 12px;
                    word-break: break-all;
                    color: #4a5568;
                    margin: 16px 0;
                }}
                .footer {{
                    background: #f7fafc;
                    padding: 24px;
                    text-align: center;
                    color: #718096;
                    font-size: 12px;
                }}
                .warning {{
                    background: #fef5e7;
                    border-left: 4px solid #f39c12;
                    padding: 12px;
                    margin: 20px 0;
                    font-size: 13px;
                }}
            </style>
        </head>
        <body style="margin: 0; padding: 20px; background: #f7fafc;">
            <div class="container">
                <div class="header">
                    <h1>QArticle</h1>
                    <p style="color: rgba(255,255,255,0.9); margin: 8px 0 0;">Восстановление доступа</p>
                </div>

                <div class="content">
                    <div class="greeting">
                        <strong>Здравствуйте, {username}!</strong>
                    </div>

                    <div class="message">
                        Мы получили запрос на восстановление пароля для вашей учетной записи на <strong>QArticle</strong>.
                    </div>

                    <div class="button-container">
                        <a href="{reset_url}" class="button">Создать новый пароль</a>
                    </div>

                    <div class="link">
                        Или скопируйте ссылку в браузер:<br>
                        {reset_url}
                    </div>

                    <div class="warning">
                         Ссылка действительна в течение 1 часа.
                    </div>

                    <div class="message" style="font-size: 14px; color: #718096;">
                        Если вы не запрашивали восстановление пароля, просто проигнорируйте это письмо.
                        Ваш пароль останется без изменений.
                    </div>
                </div>

                <div class="footer">
                    <p>© 2026 QArticle — платформа совместного обучения</p>
                </div>
            </div>
        </body>
        </html>
        """

        return self.send_email(to_email, subject, body_text, body_html)