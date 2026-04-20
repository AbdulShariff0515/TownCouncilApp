import streamlit as st
import streamlit.components.v1 as components
import textwrap
from datetime import datetime


def format_timestamp(ts):
    if not ts:
        return ""
    if isinstance(ts, str):
        ts = ts.replace("Z", "+00:00")  # safe for ISO strings
        ts = datetime.fromisoformat(ts)
    return ts.strftime("%d %b %Y · %H:%M")


def inject_css():
    st.markdown(
        """
        <style>
        .timeline {
            display: flex;
            justify-content: space-between;
            position: relative;
            margin: 30px 0;
        }
        .timeline::before {
            content: "";
            position: absolute;
            top: 50%;
            left: 0;
            right: 0;
            height: 4px;
            background: #e0e0e0;
            z-index: 0;
        }
        .node {
            text-align: center;
            z-index: 1;
            width: 18%;
        }
        .circle {
            width: 46px;
            height: 46px;
            border-radius: 50%;
            line-height: 46px;
            margin: auto;
            color: #fff;
            font-weight: 700;
            cursor: pointer;
        }
        .done { background: #2e7d32; }
        .current {
            background: #1976d2;
            box-shadow: 0 0 0 6px rgba(25,118,210,.25);
        }
        .pending { background: #bdbdbd; }
        .label {
            margin-top: 8px;
            font-size: 14px;
            font-weight: 600;
        }
        .badge {
            margin-top: 4px;
            font-size: 10px;
            background: #ffb300;
            border-radius: 4px;
            padding: 2px 6px;
            display: inline-block;
        }

        </style>
        
        """,
        unsafe_allow_html=True,
    )


def render_case_timeline(timeline: list, current_status: str):
    inject_css()
    reached = True

    # ✅ OPEN timeline container
    st.markdown("<div class='timeline'>", unsafe_allow_html=True)

    for i, step in enumerate(timeline):
        if reached and step["status"] != current_status:
            style = "done"
        elif step["status"] == current_status:
            style = "current"
            reached = False
        else:
            style = "pending"

        badge = (
            "<div class='badge'>AI override</div>"
            if step.get("ai_override")
            else ""
        )
 
        components.html(
            f"""
            <style>
                 body {{
                    background: transparent;
                    color: #e0e0e0;
                    font-family: sans-serif;
                }}
                .node {{
                    text-align: center;
                    margin-bottom: 28px;
                }}
                .circle {{
                    width: 46px;
                    height: 46px;
                    border-radius: 50%;
                    line-height: 46px;
                    margin: auto;
                    color: #fff;
                    font-weight: 700;
                    background: { '#1976d2' if style == 'current' else '#2e7d32' if style == 'done' else '#bdbdbd' };
                }}
                .label {{
                    margin-top: 8px;
                    font-size: 14px;
                    font-weight: 600;
                }}
                .timestamp {{
                    margin-top: 4px;
                    font-size: 11px;
                    color: #9e9e9e;
                }}
                .badge {{
                    margin-top: 4px;
                    font-size: 10px;
                    background: #ffb300;
                    border-radius: 4px;
                    padding: 2px 6px;
                    display: inline-block;
                    color: #000;
                }}
                
                .notes {{
                    display: none;
                    margin-top: 6px;
                    font-size: 12px;
                    color: #cfd8dc;
                    line-height: 1.4;
                }}
            </style>

            <script>
            function toggleNotes(id) {{
                const el = document.getElementById(id);
                if (!el) return;
                el.style.display = el.style.display === "block" ? "none" : "block";
            }}
            </script>

            <div class="node">
                <div class="circle" onclick="toggleNotes('notes-{i}')">
                    {step["label"][:2].upper()}
                </div>

                <div class="label">{step["label"]}</div>

                <div class="timestamp">
                    {format_timestamp(step.get("created_at"))}
                </div>

                <!-- ✅ HIDDEN NOTES -->
                <div class="notes" id="notes-{i}">
                {step.get("notes", "")}
                </div>

                {badge}
            </div>
            """,
            height=190,
        )


    # ✅ CLOSE timeline container (THIS IS IMPORTANT)
    st.markdown("</div>", unsafe_allow_html=True)
