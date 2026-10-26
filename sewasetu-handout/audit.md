# Sewa Setu Legacy Pension Portal: Comprehensive System Audit & Problem Analysis

**Document Version:** 1.0  
**Role:** Digital Fellow, Department of Social Welfare, Government of Purvanchal  
**Scope:** Forensic Codebase Audit, 6-Month Server Log Analysis, and Citizen Impact Assessment  
**Handout Root:** `sewasetu-handout/`

---

## Executive Summary

An exhaustive analysis of the codebase, the 100,000-citizen production database export (`seed.sql`), and 6 months of consolidated production logs (Jan–Jun 2026) was conducted. 

Every single complaint voiced by the Deputy Commissioner in `dc-briefing.mp3` has been traced to **specific lines of code, database schema omissions, and broken configuration paths**. Furthermore, multiple critical security vulnerabilities (SQL injection, broken authorization, unauthenticated PII leakage) were discovered that threaten the safety and privacy of elderly beneficiaries.

The following report details:
1. **The Forensic Evidence & Root Causes** for all reported issues.
2. **Exact File & Line Number Mappings** across the repository.
3. **Top 5 Fixes Ranked by Citizen Impact** (with rationale, implementation blueprint, and test strategy for your Loom presentation).
4. **Deliberate Non-Fixes** (issues identified but consciously deprioritized/left alone, as required for the DC briefing).
5. **Assessment Readiness Checklist** (handling tests, commit history, assessor admin credentials, and live deployment).

---

## 1. Problem Breakdown: The DC's Briefing vs. Forensic Evidence

### A. The Assamese Name Corruption ("????") and Names Cut in Half
* **DC's Observation:** An elderly citizen walked 2 hours because his acknowledgment slip printed his Assamese name as 4 question marks (`????`). Other citizens reported their names were cut in half despite typing them in full.
* **Root Cause 1: Arbitrary Byte Truncation (`sanitize()`)**
  * **Location:** [`app/app.py:L68-75`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L68-L75) & [`app/app.py:L252`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L252)
  * **Code:**
    ```python
    def sanitize(value, maxlen=20):
        if value is None:
            return ""
        value = value.strip()
        encoded = value.encode("utf-8")[:maxlen]
        return encoded.decode("utf-8", errors="ignore")
    ...
    name = sanitize(data.get("applicant_name", ""))
    ```
  * **Mechanism:**
    * In UTF-8, Assamese and Bengali characters take **3 bytes** per character.
    * Slicing `[:20]` allows at most **6 characters** (`6 * 3 = 18 bytes`).
    * Any typical Indian name (e.g., "প্ৰণৱ কলিতা" / Pranab Kalita) is truncated to just the first name and the initial of the surname (e.g. `প্ৰণৱ ক`).
    * Even worse, if byte 20 falls inside a 3-byte sequence, `errors="ignore"` drops the truncated byte, corrupting the final glyph.
    * Inspection of `seed.sql` confirms rows 98,929–98,948 all have truncated Assamese names cut at byte 18–19.
* **Root Cause 2: FPDF Unicode Incompatibility & Font Fallback (`????`)**
  * **Location:** [`app/app.py:L346-368`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L346-L368)
  * **Code:**
    ```python
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    ...
    for label, val in zip(labels, row):
        try:
            pdf.cell(60, 8, label, border=1)
            pdf.cell(0, 8, str(val), border=1, ln=1)
        except Exception:
            pdf.cell(0, 8, "?", border=1, ln=1)
    ```
  * **Mechanism:**
    * Core fonts in `fpdf2` (`Helvetica`, `Times`, `Courier`) only support `latin-1` (ISO-8859-1).
    * When `pdf.cell()` attempts to render Indic Unicode characters (U+0980 to U+09FF), `fpdf2` raises `FPDFUnicodeEncodingException`.
    * In standard PDF font fallbacks or encoding replacements, 4 Unicode characters outside Latin-1 without glyph mapping display as `????`.
    * To support Assamese/Indic scripts, a TrueType Unicode font (e.g., Noto Sans Bengali/Assamese or FreeSerif) must be registered with `pdf.add_font()`.

---

