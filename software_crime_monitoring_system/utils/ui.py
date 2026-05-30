"""Shared UI helpers: responsive styling, header, auth guard, KPI cards, badges."""
import streamlit as st
import config as C

# --- set_page_config guard -------------------------------------------------
# With the st.navigation router (app.py) the page config is set once at the top.
# Individual page scripts also call st.set_page_config(...); Streamlit only allows
# it once per run, so we make subsequent calls safe no-ops instead of errors.
if not getattr(st, "_phq_spc_guarded", False):
    _orig_spc = st.set_page_config
    def _guarded_spc(*a, **k):
        if st.session_state.get("_phq_page_config_done"):
            return
        try:
            _orig_spc(*a, **k)
        except Exception:
            pass
        st.session_state["_phq_page_config_done"] = True
    st.set_page_config = _guarded_spc
    st._phq_spc_guarded = True

PALETTE = {"normal": "#16a34a", "warning": "#d97706", "critical": "#dc2626",
           "unknown": "#6b7280", "primary": "#2563eb"}
_ICON = {"normal": "✓", "warning": "!", "critical": "✕", "unknown": "?"}


def inject_css():
    # Streamlit re-executes the page script on every interaction, so we re-emit the style
    # block; browsers harmlessly de-duplicate identical <style> selectors. Trying to "cache"
    # this via st.session_state is wrong (it would skip injection on subsequent reruns and
    # the page would lose its styles).
    st.markdown(
        """
        <style>
          :root{ --brand:#1e3a8a; --brand2:#2563eb; --ink:#0f172a; --muted:#64748b; --line:#e6e9ef; }
          .block-container {padding-top: 1.2rem; padding-bottom: 2.5rem; max-width: 1180px;}
          html, body, [class*="css"] {font-feature-settings:"cv11","ss01"; }
          /* header banner */
          .app-header {background: linear-gradient(100deg,#172554 0%,#1e40af 55%,#2563eb 100%);
              color:#fff; padding: 18px 22px; border-radius: 16px; margin-bottom: 18px;
              box-shadow: 0 6px 18px rgba(30,64,175,.18);}
          .app-header h1 {font-size: 1.3rem; margin: 0; font-weight: 700; letter-spacing:.2px;}
          .app-header p {margin: 4px 0 0; font-size: 0.82rem; opacity: .92;}
          /* KPI cards */
          .kpi {background:#fff; border:1px solid var(--line); border-radius:16px; padding:16px 18px;
              box-shadow:0 2px 8px rgba(15,23,42,.05); height:100%; transition:transform .12s ease, box-shadow .12s ease;
              border-top:3px solid var(--brand2);}
          .kpi:hover{ transform:translateY(-2px); box-shadow:0 8px 20px rgba(15,23,42,.09); }
          .kpi .label {font-size:.7rem; color:var(--muted); text-transform:uppercase; letter-spacing:.07em; font-weight:600;}
          .kpi .value {font-size:1.6rem; font-weight:800; color:var(--ink); margin-top:4px; line-height:1.1;}
          .kpi .sub {font-size:.74rem; color:#94a3b8; margin-top:2px;}
          /* badges */
          .badge {display:inline-flex; align-items:center; gap:6px; padding:4px 12px; border-radius:999px;
              font-size:.74rem; font-weight:700; color:#fff; letter-spacing:.03em;}
          .badge .dot{width:8px;height:8px;border-radius:50%;background:rgba(255,255,255,.85);}
          /* banners */
          .scenario-warn {background:linear-gradient(90deg,#fffbeb,#fef3c7); border:1px solid #f59e0b;
              border-left:5px solid #d97706; color:#92400e; padding:12px 16px; border-radius:12px; font-size:.86rem; font-weight:500;}
          .note {background:#eff6ff; border:1px solid #bfdbfe; border-left:5px solid #2563eb; color:#1e40af;
              padding:9px 14px; border-radius:12px; font-size:.8rem;}
          /* section label */
          .section {font-size:.78rem; font-weight:700; color:var(--brand); text-transform:uppercase;
              letter-spacing:.06em; margin:6px 0 2px; border-bottom:2px solid var(--line); padding-bottom:4px;}
          /* tables: tidy, zebra, no clutter */
          [data-testid="stDataFrame"] {border:1px solid var(--line); border-radius:12px; overflow:hidden;}
          thead tr th {background:#f1f5f9 !important; color:#0f172a !important; font-weight:700 !important;}
          /* sidebar — dark, with explicit readable contrast (no broad '*' override that breaks
             buttons/badges) */
          section[data-testid="stSidebar"] {background:#0f172a;}
          section[data-testid="stSidebar"] h1,
          section[data-testid="stSidebar"] h2,
          section[data-testid="stSidebar"] h3,
          section[data-testid="stSidebar"] p,
          section[data-testid="stSidebar"] span,
          section[data-testid="stSidebar"] label,
          section[data-testid="stSidebar"] li {color:#e2e8f0;}
          section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
          section[data-testid="stSidebar"] small {color:#cbd5e1; line-height:1.35; overflow-wrap:anywhere;}
          /* nav links readable */
          section[data-testid="stSidebar"] a {color:#e2e8f0 !important; border-radius:8px;}
          section[data-testid="stSidebar"] a:hover {background:rgba(148,163,184,.18);}
          section[data-testid="stSidebar"] a[aria-current="page"] {background:rgba(37,99,235,.35); color:#fff !important;}
          /* logout button must stay visible on the dark sidebar */
          section[data-testid="stSidebar"] .stButton>button {
              background:#1e293b; color:#f8fafc; border:1px solid #475569; font-weight:600;}
          section[data-testid="stSidebar"] .stButton>button:hover {
              background:#dc2626; color:#fff; border-color:#dc2626;}
          /* role/admin badge readable on dark */
          .role-badge {display:inline-flex; align-items:center; gap:6px; padding:3px 10px;
              border-radius:999px; font-size:.72rem; font-weight:700; color:#0f172a;
              background:#e2e8f0; letter-spacing:.02em;}
          .role-badge.admin {background:#fde68a; color:#7c2d12;}
          .role-badge.reviewer {background:#bfdbfe; color:#1e3a8a;}
          .role-badge.operator {background:#bbf7d0; color:#14532d;}
          .role-badge.viewer {background:#e5e7eb; color:#374151;}
          /* buttons */
          .stButton>button {border-radius:10px; font-weight:600;}
          .stDownloadButton>button {border-radius:10px;}
          /* tables: container width + horizontal scroll where needed */
          [data-testid="stDataFrame"] div[data-testid="stHorizontalBlock"] {overflow-x:auto;}
          @media (max-width: 640px){
            .app-header h1{font-size:1.05rem;} .kpi .value{font-size:1.3rem;}
            .block-container{padding-left:.6rem; padding-right:.6rem;}
          }
        </style>
        """, unsafe_allow_html=True)


