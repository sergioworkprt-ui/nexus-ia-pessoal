"""Email sender — Gmail SMTP sem dependências externas."""
import os, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

def send_email(to_email, subject, body):
    gmail = os.environ.get('GMAIL_ADDRESS', '')
    app_pw = os.environ.get('GMAIL_APP_PASSWORD', '')
    if not gmail or not app_pw:
        raise ValueError("GMAIL_ADDRESS e GMAIL_APP_PASSWORD não configurados")

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"NEXUS IA <{gmail}>"
    msg['To'] = to_email

    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    html = f"""<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;
background:#0a0a0f;color:#e8e8f0;padding:2rem;border-radius:12px">
<h2 style="color:#a594ff">{subject}</h2>
<div style="background:#1a1a24;padding:1.5rem;border-radius:8px;
border:1px solid #2a2a3a;white-space:pre-wrap;line-height:1.6">{body}</div>
<p style="margin-top:1rem;color:#5a5a7a;font-size:0.8rem">
NEXUS: <a href="https://nexus-ia-pessoal.onrender.com" style="color:#7c6fff">
nexus-ia-pessoal.onrender.com</a></p></div>"""
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(gmail, app_pw)
        server.sendmail(gmail, to_email, msg.as_string())
