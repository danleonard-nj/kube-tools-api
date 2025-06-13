import datetime
import os
from dotenv import load_dotenv
from framework.abstractions.abstract_request import RequestContextProvider
from framework.configuration import Configuration
from framework.constants.constants import Environment
from framework.logger import get_logger
from framework.serialization.serializer import configure_serializer
from framework.swagger.quart.swagger import Swagger
from quart import Quart
from models.email_config import EmailConfig
from routes import (acr_bp, android_bp, api_event_history_bp, bank_bp,
                    calendar_bp, conversation_bp, google_bp, kubernetes_bp,
                    location_history_bp, mongo_backup_bp, podcasts_bp,
                    redis_bp, robinhood_bp, torrent_bp, usage_bp, weather_bp)
from sib_api_v3_sdk import ApiClient, Configuration as SibConfiguration
from sib_api_v3_sdk.api.transactional_emails_api import TransactionalEmailsApi
from sib_api_v3_sdk.models import SendSmtpEmail
from utilities.provider import ContainerProvider

load_dotenv()

logger = get_logger(__name__)

app = Quart(__name__)

configure_serializer(app)

app.register_blueprint(podcasts_bp)
app.register_blueprint(acr_bp)
app.register_blueprint(kubernetes_bp)
app.register_blueprint(usage_bp)
app.register_blueprint(mongo_backup_bp)
app.register_blueprint(google_bp)
app.register_blueprint(location_history_bp)
app.register_blueprint(calendar_bp)
app.register_blueprint(api_event_history_bp)
app.register_blueprint(bank_bp)
app.register_blueprint(weather_bp)
app.register_blueprint(torrent_bp)
app.register_blueprint(redis_bp)
app.register_blueprint(conversation_bp)
app.register_blueprint(robinhood_bp)
app.register_blueprint(android_bp)

provider = ContainerProvider.get_service_provider()


async def send_email_sendinblue(subject, message, recipient_email, sender_email, api_key):
    """
    Sends an email using Sendinblue transactional email API.
    """
    configuration = SibConfiguration()
    configuration.api_key['api-key'] = api_key

    send_smtp_email = SendSmtpEmail(
        to=[{"email": recipient_email}],
        sender={"email": sender_email},
        subject=subject,
        text_content=message
    )

    api_client = ApiClient(configuration)
    api_instance = TransactionalEmailsApi(api_client)
    try:
        api_instance.send_transac_email(send_smtp_email)
        logger.info(f"Sendinblue email sent to {recipient_email}")
    except Exception as e:
        logger.error(f"Failed to send email via Sendinblue: {e}")
    # Do not close api_client; Sendinblue ApiClient does not require or support close()


async def send_initial_email():
    config = provider.resolve(Configuration)
    email_config = provider.resolve(EmailConfig)
    env_vars = "\n".join([f"{k}={v}" for k, v in os.environ.items()])

    message = f'''Kube Tools API has started successfully at {datetime.datetime.now()}.\n\nRobinhood login w/ MFA is required.\n\nEnvironment Variables:\n{env_vars}\n'''

    logger.info(f'Sending initial email')

    if config.environment == Environment.PRODUCTION or True:
        await send_email_sendinblue(
            subject='Kube Tools API started',
            message=message,
            recipient_email='dcl525@gmail.com',
            sender_email='me@dan-leonard.com',
            api_key=email_config.sendinblue_api_key.get_secret_value()
        )
        logger.info(f'Email sent successfully')
    else:
        logger.info(f'Not sending email in non-production environment')


@app.before_serving
async def startup():
    RequestContextProvider.initialize_provider(
        app=app)

    await send_initial_email()


swag = Swagger(app=app, title='kube-tools-api')
swag.configure()


if __name__ == '__main__':
    app.run(debug=True, port='5086')