def header(subtitle: str = ""):
    inject_css()
    st.markdown(
        f"""<div class="app-header"><h1>🛡️ {C.APP_NAME}</h1>
        <p>{subtitle or C.APP_TAGLINE}</p></div>""", unsafe_allow_html=True)


def section(title: str):
    st.markdown(f'<div class="section">{title}</div>', unsafe_allow_html=True)


def sidebar_account():
    """Account block in the sidebar: name, readable role badge, and a visible Log out button.
    Navigation links are provided by the st.navigation router, so we do not duplicate them here."""
    inject_css()
    user = st.session_state.get("user")
    with st.sidebar:
        st.markdown("### 🛡️ PHQ Monitoring")
        st.caption("Reported-crime forecasting & monitoring")
        if user:
            role = str(user.get("role", "")).lower()
            st.markdown(f"**👤 {user['name']}**")
            st.markdown(f'<span class="role-badge {role}">{user["role"].upper()}</span>',
                        unsafe_allow_html=True)
            st.divider()
            if st.button("Log out", use_container_width=True, key="_logout_btn"):
                # Clear ALL session state on logout (user, cached form inputs, validation
                # report, last_run, last_drift_status, lockout buckets, etc.). This prevents
                # information leakage to a subsequent user on the same browser tab.
                for k in list(st.session_state.keys()):
                    if not k.startswith("_phq_"):  # keep the one-shot CSS guard
                        st.session_state.pop(k, None)
                st.rerun()


def require_login():
    inject_css()
    user = st.session_state.get("user")
    if not user:
        st.warning("Please log in from the **Home** page to access this section.")
        st.stop()
    sidebar_account()
    return user


def can(user, perm) -> bool:
    return perm in C.ROLE_PERMS.get(user["role"], set())


def kpi(col, label, value, sub=""):
    col.markdown(
        f"""<div class="kpi"><div class="label">{label}</div>
        <div class="value">{value}</div><div class="sub">{sub}</div></div>""",
        unsafe_allow_html=True)


def drift_badge(status: str) -> str:
    color = PALETTE.get(status, PALETTE["unknown"])
    icon = _ICON.get(status, "?")
    return (f'<span class="badge" style="background:{color}">'
            f'<span class="dot"></span>{icon} {status.upper()}</span>')


def scenario_warning():
    st.markdown(f'<div class="scenario-warn">{C.SCENARIO_WARNING}</div>', unsafe_allow_html=True)


def practical_note():
    st.markdown(f'<div class="note">{C.PRACTICAL_ACCURACY_NOTE}</div>', unsafe_allow_html=True)
