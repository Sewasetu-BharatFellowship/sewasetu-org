# -*- coding: utf-8 -*-
"""
Sewa Setu - Old Age Pension Portal
Government of Purvanchal, Department of Social Welfare

Developed by: Netlink Infosolutions Pvt Ltd (2023)
Maintenance contract ended 31/01/2026.
"""

import os
import io
import csv
import random
import hashlib
import configparser
import secrets
from datetime import datetime, date, timedelta


import requests
import psycopg2
from flask import (Flask, request, session, redirect, url_for, render_template,
                   flash, send_file, abort, jsonify)
from fpdf import FPDF

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

config = configparser.ConfigParser()
config.read(os.path.join(BASE_DIR, "config", "app.ini"))

app = Flask(__name__)

app.config["PERMANENT_SESSION_LIFETIME"] = 1800

app.secret_key = os.environ["FLASK_SECRET_KEY"]

ADMIN_USERNAME = os.environ["ADMIN_USERNAME"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]

SMS_GATEWAY_URL = os.environ.get(
    "SMS_GATEWAY_URL",
    config.get("app", "sms_gateway_url")
)
OTP_VALIDITY_SECONDS = config.getint("app", "otp_validity_seconds")
UPLOAD_DIR = config.get("app", "upload_dir")
SCHEME_DEADLINE = datetime.strptime(config.get("pension", "scheme_deadline"),
                                    "%Y-%m-%d %H:%M")
MIN_AGE = config.getint("pension", "min_age")
SLA_DAYS = config.getint("pension", "sla_days")

BLOCKS = ["Sonari", "Rajapara", "Dhemaji Pathar", "Borgaon", "Namti", "Khelua"]

import logging
_logdir = "/var/log/sewasetu"
try:
    os.makedirs(_logdir, exist_ok=True)
    _fh = logging.FileHandler(os.path.join(_logdir, "sewasetu-app.log"))
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s in app: %(message)s"))
    app.logger.addHandler(_fh)
    app.logger.setLevel(logging.INFO)
except Exception:
    pass


def get_db():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", config.get("database", "host")),
        port=int(os.environ.get("DB_PORT", config.get("database", "port"))),
        dbname=os.environ.get("DB_NAME", config.get("database", "name")),
        user=os.environ.get("DB_USER", config.get("database", "user")),
        password=os.environ["DB_PASSWORD"],
    )



def sanitize(value, maxlen=100):
    """
    Sanitize text without corrupting Unicode characters.

    maxlen represents the maximum number of characters,
    not the number of UTF-8 bytes.
    """
    if value is None:
        return ""

    value = value.strip()

    return value[:maxlen]



def hash_password(p):
    return hashlib.sha256(p.encode("utf-8")).hexdigest()


def send_sms(mobile, text):
    try:
        requests.post(SMS_GATEWAY_URL + "/api/send",
                      json={"to": mobile, "text": text}, timeout=5)
    except Exception as e:
        app.logger.error("sms gateway error: %s" % e)


def deadline_remaining():
    delta = SCHEME_DEADLINE - datetime.now()
    if delta.total_seconds() <= 0:
        return None
    return int(delta.total_seconds() // 3600)


def new_application_no():
    return "SSP" + datetime.now().strftime("%y") + str(random.randint(100000, 999999))


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", hours_left=deadline_remaining())


@app.route("/about")
def about():
    return render_template("about.html")


# @app.route("/__gateway/", defaults={"subpath": ""})
# @app.route("/__gateway/<path:subpath>")
# def gateway_proxy(subpath):
#     # Convenience proxy to the internal SMS gateway, so the OTP inbox is reachable
#     # on the main site without opening a second port on the host. The gateway
#     # itself runs only on the internal network.
#     try:
#         r = requests.get(SMS_GATEWAY_URL + "/" + subpath,
#                          params=request.args, timeout=5)
#         return (r.content, r.status_code,
#                 {"Content-Type": r.headers.get("Content-Type", "text/html")})
#     except Exception as e:
#         return ("SMS gateway unreachable: %s" % e, 502)


# ---------------------------------------------------------------------------
# Application flow: mobile -> OTP -> form steps -> upload -> declaration
# ---------------------------------------------------------------------------

@app.route("/apply", methods=["GET", "POST"])
def apply():
    if deadline_remaining() is None:
        flash("The application window for this scheme has closed.")
        return redirect(url_for("index"))

    if request.method == "POST":
        mobile = request.form.get("mobile", "").strip()
        captcha = request.form.get("captcha", "").strip()
        expected_captcha = session.pop("captcha_answer", None)

        if (
            expected_captcha is None
            or not captcha.isdigit()
            or captcha != str(expected_captcha)
        ):
            flash("Invalid CAPTCHA. Please try again.")
            return render_template("apply.html", captcha_q=make_captcha())

        if len(mobile) != 10 or not mobile.isdigit():
            flash("Please fill in all required fields.")
            return render_template("apply.html", captcha_q=make_captcha())

        code = str(secrets.randbelow(900000) + 100000)

        conn = get_db()
        cur = None

        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO otps (mobile, code, created_at) VALUES (%s, %s, %s)",
                (mobile, code, datetime.now()),
            )
            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            if cur is not None:
                cur.close()
            conn.close()

        send_sms(mobile, "Your Sewa Setu OTP is %s. Valid for 5 minutes." % code)

        session.permanent = True
        session.pop("otp_attempts", None)
        session["apply_mobile"] = mobile
        return redirect(url_for("verify"))

    return render_template("apply.html", captcha_q=make_captcha())



