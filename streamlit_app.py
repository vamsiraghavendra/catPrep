"""Streamlit UI: Aeon Vocab + Fetch Merriam Webster."""

import html
import io
import json
import os
import subprocess
import sys
import streamlit as st

from aeon_vocab_lookup import build_vocab_report

st.set_page_config(
    page_title="Vocab Tools",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Light blue & white theme + component styles
st.markdown("""
<style>
    /* Theme: light blue & white */
    .stApp { background: linear-gradient(180deg, #f0f7ff 0%, #ffffff 30%); }
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #e3f2fd 0%, #f5f9ff 100%); }
    [data-testid="stSidebar"] .stMarkdown { color: #1565c0; }

    .tag-row { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.5rem 0 1rem 0; }
    .tag {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 500;
    }
    .tag-count { background: #1976d2; color: #fff; font-weight: 700; }
    .tag-genre { background: #bbdefb; color: #0d47a1; }
    .tag-author { background: #e3f2fd; color: #1565c0; }
    .tag-topic { background: #b3e5fc; color: #0277bd; }
    .entry-card {
        background: #ffffff;
        border-radius: 12px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 0.75rem;
        border-left: 4px solid #42a5f5;
        box-shadow: 0 1px 3px rgba(21,101,192,0.08);
    }
    .word-title { font-size: 1rem; font-weight: 700; letter-spacing: 0.08em; color: #0d47a1; }
    .example-label { font-size: 0.7rem; color: #5c6bc0; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 0.5rem; }
    .example-text { font-size: 0.9rem; color: #37474f; line-height: 1.5; margin-top: 0.25rem; }
    .synonym-tag {
        display: inline-block;
        padding: 0.2rem 0.5rem;
        border-radius: 6px;
        font-size: 0.8rem;
        background: #e3f2fd;
        color: #1565c0;
        margin: 0.15rem 0.25rem 0.15rem 0;
    }
    .analysis-block { margin: 1rem 0; padding: 0.75rem 0; }
    .analysis-label { font-size: 0.7rem; color: #5c6bc0; text-transform: uppercase; letter-spacing: 0.06em; }
    .main-idea { font-size: 0.9rem; color: #37474f; line-height: 1.5; margin-top: 0.25rem; }
    .tone-tag {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 500;
        background: #fff3e0;
        color: #e65100;
        margin-top: 0.25rem;
    }
    .mw-word-chip {
        display: inline-block;
        padding: 0.35rem 0.7rem;
        margin: 0.2rem;
        border-radius: 8px;
        background: #e3f2fd;
        color: #1565c0;
        font-weight: 500;
    }
    /* Sidebar nav buttons */
    .nav-btn { width: 100%; margin-bottom: 0.5rem; text-align: center; }
    /* Landing page */
    .hero-title { font-size: 2rem; font-weight: 700; color: #0d47a1; margin-bottom: 0.5rem; }
    .hero-subtitle { font-size: 1.1rem; color: #546e7a; margin-bottom: 2rem; line-height: 1.6; }
    .tool-card {
        background: #ffffff;
        border-radius: 16px;
        padding: 1.5rem 2rem;
        margin: 1rem 0;
        border: 2px solid #bbdefb;
        box-shadow: 0 4px 12px rgba(21,101,192,0.08);
        transition: all 0.2s ease;
    }
    .tool-card:hover { border-color: #42a5f5; box-shadow: 0 6px 16px rgba(21,101,192,0.12); }
    .tool-card h3 { color: #1565c0; margin-top: 0; }
    .tool-card p { color: #546e7a; margin-bottom: 1rem; }
    /* Donate page */
    .donate-shell {
        background: #ffffff;
        border: 2px solid #bbdefb;
        border-radius: 16px;
        padding: 1.25rem 1.5rem;
        box-shadow: 0 4px 12px rgba(21,101,192,0.08);
        margin-top: 0.5rem;
    }
    .donate-caption {
        text-align: center;
        color: #546e7a;
        font-size: 0.95rem;
        margin-top: 0.25rem;
    }
    .donate-copy {
        margin-top: 1rem;
        background: #f8fbff;
        border-radius: 12px;
        border: 1px solid #dbeafe;
        padding: 1rem 1.1rem;
        color: #455a64;
        line-height: 1.65;
    }
    .donate-image-wrap {
        background: #f8fbff;
        border-radius: 12px;
        border: 1px solid #dbeafe;
        padding: 0.9rem;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# Session state for component selection
if "component" not in st.session_state:
    st.session_state.component = "Home"

view_map = {
    "home": "Home",
    "aeon": "Aeon Vocab",
    "mw": "Fetch Merriam Webster",
    "donate": "Donate",
}
view = str(st.query_params.get("view", "")).lower()
if view in view_map:
    st.session_state.component = view_map[view]

# Sidebar: selectable buttons
with st.sidebar:
    st.markdown("### 📖 Vocab Tools")
    st.markdown("---")
    st.markdown("**Choose a tool**")
    if st.button("🏠 Home", key="nav_home", width="stretch"):
        st.session_state.component = "Home"
        st.query_params["view"] = "home"
        st.rerun()
    if st.button("📰 Aeon Vocab", key="nav_aeon", width="stretch"):
        st.session_state.component = "Aeon Vocab"
        st.query_params["view"] = "aeon"
        st.rerun()
    if st.button("📚 Fetch Merriam Webster", key="nav_mw", width="stretch"):
        st.session_state.component = "Fetch Merriam Webster"
        st.query_params["view"] = "mw"
        st.rerun()
    if st.button("💝 Donate", key="nav_donate", width="stretch"):
        st.session_state.component = "Donate"
        st.query_params["view"] = "donate"
        st.rerun()

component = st.session_state.component

# Main content based on selection
if component == "Home":
    st.markdown('<p class="hero-title">Welcome to Vocab Tools</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="hero-subtitle">Extract and learn vocabulary for GMAT/CAT prep. Choose a tool from the sidebar to get started.</p>',
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        with st.container():
            st.markdown("""
            <a href="?view=aeon" target="_self" style="text-decoration:none;color:inherit;display:block;">
                <div class="tool-card">
                    <h3>📰 Aeon Vocab</h3>
                    <p>Paste an Aeon article URL and extract GMAT/CAT-level vocabulary with definitions, examples, and synonyms.</p>
                </div>
            </a>
            """, unsafe_allow_html=True)
    with col2:
        with st.container():
            st.markdown("""
            <a href="?view=mw" target="_self" style="text-decoration:none;color:inherit;display:block;">
                <div class="tool-card">
                    <h3>📚 Fetch Merriam Webster</h3>
                    <p>Log in and fetch your Saved Words from merriam-webster.com, then view definitions and synonyms for each word.</p>
                </div>
            </a>
            """, unsafe_allow_html=True)

elif component == "Aeon Vocab":
    st.markdown("## 📰 Aeon Vocab")
    st.markdown("Extract GMAT/CAT vocabulary from Aeon articles with definitions and synonyms.")
    st.markdown("---")
    st.info(
        "Please enter an Aeon article URL so we can extract key vocabulary and provide "
        "meanings, example usage, and synonyms."
    )

    url = st.text_input(
        "Article URL",
        placeholder="https://aeon.co/essays/...",
        label_visibility="collapsed",
    )

    if st.button("Extract", type="primary", width="stretch"):
        if not url or not url.strip():
            st.warning("Enter an Aeon article URL.")
        else:
            with st.spinner("Extracting vocabulary…"):
                try:
                    report = build_vocab_report(url.strip())
                except Exception as e:
                    st.error(str(e))
                    st.stop()

            # Article header
            st.markdown(f"**{report['article_title']}**")

            tags_html = '<div class="tag-row">'
            if report.get("word_count"):
                tags_html += f'<span class="tag tag-count">{report["word_count"]} words</span>'
            if report.get("genre"):
                tags_html += f'<span class="tag tag-genre">{report["genre"]}</span>'
            if report.get("author"):
                tags_html += f'<span class="tag tag-author">{report["author"]}</span>'
            if report.get("topics"):
                for t in report["topics"]:
                    tags_html += f'<span class="tag tag-topic">{t}</span>'
            tags_html += "</div>"
            st.markdown(tags_html, unsafe_allow_html=True)

            # Main idea and tone (above Open article)
            if report.get("main_idea") or report.get("tone"):
                analysis_html = '<div class="analysis-block">'
                if report.get("main_idea"):
                    analysis_html += '<div class="analysis-label">Main idea</div>'
                    analysis_html += f'<div class="main-idea">{html.escape(report["main_idea"])}</div>'
                if report.get("tone"):
                    analysis_html += '<div class="analysis-label" style="margin-top:0.5rem;">Tone</div>'
                    analysis_html += f'<span class="tag tone-tag">{html.escape(report["tone"])}</span>'
                analysis_html += "</div>"
                st.markdown(analysis_html, unsafe_allow_html=True)

            st.link_button("Open article", report["article_url"], width="stretch")
            st.divider()

            # Vocabulary cards
            for entry in report["entries"]:
                word_upper = html.escape(entry["word"].upper())
                card = '<div class="entry-card">'
                card += f'<div class="word-title">{word_upper}</div>'
                if entry.get("definition"):
                    card += '<div class="example-label">Definition</div>'
                    card += f'<div class="example-text">{html.escape(entry["definition"])}</div>'
                if entry.get("example_usage"):
                    ex = entry["example_usage"][0]
                    if not ex.startswith("Definition:") or not entry.get("definition"):
                        card += '<div class="example-label" style="margin-top:0.5rem;">Example</div>'
                        card += f'<div class="example-text">{html.escape(ex)}</div>'
                if entry.get("synonyms"):
                    card += '<div class="example-label" style="margin-top:0.6rem;">Synonyms</div>'
                    card += '<div style="margin-top:0.25rem;">'
                    for syn in entry["synonyms"]:
                        card += f'<span class="synonym-tag">{html.escape(syn)}</span>'
                    card += "</div>"
                card += "</div>"
                st.markdown(card, unsafe_allow_html=True)

elif component == "Fetch Merriam Webster":
    # Fetch Merriam Webster
    st.markdown("## 📚 Fetch Merriam Webster")
    st.markdown("Scrape your Saved Words from merriam-webster.com and view definitions from Dictionary & Thesaurus.")
    st.markdown("---")

    st.info(
        "Enter your Merriam-Webster credentials so we can securely retrieve your saved words, "
        "including meanings, example usage, and synonyms."
    )

    email = st.text_input("Email", placeholder="your@email.com", type="default")
    password = st.text_input("Password", placeholder="••••••••", type="password")
    st.caption(
        "Your password is not stored by this application. It is used only for a one-time "
        "sign-in to your Merriam-Webster account in order to retrieve saved words, since "
        "Merriam-Webster does not provide a direct API for this data."
    )
    st.warning(
        "This process may take some time (3 - 5 min). Please wait for the results to load, and avoid "
        "switching, refreshing, or closing the tab while retrieval is in progress."
    )

    if st.button("Fetch Saved Words", type="primary", width="stretch"):
        if not email or not password:
            st.warning("Enter your email and password.")
        else:
            with st.spinner("Logging in and scraping Saved Words…"):
                # Run Playwright in a separate process to avoid asyncio/subprocess
                # conflicts on Windows when called from Streamlit
                app_dir = os.path.dirname(os.path.abspath(__file__))
                runner = os.path.join(app_dir, "fetch_mw_runner.py")
                env = os.environ.copy()
                env["MW_EMAIL"] = email
                env["MW_PASSWORD"] = password
                try:
                    result = subprocess.run(
                        [sys.executable, runner],
                        capture_output=True,
                        text=True,
                        env=env,
                        cwd=app_dir,
                        timeout=300,
                    )
                except subprocess.TimeoutExpired:
                    st.error("Fetch timed out after 5 minutes.")
                    st.stop()
                except Exception as e:
                    st.error(str(e))
                    st.stop()

                out = (result.stdout or "").strip()
                err_out = (result.stderr or "").strip()
                if result.returncode != 0 and not out:
                    st.error(f"Fetch failed: {err_out or 'Unknown error'}")
                    st.stop()

                try:
                    data = json.loads(out)
                except json.JSONDecodeError:
                    st.error(f"Invalid response: {out[:200]}")
                    st.stop()

                if "error" in data:
                    st.error(f"Fetch failed: {data['error']}")
                    st.stop()

                words = data.get("words", [])

            if not words:
                st.warning("No words found. Check your credentials.")
                st.stop()

            st.success(f"Fetched **{len(words)}** saved words. Fetching definitions and synonyms…")

            with st.spinner("Fetching definitions (Dictionary) and synonyms (Thesaurus) for each word…"):
                try:
                    from merriamCode import build_word_entries_from_mw

                    entries = build_word_entries_from_mw(words)
                except Exception as e:
                    st.error(str(e))
                    st.stop()

            # Summary tag
            st.markdown(f'<div class="tag-row"><span class="tag tag-count">{len(entries)} words</span></div>', unsafe_allow_html=True)
            st.divider()

            # Word cards (same style as Aeon vocab)
            for entry in entries:
                word_upper = html.escape(entry["word"].upper())
                card = '<div class="entry-card">'
                card += f'<div class="word-title">{word_upper}</div>'
                if entry.get("definition"):
                    card += '<div class="example-label">Definition</div>'
                    card += f'<div class="example-text">{html.escape(entry["definition"])}</div>'
                if entry.get("example_usage"):
                    ex = entry["example_usage"][0]
                    if not ex.startswith("Definition:") or not entry.get("definition"):
                        card += '<div class="example-label" style="margin-top:0.5rem;">Example</div>'
                        card += f'<div class="example-text">{html.escape(ex)}</div>'
                if entry.get("synonyms"):
                    card += '<div class="example-label" style="margin-top:0.6rem;">Synonyms</div>'
                    card += '<div style="margin-top:0.25rem;">'
                    for syn in entry["synonyms"]:
                        card += f'<span class="synonym-tag">{html.escape(syn)}</span>'
                    card += "</div>"
                card += "</div>"
                st.markdown(card, unsafe_allow_html=True)

            # Download buttons
            st.divider()
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    "Download JSON",
                    data=json.dumps([{"word": e["word"], "definition": e.get("definition"), "synonyms": e.get("synonyms")} for e in entries], indent=2),
                    file_name="words.json",
                    mime="application/json",
                    width="stretch",
                )
            with col2:
                csv_buf = io.StringIO()
                csv_buf.write("word,definition,synonyms\n")
                for e in entries:
                    defn = (e.get("definition") or "").replace('"', '""')
                    syns = "; ".join(e.get("synonyms") or [])
                    syns = syns.replace('"', '""')
                    csv_buf.write(f'"{e["word"]}","{defn}","{syns}"\n')
                st.download_button(
                    "Download CSV",
                    data=csv_buf.getvalue(),
                    file_name="words.csv",
                    mime="text/csv",
                    width="stretch",
                )

elif component == "Donate":
    st.markdown("## 💝 Support This Project")
    st.markdown("If this tool saves you time, you can support ongoing development.")
    st.markdown("---")

    left_col, right_col = st.columns([1, 1.35], gap="large")
    with left_col:
        qr_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "GooglePay_QR.png")
        pad_l, image_col, pad_r = st.columns([0.08, 0.84, 0.08])
        with image_col:
            st.image(qr_path, width="stretch")
        st.markdown(
            '<div class="donate-caption">Scan with Google Pay</div>',
            unsafe_allow_html=True,
        )
    with right_col:
        st.markdown(
            """
            <div class="donate-copy">
                Lorem ipsum dolor sit amet, consectetur adipiscing elit. Integer posuere erat a ante venenatis dapibus posuere velit aliquet.
                Curabitur blandit tempus porttitor. Donec ullamcorper nulla non metus auctor fringilla. Praesent commodo cursus magna,
                vel scelerisque nisl consectetur et. Aenean lacinia bibendum nulla sed consectetur.
            </div>
            """,
            unsafe_allow_html=True,
        )
