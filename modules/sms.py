"""
NEXUS SMS Module — Alertas por SMS
Usa textbelt (1 SMS grátis/dia) ou Twilio (pago).
"""
import os, json, urllib.request, urllib.parse, logging
logger = logging.getLogger('nexus.sms')


def send_sms_textbelt(phone, message):
    """
    Textbelt — 1 SMS grátis por dia por IP.
    Para mais: comprar key em textbelt.com (~$2 por 100 SMS).
    """
    key = os.environ.get('TEXTBELT_KEY', 'textbelt')  # 'textbelt' = 1 grátis/dia
    data = urllib.parse.urlencode({
        'phone': phone,
        'message': message[:160],
        'key': key
    }).encode()
    req = urllib.request.Request(
        'https://textbelt.com/text',
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
        if result.get('success'):
            logger.info(f"SMS enviado para {phone[:6]}...")
            return True, result
        return False, result.get('error', 'Erro desconhecido')
    except Exception as e:
        return False, str(e)


def send_sms_twilio(phone, message):
    """Twilio — pago mas muito fiável."""
    account_sid = os.environ.get('TWILIO_SID', '')
    auth_token = os.environ.get('TWILIO_TOKEN', '')
    from_number = os.environ.get('TWILIO_FROM', '')
    if not all([account_sid, auth_token, from_number]):
        return False, "Twilio não configurado"

    import base64
    credentials = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    data = urllib.parse.urlencode({
        'To': phone, 'From': from_number, 'Body': message[:1600]
    }).encode()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    req = urllib.request.Request(url, data=data, headers={
        'Authorization': f'Basic {credentials}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
        return True, result
    except Exception as e:
        return False, str(e)


def send_sms(phone, message):
    """
    Router SMS — tenta textbelt primeiro, depois Twilio.
    """
    if not phone:
        return False, "Número de telefone não configurado"

    # Tenta Twilio primeiro se configurado
    if os.environ.get('TWILIO_SID'):
        ok, result = send_sms_twilio(phone, message)
        if ok: return True, result

    # Fallback textbelt
    return send_sms_textbelt(phone, message)