def make_captcha():
    a, b = random.randint(1, 9), random.randint(1, 9)
    session["captcha_answer"] = a + b
    return "%d + %d" % (a, b)



@app.route("/verify", methods=["GET", "POST"])
def verify():
    mobile = session.get("apply_mobile")

    if not mobile:
        return redirect(url_for("apply"))

    if request.method == "POST":
        # Block verification after 5 failed attempts.
        attempts = session.get("otp_attempts", 0)

        if attempts >= 5:
            session.pop("apply_mobile", None)
            session.pop("otp_attempts", None)
            flash("Too many incorrect OTP attempts. Please request a new OTP.")
            return redirect(url_for("apply"))

        code = request.form.get("otp", "").strip()

        conn = get_db()
        cur = None

        try:
            cur = conn.cursor()

            cur.execute(
                "SELECT code, created_at FROM otps "
                "WHERE mobile = %s AND purpose = %s "
                "ORDER BY id DESC LIMIT 1",
                (mobile, "registration"),
            )
            row = cur.fetchone()

        except Exception:
            conn.rollback()
            raise

        finally:
            if cur is not None:
                cur.close()
            conn.close()

        if row and row[0] == code:
            age = (datetime.now() - row[1]).total_seconds()

            if age > OTP_VALIDITY_SECONDS:
                session.pop("apply_mobile", None)
                session.pop("otp_attempts", None)
                app.logger.warning(
                    "otp expired mobile=%s age=%ds" % (mobile, int(age))
                )
                flash("OTP expired. Please request a new OTP.")
                return redirect(url_for("apply"))

            session["verified_mobile"] = mobile

            if not correction_session_is_valid():
                session.pop("correction_application_id", None)
                session.pop("verified_mobile", None)
                session.pop("form_data", None)
                session.pop("doc_path", None)

                flash(
                    "Your correction session is invalid or has expired. "
                    "Please login again."
                )
                return redirect(url_for("status_login"))

            session.pop("otp_attempts", None)
            session.pop("apply_mobile", None)

            return redirect(url_for("form_step", step=1))

        attempts += 1

        if attempts >= 5:
            session.pop("apply_mobile", None)
            session.pop("otp_attempts", None)
            flash("Too many incorrect OTP attempts. Please request a new OTP.")
            return redirect(url_for("apply"))

        session["otp_attempts"] = attempts
        flash("Invalid OTP.")

    return render_template("verify.html", mobile=mobile)

