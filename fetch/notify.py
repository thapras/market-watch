"""Digest and push for must-reads. Runs after the fetch in the Action:

    python3 -m fetch.notify

Reads data/changes.json and data/state.json, finds must-reads logged since the last notification, and sends
them to whichever channels are configured by environment variables (none set: nothing is sent, and it says so):
  NTFY_TOPIC                      ntfy.sh topic (no account needed)
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  SMTP_HOST, SMTP_USER, SMTP_PASS, DIGEST_TO   email digest over STARTTLS on port 587 (Gmail app password works)
The digest goes out only when there is a must-read; notable and FYI items ride along in the same message.
"""
import datetime as dt
import json
import os
import smtplib
import sys
import urllib.request
from email.mime.text import MIMEText

from . import changes as ch

BKK = dt.timezone(dt.timedelta(hours=7))


def build_text(items, all_items, as_of_label):
    musts = [c for c in items if c["tier"] == "must"]
    notes = [c for c in all_items if c["tier"] == "note"][:6]
    lines = ["Market Watch, %s" % as_of_label, ""]
    lines.append("Must read (%d)" % len(musts))
    for c in musts:
        lines.append("  %s  %s" % (c["d"], c["text"]))
    if notes:
        lines.append("")
        lines.append("Notable")
        for c in notes:
            lines.append("  %s  %s" % (c["d"], c["text"]))
    return "\n".join(lines)


def send_ntfy(topic, title, text):
    req = urllib.request.Request("https://ntfy.sh/%s" % topic, data=text.encode("utf-8"),
                                 headers={"Title": title, "Priority": "high", "Tags": "chart_with_upwards_trend"})
    urllib.request.urlopen(req, timeout=30).read()


def send_telegram(token, chat_id, text):
    body = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % token, data=body,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30).read()


def send_email(host, user, password, to, subject, text):
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    with smtplib.SMTP(host, 587, timeout=60) as s:
        s.starttls()
        s.login(user, password)
        s.sendmail(user, [to], msg.as_string())


def main(argv=None):
    data_dir = os.environ.get("MW_DATA", "data")
    changes = ch.load(os.path.join(data_dir, "changes.json")) or {"changes": [], "asOfLabel": ""}
    state = ch.load(os.path.join(data_dir, "state.json")) or {}
    since = state.get("notified", "")
    fresh = [c for c in changes.get("changes", []) if c.get("t", "") > since]
    musts = [c for c in fresh if c["tier"] == "must"]
    if not musts:
        print("notify: no must-read since %s; nothing sent" % (since or "the start"))
        return 0
    text = build_text(fresh, fresh, changes.get("asOfLabel", ""))
    title = "Market Watch: %d must-read%s" % (len(musts), "" if len(musts) == 1 else "s")
    sent = []
    env = os.environ
    try:
        if env.get("NTFY_TOPIC"):
            send_ntfy(env["NTFY_TOPIC"], title, text)
            sent.append("ntfy")
        if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
            send_telegram(env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"], title + "\n\n" + text)
            sent.append("telegram")
        if env.get("SMTP_HOST") and env.get("SMTP_USER") and env.get("SMTP_PASS") and env.get("DIGEST_TO"):
            send_email(env["SMTP_HOST"], env["SMTP_USER"], env["SMTP_PASS"], env["DIGEST_TO"], title, text)
            sent.append("email")
    except Exception as e:      # noqa: BLE001
        print("notify: send failed: %s" % e, file=sys.stderr)
        return 1
    if not sent:
        print("notify: %d must-read(s) pending but no channel is configured (NTFY_TOPIC, TELEGRAM_*, SMTP_*)" % len(musts))
        return 0
    state["notified"] = dt.datetime.now(BKK).isoformat(timespec="minutes")
    ch.save(os.path.join(data_dir, "state.json"), state)
    print("notify: sent %d must-read(s) via %s" % (len(musts), ", ".join(sent)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