### B. Deemed Approval Failure (The "Holi Incident")
* **DC's Observation:** Under the Right to Public Services (RTPS) Act, pending applications must be automatically approved after 15 days of silence. The nightly automated job stopped working around Holi (March 2026), and files have been sitting for months.
* **Forensic Evidence in `logs/cron.log`:**
  * Successful runs: Jan 1 to Mar 14, 2026:
    ```
    2026-03-14 02:00:02 deemed approval: 10 applications approved
    ```
  * Exact breaking date: **March 15, 2026**:
    ```
    Traceback (most recent call last):
      File "/app/scripts/deemed_approval.py", line 24, in <module>
        with open(CONFIG_PATH) as fh:
    FileNotFoundError: [Errno 2] No such file or directory: '/app/config/settings.ini'
    ```
* **Root Cause:**
  * **Location:** [`app/scripts/deemed_approval.py:L23-25`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/scripts/deemed_approval.py#L23-L25) vs [`app/config/app.ini:L2`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/config/app.ini#L2)
  * In March 2026 (change request `CR-2026-031`), vendor developers consolidated `config/settings.ini` into `config/app.ini`.
  * `app.py` was updated to read `app.ini`, but `deemed_approval.py` was forgotten and still pointed to `settings.ini`.
  * As a direct consequence, **4,874 pending applications** accumulated in the database between March and October 2026 with no decisions.
* **Secondary Deemed Approval Issues:**
  * **Container Timezone:** Container runs in UTC. `0 2 * * *` in UTC runs at 07:30 AM IST.
  * **Network Bottleneck:** When the backlog of 4,874 applications is cleared, looping over them with synchronous `requests.post()` calls with `timeout=5` will take hours or freeze the scheduler.
  * **Status Portal Transparency:** In `view_application()`, the query displays the raw database status. If an application is older than 15 days, it must either be updated by the batch job or dynamically computed and shown as deemed approved to the citizen.

---

### C. Month-End Performance Degradation & Service Outage
* **DC's Observation:** "2 or 3 days before the disbursement deadline, the whole site crawls to a halt. My staff shrug: 'Server slow down hai, sir. Kya karein?' The day after, it stops mattering."
* **Forensic Evidence from Access Logs & App Logs:**
  * Traffic surges from ~1,000 requests/day to **80,000 requests/day** on the 28th–31st of every month (Jan 30: 80,131; Mar 30: 78,940; Apr 29: 79,527; May 28: 76,432; Jun 30: 70,359).
  * On these dates, logs record **6,886 HTTP 500 errors** and **6,873 HTTP 504 Gateway Timeouts**.
  * Over **11,118 entries** in `sewasetu-app.log` record:
    ```
    ERROR in app: (psycopg2.OperationalError) FATAL: sorry, too many clients already
    ```
* **Root Causes:**
  1. **Synchronous CPU-Melting PDF Generation on Form Submission:**
     * **Location:** [`app/app.py:L326`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L326) & [`app/app.py:L355-358`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L355-L358)
     * Every `POST /declaration` generates a PDF inside the HTTP request.
     * `generate_acknowledgment` contains a loop:
       ```python
       for i in range(0, 2000):
           x = 10 + (i % 190)
           pdf.line(x, 282, x + 0.5, 282)
           pdf.line(x, 12, x + 0.5, 12)
       ```
       Drawing **4,000 vector lines per PDF** pins the CPU core for 1–2 seconds.
     * Gunicorn only has 4 workers (`--workers 4`). With 4 concurrent applicants, all 4 workers are 100% CPU bound.
  2. **Sequential Scans on 100,000 Rows (Zero Indexes):**
     * **Location:** [`app/schema.sql:L5-24`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/schema.sql#L5-L24)
     * The `applications` table has only `PRIMARY KEY (id)`.
     * Zero indexes on `mobile`, `submitted_at`, `status`, or `block`.
     * Every submission executes `SELECT count(*) FROM applications WHERE mobile = %s`, doing a full table scan across 100,000 rows.
     * Citizen logins execute `SELECT id FROM applications WHERE mobile = %s ORDER BY submitted_at DESC LIMIT 1`, another full table scan.
  3. **Database Connection Leaks & Exhaustion:**
     * **Location:** [`app/app.py:L58-65`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L58-L65)
     * No connection pool is used (`psycopg2.connect` is called directly).
     * When Gunicorn kills workers that exceed the 30-second timeout (`--timeout 30`), backend PostgreSQL connections are abandoned, hitting PostgreSQL's `max_connections = 100`.

---

### D. Data Leak & Citizen Privacy Violation ("Salesmen at the Door")
* **DC's Observation:** "Meera says there is a rumor that the moment you apply on the portal, you start getting phone calls. Salesmen. People turning up at your door trying to sell you things."
* **Forensic Evidence:**
  * Access logs show **20,573 requests** querying `/ack/<id>.pdf` across sequential and random IDs.
* **Root Cause 1: Completely Public, Unauthenticated PII PDF Route**
  * **Location:** [`app/app.py:L423-437`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L423-L437)
  * `GET /ack/<int:app_id>.pdf` requires **no session, no login, and no authorization**.
  * Any third-party scraper can iterate `1..100000` to download acknowledgment slips containing:
    * Applicant Name
    * Mobile Number
    * Date of Birth
    * Village & Block
    * Bank Account Number & IFSC Code
* **Root Cause 2: Insecure Direct Object Reference (IDOR) on Application Status**
  * **Location:** [`app/app.py:L406-421`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L406-L421)
  * `GET /application/<int:app_id>` checks `if not session.get("logged_in")`, but never verifies whether `app_id` belongs to `session.get("portal_mobile")`!
  * Any citizen who logs in with their own mobile number can simply modify the URL to `/application/1`, `/application/2`, etc., and view other citizens' private financial and personal records.

---

### E. The Broken Digital Form & Bazaar Middlemen
* **DC's Observation:** Eligible senior citizens cannot get through the digital form; middlemen in the bazaar charge fees because "only they have figured out how it works."
* **Root Causes:**
  1. **Upload Form Trap (`ERR_VAL_47`):**
     * **Location:** [`app/templates/upload.html:L5-6`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/templates/upload.html#L5-L6) vs [`app/app.py:L221-226`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L221-L226)
     * The UI explicitly says: *"Accepted formats: JPG or PDF, maximum size 5 MB."*
     * The backend code strictly requires:
       ```python
       if not filename.endswith(".pdf"):
           flash("ERR_VAL_47")
           return render_template("upload.html")
       if len(content) > 102400:
           flash("ERR_VAL_47")
           return render_template("upload.html")
       ```
     * JPG uploads are rejected outright. PDFs larger than **100 KB** (102,400 bytes) are rejected.
     * The error shown to the elderly citizen is the incomprehensible code `ERR_VAL_47`.
  2. **American Date Format (`%m/%d/%Y`) Preference:**
     * **Location:** [`app/app.py:L274-279`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L274-L279)
     * Code parses `for fmt in ("%m/%d/%Y", "%d/%m/%Y")`.
     * The placeholder prompts `DD/MM/YYYY`, but the code parses month first. A citizen born on June 5 (`05/06/1960`) is recorded as born on May 6.
     * If entered in ISO format (`YYYY-MM-DD`), it fails completely with the unhelpful message: *"Something went wrong. Please try again."*
  3. **Absurd Widowed Field Requirement:**
     * **Location:** [`app/app.py:L267-270`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L267-L270)
     * Code checks:
       ```python
       if marital == "Widowed":
           if not husband_name or not husband_employer:
               flash("Something went wrong. Please try again.")
               return redirect(url_for("form_step", step=1))
       ```
     * A widow is forced to enter her deceased husband's *current employer*. If left blank, she is booted back to step 1 with zero explanation.
  4. **Unhelpful, Cryptic Error Messages:**
     * Almost every validation failure in `handle_submission()` defaults to `flash("Something went wrong. Please try again.")`, never indicating which field was invalid.
  5. **No Verification of Captcha:**
     * **Location:** [`app/app.py:L140-156`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L140-L156)
     * `apply()` renders a math captcha and stores `session["captcha_answer"]`, but `POST /apply` never compares the user's submitted captcha to the session!
  6. **Short Session Expiry (5 Minutes):**
     * **Location:** [`app/app.py:L31`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L31)
     * `app.config["PERMANENT_SESSION_LIFETIME"] = 300` (5 minutes). Senior citizens typing slowly on a mobile device get their session wiped mid-application.

---

### F. Overflowing Helpdesk: Inability to Correct Mistakes
* **DC's Observation:** "People begging us to cancel their application because they made one small mistake... no way to fix it, no way to go back."
* **Root Cause:**
  * **Location:** [`app/app.py:L297-302`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L297-L302)
  * As soon as an application is submitted, `mobile` is locked.
  * The portal has no mechanism for a citizen to view draft details, edit pending submissions, or withdraw/cancel an incorrect pending application.
  * The admin panel only has "Approve" and "Reject" buttons; staff cannot cancel or return an application for correction.

---

### G. Security Vulnerabilities (Automated Probe Target Areas)

1. **Staff Authorization Bypass (Acting as Staff Without Authority):**
   * **Location:** [`app/app.py:L532-557`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L532-L557)
   * `POST /admin/approve/<id>` and `POST /admin/reject/<id>` only check:
     ```python
     if not session.get("logged_in"):
         abort(403)
     ```
   * Because any citizen logged into `/status` has `session["logged_in"] = True`, **any citizen can send a POST request to approve or reject any application in the state!** It must check `session.get("admin")`.
2. **SQL Injection in Password Reset:**
   * **Location:** [`app/app.py:L446-449`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L446-L449)
   * Direct string interpolation:
     ```python
     cur.execute("SELECT mobile FROM portal_users WHERE mobile = '%s'" % mobile)
     cur.execute("SELECT dob FROM applications WHERE mobile = '%s' LIMIT 1" % mobile)
     ```
   * Open to union-based SQL injection and authentication bypass.
3. **Hardcoded Secrets & Default Admin Credentials:**
   * `ADMIN_USERNAME = "admin"`, `ADMIN_PASSWORD = "sewasetu@123"` in [`app/app.py:L33-34`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L33-L34).
   * Secret key: `ssp-prod-key-2023-donotshare` in [`app/config/app.ini:L12`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/config/app.ini#L12) allows cookie forgery with tools like `flask-unsign`.
4. **Unrestricted File Upload / Path Traversal:**
   * `path = os.path.join(UPLOAD_DIR, "%s_%s" % (session["verified_mobile"], filename))` without using `werkzeug.utils.secure_filename`.

---

## 2. Complete File-by-File Vulnerability Map

| File Path | Lines | Vulnerability / Bug Description | Severity |
| :--- | :--- | :--- | :--- |
| [`app/scripts/deemed_approval.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/scripts/deemed_approval.py) | 23–25 | Broken file path (`settings.ini` instead of `app.ini`); broke auto-approvals since March 15 | **Critical** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 68–75, 252 | `sanitize(maxlen=20)` truncates UTF-8 Indian names to 20 bytes (~6 chars), cutting them in half | **Critical** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 346–372 | FPDF Helvetica font crashes on Assamese Unicode; decorative border runs 4,000 line draw calls | **Critical** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 423–437 | `/ack/<id>.pdf` has no authentication; public PII leak harvested by commercial scrapers | **Critical** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 406–421 | `/application/<id>` has IDOR; any logged-in citizen can view any other citizen's full records | **Critical** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 534, 548 | Broken Access Control: checks `session.get("logged_in")` instead of `"admin"`; citizens can approve/reject | **Critical** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 446, 449 | SQL injection via `%s` string interpolation in `/status/reset` | **Critical** |
| [`app/schema.sql`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/schema.sql) | 5–24 | Missing database indexes on `mobile`, `status`, `submitted_at`; causes 504 timeouts under load | **High** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 58–65 | No connection pooling; connection leaks during timeout spikes exhaust Postgres client limit | **High** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 215–226 | Upload rejects JPGs (contrary to UI) and caps at 100 KB instead of 5 MB, throwing `ERR_VAL_47` | **High** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 267–270 | Widows forced to provide deceased husband's current employer; blocks eligible citizens | **High** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 274–282 | Date parsing prioritizes `%m/%d/%Y` over `%d/%m/%Y`; rejects ISO dates with generic error | **Medium** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 140–156 | Math captcha generated and displayed, but never validated in `POST /apply` | **Medium** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 33–34, config | Hardcoded default admin credentials (`admin`/`sewasetu@123`) and shared secret key | **Medium** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 31 | Session lifetime is only 300 seconds (5 minutes); logs out slow-typing seniors | **Medium** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 228 | Unsafe path join with raw uploaded filename (`secure_filename` missing) | **Medium** |
| [`app/app.py`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py) | 297–302 | Strict mobile lock without edit/cancel flow leaves citizens stuck on clerical errors | **Medium** |

---

## 3. Top 5 Fixes Ranked by Citizen Impact (For Your Loom Video)

The brief requires you to present your **top 5 fixes ranked by citizen impact, with reasons, in order**. Here is the recommended ranking and the citizen-first justification:

```mermaid
graph TD
    F1["1. Restore RTPS Deemed Approval Job<br><b>Impact:</b> Legally grants pension to 4,874+ stranded seniors"] --> F2["2. Plug PII Data Leak & IDOR<br><b>Impact:</b> Stops commercial harassment & financial exploitation"]
    F2 --> F3["3. Fix Assamese / Indic Name Storage & PDF Slip<br><b>Impact:</b> Citizen dignity & valid legal proof of identity"]
    F3 --> F4["4. Fix Month-End Concurrency & Crash Spikes<br><b>Impact:</b> Prevents portal outage when citizens need it most"]
    F4 --> F5["5. Fix Form Usability & File Upload Trap<br><b>Impact:</b> Eliminates middleman corruption in bazaars"]
```

### Rank 1: Restoring the RTPS 15-Day Deemed Approval Engine
* **Citizen Impact:** Under the Right to Public Services Act, statutory silence equals automatic entitlement. Because of a simple configuration typo (`settings.ini`), **4,874 elderly citizens** have been waiting up to 7 months for pensions they are legally owed. Restoring this fulfills the primary purpose of the welfare state.
* **What to Fix:**
  * In [`app/scripts/deemed_approval.py:L23`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/scripts/deemed_approval.py#L23), change `CONFIG_PATH` to `app.ini`.
  * Ensure the scheduler container runs with the correct crontab and timezone (`Asia/Kolkata`).
  * In the status portal (`/application/<id>`), if an application is still pending after 15 days, compute deemed approval dynamically if the cron hasn't executed yet.
* **Test Case:** Submit an application with a backdated submission timestamp (`now - 16 days`); run the deemed approval routine; verify that status transitions to `DEEMED_APPROVED`, `decided_by` becomes `'RTPS-AUTO'`, SMS is triggered, and the citizen view shows approved.

---

### Rank 2: Securing Citizen Data (Plug Public PDF Leak & IDOR)
* **Citizen Impact:** Elderly rural citizens are prime targets for financial fraud and predatory salesmen. The open `/ack/<id>.pdf` route and IDOR on `/application/<id>` exposed 100,000 citizens' bank accounts, mobile numbers, dates of birth, and home addresses to web scrapers.
* **What to Fix:**
  * Restrict `/ack/<int:app_id>.pdf` to authenticated users: verify that either `session.get("admin")` is true OR `session.get("portal_mobile")` matches the application's mobile number.
  * In `/application/<int:app_id>`, enforce that non-admin sessions can only view applications matching `session.get("portal_mobile")`.
* **Test Case:**
  1. Send an unauthenticated `GET /ack/1.pdf` -> Expect HTTP 401 or redirect to login.
  2. Log in as Citizen A, attempt `GET /application/<id_of_Citizen_B>` -> Expect HTTP 403 Forbidden.

---

### Rank 3: Full Indic Unicode Support & Fixing Truncated Names
* **Citizen Impact:** A government acknowledgment slip is often an elderly citizen's only physical proof of application. Having one's native language name printed as `????` or chopped in half strips their dignity and causes bureaucratic rejection.
* **What to Fix:**
  * In [`app/app.py:L68-75`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L68-L75), update `sanitize()` to measure length in **characters** (or increase byte limit to 100 bytes to match `VARCHAR(100)` in Postgres) rather than a rigid 20-byte cutoff.
  * In [`app/app.py:L346-372`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L346-L372), add a TrueType Unicode font (such as Noto Sans Assamese/Bengali or FreeSerif) to FPDF via `pdf.add_font()` so Indic characters render faithfully in PDF slips.
* **Test Case:** Submit an application with name `"প্ৰণৱ কলিতা"` (Pranab Kalita, 11 Assamese characters, 33 bytes); assert the database stores the exact 11 characters; generate the PDF and verify it renders without exception or question marks.

---

### Rank 4: Eliminating Month-End Server Lockups (Indexes & Async/Fast PDF)
* **Citizen Impact:** Citizens rushed to apply right before the month-end deadline, only to be met with 504 timeouts and database crashes.
* **What to Fix:**
  * Add database indexes in Postgres:
    ```sql
    CREATE INDEX IF NOT EXISTS idx_applications_mobile ON applications(mobile);
    CREATE INDEX IF NOT EXISTS idx_applications_status_submitted ON applications(status, submitted_at);
    CREATE INDEX IF NOT EXISTS idx_portal_users_mobile ON portal_users(mobile);
    ```
  * In `generate_acknowledgment()`, delete the 2,000-iteration decorative line-drawing loop ([`app/app.py:L355-358`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L355-L358)) which wastes seconds of CPU time per request.
  * Implement basic connection closing in a `finally` block or Flask teardown to prevent connection leaks.
* **Test Case:** Concurrently query `/application/<id>` and submit `POST /declaration` with 20 parallel clients; measure response times drop from >30s to <200ms with 0 database connection errors.

---

### Rank 5: Removing Bazaar Middleman Traps (Upload Limits, Dates, & Widowed Rule)
* **Citizen Impact:** Predatory middlemen in the bazaar were profiting off seniors because the form had hidden traps: rejecting JPGs, capping PDFs at an impossible 100 KB with the cryptic error `ERR_VAL_47`, demanding dead husbands' current employers, and misparsing dates.
* **What to Fix:**
  * In [`app/app.py:L221-226`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L221-L226): Accept `.jpg`, `.jpeg`, and `.png` in addition to `.pdf`; raise upload size limit to 5 MB (`5 * 1024 * 1024` bytes); replace `ERR_VAL_47` with human-readable error messages.
  * In [`app/app.py:L267-270`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L267-L270): Remove the mandatory requirement for `husband_employer` when status is "Widowed".
  * In [`app/app.py:L274-279`](file:///c:/Users/trade/Downloads/sewasetu-handout/sewasetu-handout/app/app.py#L274-L279): Parse `%d/%m/%Y` and ISO format `%Y-%m-%d` before `%m/%d/%Y`.
* **Test Case:** Upload a 2 MB valid JPG file and submit as a widowed applicant without husband employer; assert successful application submission.

---

## 4. What Was Deliberately Left Alone (And Why)

In your Loom briefing to the DC, explaining what you **consciously chose NOT to do** shows senior engineering maturity. You should mention:

1. **Re-skinning / Modernizing the Entire Front-End UI:**
   * *Rationale:* The UI looks dated ("Designed for 1024x768"), but the automated assessor specifically states: *"We are not scoring visual polish, feature count, or how many tools you installed."* Rewriting the frontend in React/Next.js would introduce regressions and break the automated probe's HTML element selectors.
2. **Replacing SQLite/Postgres with a New Database or Microservices:**
   * *Rationale:* The single-node Postgres database easily handles 100,000 citizens once proper B-Tree indexes are applied and connection leaks are plugged. Re-architecting would create unnecessary operational risk for a 30-day evaluation period.
3. **Modifying or Rewriting Seed Citizen Records:**
   * *Rationale:* The brief specifically warns: *"Do not delete or alter existing citizen records except where a fix requires it. This is production data. Treat the people in it accordingly."*
4. **Descoping Legacy Payment Gateway Callback / Excel Export Stubs:**
   * *Rationale:* Code in `old_payment_gateway_callback()` and `export_to_excel()` is dead code from descoped phases. Removing them provides zero citizen impact and risks unintended side effects.

---

## 5. Strategic Preparation Checklist for Final Submission

When you implement your fixes, keep these procedural requirements in mind:

* [ ] **Git Commit Structure:**
  * For each of the top 5 fixes:
    1. Commit 1: Write an automated test that reproduces the bug (must FAIL).
    2. Commit 2: Implement the fix in the code (test now PASSES).
  * Do not squash your commits. The assessor clones your repository and verifies that tests fail before a fix and pass after.
* [ ] **Private GitHub Repository:**
  * Create a private GitHub repository.
  * Invite `harshnisar` as a read-only collaborator (accepted automatically).
* [ ] **Repository Zip:**
  * Create a `.zip` archive including the `.git` folder (excluding `seed/seed.sql` and the log archive to stay well under 100 MB).
* [ ] **Admin Credentials for Assessor:**
  * If you fix the staff authorization bypass and rotate the hardcoded credentials, ensure the new username and password are provided in the submission form.
* [ ] **Public Deployment:**
  * Deploy using Docker Compose on any standard VPS (AWS, DigitalOcean, Hetzner, etc.).
  * Ensure the SMS gateway console remains reachable at `/__gateway/` through port 8000.
  * Keep the VPS running for up to 30 days until notified.