def correction_session_is_valid():
    app_id = session.get("correction_application_id")

    # Normal application submission.
    if not app_id:
        return True

    mobile = session.get("verified_mobile")

    if not mobile:
        return False

    conn = get_db()
    cur = None

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT status
            FROM applications
            WHERE id = %s AND mobile = %s
            """,
            (app_id, mobile),
        )
        row = cur.fetchone()

        return bool(row and row[0] == "CORRECTION_REQUIRED")

    except Exception:
        conn.rollback()
        raise

    finally:
        if cur is not None:
            cur.close()
        conn.close()

@app.route("/form/<int:step>", methods=["GET", "POST"])
def form_step(step):
    if not session.get("verified_mobile"):
        flash("Session expired. Please verify your mobile number again.")
        return redirect(url_for("apply"))

    if not correction_session_is_valid():
        session.pop("correction_application_id", None)
        session.pop("verified_mobile", None)
        session.pop("form_data", None)
        session.pop("doc_path", None)

        flash("Your correction session is invalid or has expired. Please login again.")
        return redirect(url_for("status_login"))

    if step not in (1, 2, 3):
        abort(404)

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if not session.get("verified_mobile"):
        flash("Your session has expired. Please verify your mobile number again.")
        return redirect(url_for("apply"))

    if not correction_session_is_valid():
        session.pop("correction_application_id", None)
        session.pop("verified_mobile", None)
        session.pop("form_data", None)
        session.pop("doc_path", None)

        flash("Your correction session is invalid or has expired. Please login again.")
        return redirect(url_for("status_login"))

    if request.method == "POST":
        f = request.files.get("document")

        if f is None or not f.filename:
            flash("Please select a document to upload.")
            return render_template("upload.html")

        # Maximum upload size: 5 MB
        max_size = 5 * 1024 * 1024
        content = f.stream.read(max_size + 1)

        if len(content) > max_size:
            flash("File size must not exceed 5 MB.")
            return render_template("upload.html")

        # Validate actual file signature, not just extension.
        file_types = {
            b"%PDF-": "pdf",
            b"\xff\xd8\xff": "jpg",
            b"\x89PNG\r\n\x1a\n": "png",
        }

        extension = None

        for signature, ext in file_types.items():
            if content.startswith(signature):
                extension = ext
                break

        if extension is None:
            flash("Invalid document. Please upload a valid PDF, JPG, JPEG, or PNG file.")
            return render_template("upload.html")

        os.makedirs(UPLOAD_DIR, exist_ok=True)

        # Use verified mobile and detected extension.
        mobile = session["verified_mobile"]
        path = os.path.join(UPLOAD_DIR, f"{mobile}.{extension}")

        with open(path, "wb") as out:
            out.write(content)

        session["doc_path"] = path
        return redirect(url_for("declaration"))

    return render_template("upload.html")


@app.route("/declaration", methods=["GET", "POST"])
def declaration():
    if not session.get("verified_mobile"):
        flash("Session expired. Please verify your mobile number again.")
        return redirect(url_for("apply"))
    if not correction_session_is_valid():
        session.pop("correction_application_id", None)
        session.pop("verified_mobile", None)
        session.pop("form_data", None)
        session.pop("doc_path", None)

        flash("Your correction session is invalid or has expired. Please login again.")
        return redirect(url_for("status_login"))
    if request.method == "POST":
        return handle_submission()
    return render_template("declaration.html")



def handle_submission():
    # TODO: split this up some day. It grew. - RK, 09/2024
    mobile = session.get("verified_mobile")
    data = session.get("form_data", {})
    doc_path = session.get("doc_path", "")
    correction_app_id = session.get("correction_application_id")
    is_correction = bool(correction_app_id)

    # Validate verified mobile number.
    if not mobile or len(mobile) != 10 or not mobile.isdigit():
        flash("Please verify your mobile number again.")
        return redirect(url_for("apply"))

    # Validate uploaded document.
    try:
        valid_document = (
            bool(doc_path)
            and os.path.isfile(doc_path)
            and os.path.getsize(doc_path) > 0
        )
    except OSError:
        valid_document = False

    if not valid_document:
        flash("Please upload your required document before submitting.")
        return redirect(url_for("upload"))

    name = sanitize(data.get("applicant_name", ""))
    village = data.get("village", "").strip()
    block = data.get("block", "").strip()
    gender = data.get("gender", "")
    marital = data.get("marital_status", "")
    husband_name = data.get("husband_name", "")
    husband_employer = data.get("husband_employer", "")
    bank_account = data.get("bank_account", "").strip()
    ifsc = data.get("ifsc", "").strip().upper()
    dob_raw = data.get("dob", "").strip()

    if not name or not village or not block or not bank_account or not dob_raw:
        flash("Something went wrong. Please try again.")
        return redirect(url_for("form_step", step=1))

    if marital == "Widowed" and not husband_name:
        flash("Please provide your husband's name.")
        return redirect(url_for("form_step", step=1))

    # Parse date of birth.
    dob = None

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            dob = datetime.strptime(dob_raw, fmt).date()
            break
        except ValueError:
            continue

    if dob is None:
        flash("Please enter a valid date of birth in DD/MM/YYYY format.")
        return redirect(url_for("form_step", step=1))

    # Validate applicant age.
    today = date.today()
    age = today.year - dob.year - (
        (today.month, today.day) < (dob.month, dob.day)
    )

    if age < MIN_AGE:
        flash("Applicant must be above %d years of age to be eligible." % MIN_AGE)
        return redirect(url_for("form_step", step=1))

    if datetime.now() > SCHEME_DEADLINE:
        flash("The application deadline has passed.")
        return redirect(url_for("index"))

    conn = get_db()
    cur = None

    try:
        cur = conn.cursor()

        if is_correction:
            # Update only the citizen's own application awaiting correction.
            cur.execute(
                """
                UPDATE applications
                SET applicant_name = %s,
                    dob = %s,
                    gender = %s,
                    marital_status = %s,
                    husband_name = %s,
                    husband_employer = %s,
                    village = %s,
                    block = %s,
                    bank_account = %s,
                    ifsc = %s,
                    doc_path = %s,
                    status = 'PENDING',
                    decided_at = NULL,
                    decided_by = NULL,
                    correction_reason = NULL,
                    correction_requested_at = NULL
                WHERE id = %s
                  AND mobile = %s
                  AND status = 'CORRECTION_REQUIRED'
                RETURNING id, application_no
                """,
                (
                    name, dob, gender, marital,
                    husband_name, husband_employer,
                    village, block, bank_account, ifsc,
                    doc_path, correction_app_id, mobile,
                ),
            )

            updated = cur.fetchone()

            if not updated:
                conn.rollback()
                flash(
                    "Application could not be updated. "
                    "Please contact support."
                )
                return redirect(url_for("index"))

            new_id, app_no = updated

            # Keep the portal login password synchronized with the updated DOB.
            portal_pass = dob.strftime("%d%m%Y")

            cur.execute(
                """
                UPDATE portal_users
                SET password_hash = %s
                WHERE mobile = %s
                """,
                (hash_password(portal_pass), mobile),
            )

        else:
            # Prevent duplicate normal applications.
            cur.execute(
                "SELECT count(*) FROM applications WHERE mobile = %s",
                (mobile,),
            )

            if cur.fetchone()[0] > 0:
                flash(
                    "An application already exists for this mobile number. "
                    "Duplicate applications are not permitted."
                )
                return redirect(url_for("index"))

            app_no = new_application_no()

            cur.execute(
                """
                INSERT INTO applications
                    (
                        application_no, applicant_name, mobile, dob,
                        gender, marital_status, husband_name,
                        husband_employer, village, block, bank_account,
                        ifsc, doc_path, status, submitted_at
                    )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, 'PENDING', %s
                )
                RETURNING id
                """,
                (
                    app_no, name, mobile, dob, gender, marital,
                    husband_name, husband_employer, village, block,
                    bank_account, ifsc, doc_path, datetime.now(),
                ),
            )

            new_id = cur.fetchone()[0]

            # Create status portal account if it does not exist.
            portal_pass = dob.strftime("%d%m%Y")

            cur.execute(
                "SELECT count(*) FROM portal_users WHERE mobile = %s",
                (mobile,),
            )

            if cur.fetchone()[0] == 0:
                cur.execute(
                    """
                    INSERT INTO portal_users (mobile, password_hash)
                    VALUES (%s, %s)
                    """,
                    (mobile, hash_password(portal_pass)),
                )

        conn.commit()

        app.logger.info(
            "generating acknowledgment pdf application=%d" % new_id
        )

        # Regenerate acknowledgment using the updated application data.
        pdf_bytes = generate_acknowledgment(cur, new_id)

        ack_dir = os.path.join(UPLOAD_DIR, "ack")
        os.makedirs(ack_dir, exist_ok=True)

        ack_path = os.path.join(ack_dir, "%d.pdf" % new_id)
        temp_ack_path = ack_path + ".tmp"

        try:
            with open(temp_ack_path, "wb") as out:
                out.write(pdf_bytes)

            os.replace(temp_ack_path, ack_path)

        finally:
            if os.path.exists(temp_ack_path):
                os.remove(temp_ack_path)

    except Exception:
        conn.rollback()
        raise

    finally:
        if cur is not None:
            cur.close()
        conn.close()

    # Clear submission and correction session data.
    session.pop("form_data", None)
    session.pop("doc_path", None)
    session.pop("verified_mobile", None)
    session.pop("correction_application_id", None)

    if is_correction:
        sms_message = (
            "Sewa Setu: corrected application %s has been resubmitted "
            "successfully. Track its status using your mobile number "
            "and updated DOB (DDMMYYYY)."
        ) % app_no
    else:
        sms_message = (
            "Sewa Setu: application %s received. Track at the status portal "
            "with mobile no. and password (DOB as DDMMYYYY)."
        ) % app_no

    send_sms(mobile, sms_message)

    return render_template(
        "confirmation.html",
        app_no=app_no,
        app_id=new_id,
    )


def generate_acknowledgment(cur, app_id):
    cur.execute(
        "SELECT application_no, applicant_name, mobile, dob, village, block, "
        "bank_account, ifsc, submitted_at, status FROM applications WHERE id = %s",
        (app_id,)
    )

    row = cur.fetchone()

    if not row:
        raise ValueError(f"Application {app_id} not found")

    font_path = os.path.join(
        BASE_DIR,
        "fonts",
        "NotoSansBengali-Regular.ttf"
    )

    if not os.path.isfile(font_path):
        raise FileNotFoundError(
            f"Unicode font not found: {font_path}"
        )

    pdf = FPDF()
    pdf.add_page()

    # Register embedded Unicode TrueType font.
    pdf.add_font(
        family="NotoSansBengali",
        style="",
        fname=font_path
    )

    # Enable Indic script shaping
    pdf.set_text_shaping(
    use_shaping_engine=True,
    direction="ltr",
    script="beng"
)

    pdf.set_font("NotoSansBengali", size=14)

    pdf.cell(
        0, 10,
        "GOVERNMENT OF PURVANCHAL",
        ln=1,
        align="C"
    )

    pdf.set_font("NotoSansBengali", size=11)

    pdf.cell(
        0, 8,
        "Department of Social Welfare",
        ln=1,
        align="C"
    )

    pdf.cell(
        0, 8,
        "Old Age Pension Scheme - Acknowledgment",
        ln=1,
        align="C"
    )

    pdf.ln(4)

    # Keep the existing acknowledgment layout.
    labels = [
        "Application No",
        "Applicant Name",
        "Mobile",
        "Date of Birth",
        "Village",
        "Block",
        "Bank Account",
        "IFSC",
        "Submitted At",
        "Status"
    ]

    pdf.set_font("NotoSansBengali", size=10)

    for label, val in zip(labels, row):
        pdf.cell(60, 8, label, border=1)
        pdf.cell(0, 8, str(val), border=1, ln=1)

    pdf.ln(6)

    pdf.set_font("NotoSansBengali", size=9)

    pdf.multi_cell(
        0,
        5,
        "This is a computer generated acknowledgment. Processing SLA "
        "as per the Purvanchal Right to Public Services Act applies."
    )

    return bytes(pdf.output())

# ---------------------------------------------------------------------------
# Status portal (citizen login)
# ---------------------------------------------------------------------------

@app.route("/status", methods=["GET", "POST"])
def status_login():
    if request.method == "POST":
        mobile = request.form.get("mobile", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        cur = None

        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT password_hash FROM portal_users WHERE mobile = %s",
                (mobile,),
            )
            row = cur.fetchone()

        except Exception:
            conn.rollback()
            raise

        finally:
            if cur is not None:
                cur.close()
            conn.close()

        if row and row[0] == hash_password(password):
            session["logged_in"] = True
            session["portal_mobile"] = mobile

            conn = get_db()
            cur = None

            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id FROM applications WHERE mobile = %s "
                    "ORDER BY submitted_at DESC LIMIT 1",
                    (mobile,),
                )
                r = cur.fetchone()

            except Exception:
                conn.rollback()
                raise

            finally:
                if cur is not None:
                    cur.close()
                conn.close()

            if r:
                return redirect(url_for("view_application", app_id=r[0]))

            flash("No application found for this mobile number.")
            return redirect(url_for("status_login"))

        flash("Unable to verify your details. Please check your mobile number and date of birth.")

    return render_template("status_login.html")

@app.route("/application/<int:app_id>")
def view_application(app_id):
    if not session.get("logged_in"):
        flash("Please login to view application status.")
        return redirect(url_for("status_login"))
    
    conn = get_db()
    cur = None

    try:
        cur = conn.cursor()
        cur.execute(
    "SELECT application_no, applicant_name, mobile, dob, village, block, "
    "bank_account, ifsc, status, submitted_at, decided_at, correction_reason "
    "FROM applications WHERE id = %s",
    (app_id,)
)
        row = cur.fetchone()

    except Exception:
        conn.rollback()
        raise

    finally:
        if cur is not None:
            cur.close()
        conn.close()

    if not row:
        abort(404)

    # Admins can view every application.
    # Citizens can only view applications linked to their mobile.
    if not session.get("admin") and row[2] != session.get("portal_mobile"):
        abort(403)

        # Display deemed approval when the statutory SLA has expired,
    # even if the scheduled job has not updated the database yet.
    if (
        row[8] == "PENDING"
        and row[9] is not None
        and row[9] < datetime.now() - timedelta(days=SLA_DAYS)
    ):
        row = list(row)
        row[8] = "DEEMED_APPROVED"
        row = tuple(row)

    return render_template("application.html", a=row, app_id=app_id)

@app.route("/application/<int:app_id>/edit")
def edit_application(app_id):
    if not session.get("logged_in"):
        flash("Please login to edit your application.")
        return redirect(url_for("status_login"))

    mobile = session.get("portal_mobile")

    conn = get_db()
    cur = None

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT applicant_name, mobile, dob, gender, marital_status,
                   husband_name, husband_employer, village, block,
                   bank_account, ifsc, doc_path, status
            FROM applications
            WHERE id = %s AND mobile = %s
            """,
            (app_id, mobile),
        )
        row = cur.fetchone()

    except Exception:
        conn.rollback()
        raise

    finally:
        if cur is not None:
            cur.close()
        conn.close()

    if not row:
        abort(404)

    if row[12] != "CORRECTION_REQUIRED":
        flash("This application is not awaiting correction.")
        return redirect(url_for("view_application", app_id=app_id))

    dob = row[2].strftime("%d/%m/%Y") if row[2] else ""

    session["verified_mobile"] = mobile
    session["correction_application_id"] = app_id
    session["form_data"] = {
        "applicant_name": row[0] or "",
        "dob": dob,
        "gender": row[3] or "",
        "marital_status": row[4] or "",
        "husband_name": row[5] or "",
        "husband_employer": row[6] or "",
        "village": row[7] or "",
        "block": row[8] or "",
        "bank_account": row[9] or "",
        "ifsc": row[10] or "",
    }

    # Require a fresh document during correction.
    session.pop("doc_path", None)

    return redirect(url_for("form_step", step=1))

