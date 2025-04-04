from framework.configuration import Configuration
from framework.logger import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from openai import OpenAI
from quart import Response, request
from twilio.twiml.voice_response import Gather, VoiceResponse

logger = get_logger(__name__)


def get_gpt_response(container, prompt):
    config = container.resolve(Configuration)
    client = OpenAI(api_key=config.open_ai.get('api_key'))

    response = client.chat.completions.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": "You are a friendly AI having a phone conversation."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=100
    )
    return response.choices[0].message.content


fakebot_bp = MetaBlueprint('fakebot_bp', __name__)


@fakebot_bp.route("/voice", methods=['POST'])
async def voice(container):
    resp = VoiceResponse()
    gather = Gather(input='speech', action='/gpt-reply', timeout=5)
    gather.say("Hello?")
    resp.append(gather)
    resp.redirect('/voice')  # If nothing is said
    return Response(str(resp), mimetype='text/xml')


@fakebot_bp.route("/gpt-reply", methods=['POST'])
async def gpt_reply(container):
    form = await request.form
    speech = form.get('SpeechResult')
    logger.info(f"User said: {speech}")

    gpt_reply = get_gpt_response(container, speech)
    logger.info(f"GPT replied: {gpt_reply}")

    resp = VoiceResponse()
    gather = Gather(input='speech', action='/gpt-reply', timeout=5)
    gather.say(gpt_reply)
    resp.append(gather)
    resp.redirect('/voice')
    return Response(str(resp), mimetype='text/xml')
