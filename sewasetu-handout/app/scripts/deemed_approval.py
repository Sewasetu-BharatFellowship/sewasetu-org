
# -*- coding: utf-8 -*-
"""
Nightly deemed-approval job.

Under the Purvanchal Right to Public Services Act, an application not processed
within the statutory SLA stands approved. This job marks such applications
DEEMED_APPROVED and notifies the applicant by SMS.

Scheduled via cron, 02:00 daily. See deploy/crontab.
"""

import os
import sys
import configparser
import logging
from datetime import datetime, timedelta

import psycopg2
import requests


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

config = configparser.ConfigParser()
CONFIG_PATH = os.environ.get(
    "DEEMED_APPROVAL_CONFIG",
    os.path.join(BASE_DIR, "config", "app.ini")
)

if not os.path.isfile(CONFIG_PATH):
    raise FileNotFoundError(
        f"Configuration file not found: {CONFIG_PATH}"
    )

with open(CONFIG_PATH, encoding="utf-8") as fh:
    config.read_file(fh)

SLA_DAYS = config.getint("pension", "sla_days")
SMS_GATEWAY_URL = config.get("app", "sms_gateway_url")

logger = logging.getLogger(__name__)


def main():
    conn = None
    cur = None

    try:
        conn = psycopg2.connect(
            host=config.get("database", "host"),
            port=config.get("database", "port"),
            dbname=config.get("database", "name"),
            user=config.get("database", "user"),
            password=os.environ["DB_PASSWORD"],
        )

        cur = conn.cursor()

        now = datetime.now()
        cutoff = now - timedelta(days=SLA_DAYS)

        cur.execute(
            """UPDATE applications
               SET status = 'DEEMED_APPROVED',
                   decided_at = %s,
                   decided_by = 'RTPS-AUTO'
               WHERE status = 'PENDING' AND submitted_at < %s
               RETURNING application_no, mobile""",
            (now, cutoff),
        )

        rows = cur.fetchall()
        conn.commit()

    except Exception:
        if conn is not None:
            conn.rollback()
        raise

    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()

    # Send notifications only after the approval transaction commits.
    for app_no, mobile in rows:
        try:
            response = requests.post(
                SMS_GATEWAY_URL + "/api/send",
                json={
                    "to": mobile,
                    "text": (
                        "Sewa Setu: your pension application %s stands approved "
                        "under the RTPS Act." % app_no
                    ),
                },
                timeout=5,
            )

            response.raise_for_status()

        except Exception as exc:
            logger.error(
                "SMS notification failed for application %s: %s",
                app_no,
                exc,
            )

    logger.info(
        "%s deemed approval: %d applications approved",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        len(rows),
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(main())