@app.route("/ack/<int:app_id>.pdf")
def ack_pdf(app_id):
    if not session.get("logged_in"):
        flash("Please login to view application status.")
        return redirect(url_for("status_login"))

    # Always verify ownership before checking the cached PDF.
    conn = get_db()
    cur = None

    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT mobile FROM applications WHERE id = %s",
        (app_id,)
    )
        row = cur.fetchone()

    except Exception:
        conn.rollback()
        raise

    finally:
        if cur is not None:
            cur.close()
        conn.close()

    if not row:
        abort(404)

    if not session.get("admin") and row[0] != session.get("portal_mobile"):
        abort(403)

    path = os.path.join(UPLOAD_DIR, "ack", "%d.pdf" % app_id)

    if os.path.exists(path):
        return send_file(path, mimetype="application/pdf")

    conn = get_db()
    cur = conn.cursor()

    try:
        data = generate_acknowledgment(cur, app_id)
    finally:
        cur.close()
        conn.close()

    return send_file(
        io.BytesIO(data),
        mimetype="application/pdf"
    )



@app.route("/status/reset", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        mobile = request.form.get("mobile", "").strip()

        if len(mobile) != 10 or not mobile.isdigit():
            flash("Please enter a valid 10-digit mobile number.")
            return render_template("reset.html", step="request")

        conn = get_db()
        cur = None
        sms_mobile = None

        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT mobile FROM portal_users WHERE mobile = %s",
                (mobile,),
            )
            account = cur.fetchone()

            if account:
                code = str(secrets.randbelow(900000) + 100000)

                cur.execute(
                    "DELETE FROM otps WHERE mobile = %s "
                    "AND purpose = %s",
                    (mobile, "password_reset"),
                )
                cur.execute(
                    "INSERT INTO otps (mobile, code, created_at, purpose) "
                    "VALUES (%s, %s, %s, %s)",
                    (mobile, code, datetime.now(), "password_reset"),
                )
                conn.commit()
                sms_mobile = mobile

        except Exception:
            conn.rollback()
            raise

        finally:
            if cur is not None:
                cur.close()
            conn.close()

        session.pop("reset_verified_mobile", None)
        session.pop("reset_attempts", None)
        session.pop("reset_mobile", None)

        if sms_mobile:
            session["reset_mobile"] = sms_mobile
            send_sms(
                sms_mobile,
                "Your Sewa Setu password reset OTP is %s. "
                "Valid for 5 minutes." % code,
            )

        flash("If the account exists, a password reset OTP has been sent.")
        return redirect(url_for("reset_password_verify"))

    return render_template("reset.html", step="request")


@app.route("/status/reset/verify", methods=["GET", "POST"])
def reset_password_verify():
    mobile = session.get("reset_mobile")

    if not mobile:
        flash("Please request a password reset OTP first.")
        return redirect(url_for("reset_password"))

    if request.method == "POST":
        attempts = session.get("reset_attempts", 0)

        if attempts >= 5:
            session.pop("reset_mobile", None)
            session.pop("reset_attempts", None)
            flash("Too many incorrect attempts. Please request a new OTP.")
            return redirect(url_for("reset_password"))

        code = request.form.get("otp", "").strip()

        conn = get_db()
        cur = None
        row = None

        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT code, created_at FROM otps "
                "WHERE mobile = %s AND purpose = %s "
                "ORDER BY id DESC LIMIT 1",
                (mobile, "password_reset"),
            )
            row = cur.fetchone()

            if row and row[0] == code:
                age = (datetime.now() - row[1]).total_seconds()

                if age <= OTP_VALIDITY_SECONDS:
                    cur.execute(
                        "DELETE FROM otps WHERE mobile = %s "
                        "AND purpose = %s",
                        (mobile, "password_reset"),
                    )
                    conn.commit()
                    session["reset_verified_mobile"] = mobile
                    session.pop("reset_mobile", None)
                    session.pop("reset_attempts", None)
                    return redirect(url_for("reset_password_new"))
                
                conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            if cur is not None:
                cur.close()
            conn.close()

        attempts += 1
        session["reset_attempts"] = attempts

        if attempts >= 5:
            session.pop("reset_mobile", None)
            session.pop("reset_attempts", None)
            flash("Too many incorrect attempts. Please request a new OTP.")
            return redirect(url_for("reset_password"))

        flash("Invalid or expired OTP.")

    return render_template("reset.html", step="verify")


@app.route("/status/reset/password", methods=["GET", "POST"])
def reset_password_new():
    mobile = session.get("reset_verified_mobile")

    if not mobile:
        flash("Please verify your reset OTP first.")
        return redirect(url_for("reset_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return render_template("reset.html", step="password")

        if password != confirm_password:
            flash("Passwords do not match.")
            return render_template("reset.html", step="password")

        conn = get_db()
        cur = None

        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE portal_users SET password_hash = %s "
                "WHERE mobile = %s",
                (hash_password(password), mobile),
            )
            updated = cur.rowcount
            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            if cur is not None:
                cur.close()
            conn.close()

        session.pop("reset_verified_mobile", None)

        if updated:
            flash("Your password has been reset successfully. Please log in.")
        else:
            flash("Unable to reset password. Please try again.")

        return redirect(url_for("status_login"))

    return render_template("reset.html", step="password")


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if (request.form.get("username") == ADMIN_USERNAME and
                request.form.get("password") == ADMIN_PASSWORD):
            session["logged_in"] = True
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials.")
    return render_template("admin_login.html")



@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    conn = get_db()
    cur = None

    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT status, count(*) FROM applications GROUP BY status"
        )
        by_status = cur.fetchall()

        cur.execute(
            "SELECT count(*) FROM applications WHERE status = 'PENDING' "
            "AND submitted_at < %s",
            (datetime.now() - timedelta(days=SLA_DAYS),),
        )
        overdue = cur.fetchone()[0]

        cur.execute(
            "SELECT block, count(*) FROM applications WHERE status = 'PENDING' "
            "GROUP BY block ORDER BY count(*) DESC"
        )
        by_block = cur.fetchall()

    finally:
        if cur is not None:
            cur.close()
        conn.close()

    return render_template(
        "admin_dashboard.html",
        by_status=by_status,
        overdue=overdue,
        by_block=by_block,
        sla=SLA_DAYS,
    )



@app.route("/admin/applications")
def admin_list():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    status = request.args.get("status", "PENDING")
    page = int(request.args.get("page", 1))

    conn = get_db()
    cur = None

    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, application_no, applicant_name, mobile, block, status, "
            "submitted_at FROM applications WHERE status = %s "
            "ORDER BY submitted_at ASC LIMIT 50 OFFSET %s",
            (status, (page - 1) * 50),
        )
        rows = cur.fetchall()
    finally:
        if cur is not None:
            cur.close()
        conn.close()

    return render_template(
        "admin_list.html",
        rows=rows,
        status=status,
        page=page,
    )



@app.route("/admin/application/<int:app_id>")
def admin_view(app_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    conn = get_db()
    cur = None

    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT application_no, applicant_name, mobile, dob, gender, "
            "marital_status, village, block, bank_account, ifsc, doc_path, "
            "status, submitted_at, decided_at, decided_by "
            "FROM applications WHERE id = %s",
            (app_id,),
        )
        row = cur.fetchone()

    finally:
        if cur is not None:
            cur.close()
        conn.close()

    if not row:
        abort(404)

    return render_template("admin_view.html", a=row, app_id=app_id)



@app.route("/admin/approve/<int:app_id>", methods=["POST"])
def admin_approve(app_id):
    if not session.get("admin"):
        abort(403)

    conn = get_db()
    cur = None

    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE applications SET status = 'APPROVED', decided_at = %s "
            "WHERE id = %s AND status = 'PENDING'",
            (datetime.now(), app_id),
        )
        if cur.rowcount == 0:
            flash("Application not found or is no longer pending.")
            return redirect(url_for("admin_list"))
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        if cur is not None:
            cur.close()
        conn.close()

    flash("Application approved.")
    return redirect(url_for("admin_list"))


@app.route("/admin/reject/<int:app_id>", methods=["POST"])
def admin_reject(app_id):
    if not session.get("admin"):
        abort(403)

    conn = get_db()
    cur = None

    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE applications SET status = 'REJECTED', decided_at = %s "
            "WHERE id = %s AND status = 'PENDING'",
            (datetime.now(), app_id),
        )
        if cur.rowcount == 0:
            flash("Application not found or is no longer pending.")
            return redirect(url_for("admin_list"))
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        if cur is not None:
            cur.close()
        conn.close()

    flash("Application rejected.")
    return redirect(url_for("admin_list"))


@app.route("/admin/request-correction/<int:app_id>", methods=["POST"])
def admin_request_correction(app_id):
    if not session.get("admin"):
        abort(403)

    reason = request.form.get("correction_reason", "").strip()

    if not reason:
        flash("Please provide a correction reason.")
        return redirect(url_for("admin_view", app_id=app_id))

    if len(reason) > 1000:
        flash("Correction reason cannot exceed 1000 characters.")
        return redirect(url_for("admin_view", app_id=app_id))

    conn = get_db()
    cur = None

    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE applications
            SET status = 'CORRECTION_REQUIRED',
                correction_reason = %s,
                correction_requested_at = %s
            WHERE id = %s AND status = 'PENDING'
            """,
            (reason, datetime.now(), app_id),
        )

        if cur.rowcount == 0:
            conn.rollback()
            flash("Application not found or is not pending.")
            return redirect(url_for("admin_list"))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        if cur is not None:
            cur.close()
        conn.close()

    flash("Correction requested successfully.")
    return redirect(url_for("admin_list"))
# ---------------------------------------------------------------------------
# Unused / legacy
# ---------------------------------------------------------------------------

def export_to_excel(rows):
    # Was used for the monthly disbursement report before eKosh integration.
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["application_no", "name", "account", "ifsc", "amount"])
    for r in rows:
        writer.writerow(list(r) + ["250"])
    return out.getvalue()


def old_payment_gateway_callback(txn):
    # retained for reference; eChallan integration was descoped in Phase 2
    status = txn.get("STATUS")
    if status == "0300":
        return "SUCCESS"
    elif status == "0399":
        return "FAILED"
    return "PENDING"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
