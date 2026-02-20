from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pydeck as pdk
import streamlit as st

from config import OUTPUT_DIR
from tools.geocoding import geocode_address


st.set_page_config(
    page_title="Surelock Homes Streamlit",
    page_icon="🧭",
    layout="wide",
)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _find_runs(output_dir: Path) -> List[Path]:
    if not output_dir.exists():
        return []
    runs: List[Path] = []
    for child in output_dir.iterdir():
        if not child.is_dir():
            continue
        result_file = child / "result.json"
        if result_file.exists():
            runs.append(child)
    return sorted(runs, key=lambda p: p.name, reverse=True)


def _extract_addresses(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []

    for flag in payload.get("flagged", []) or []:
        provider = flag.get("provider", {}) if isinstance(flag, dict) else {}
        address = ""
        if isinstance(flag, dict):
            address = str(flag.get("address") or "").strip()
        if not address and isinstance(provider, dict):
            address = str(provider.get("address") or "").strip()
        if address:
            records.append(
                {
                    "address": address,
                    "label": str(provider.get("name") or flag.get("provider_name") or "Flagged provider"),
                    "kind": "flagged",
                }
            )

    for call in payload.get("tool_calls", []) or []:
        if not isinstance(call, dict):
            continue
        args = call.get("arguments") or call.get("input") or {}
        if not isinstance(args, dict):
            continue
        address = str(args.get("address") or "").strip()
        if not address:
            continue
        tool_name = str(call.get("tool") or "tool")
        records.append(
            {
                "address": address,
                "label": tool_name,
                "kind": "investigated",
            }
        )

    deduped: Dict[tuple[str, str], Dict[str, str]] = {}
    for row in records:
        key = (row["address"], row["kind"])
        deduped[key] = row
    return list(deduped.values())


@st.cache_data(show_spinner=False)
def _geocode_rows(address_rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    geocoded: List[Dict[str, Any]] = []
    for row in address_rows:
        geocode = geocode_address(row["address"])
        lat = geocode.get("lat")
        lng = geocode.get("lng")
        if lat is None or lng is None:
            continue
        geocoded.append(
            {
                "address": row["address"],
                "label": row["label"],
                "kind": row["kind"],
                "lat": float(lat),
                "lng": float(lng),
                "source": geocode.get("status", "unknown"),
            }
        )
    return geocoded


def _build_map(df: pd.DataFrame) -> pdk.Deck:
    color_map = {
        "flagged": [220, 38, 38, 190],
        "investigated": [37, 99, 235, 120],
    }
    plot_df = df.copy()
    plot_df["color"] = plot_df["kind"].map(lambda k: color_map.get(k, [100, 116, 139, 120]))
    plot_df["radius"] = plot_df["kind"].map(lambda k: 220 if k == "flagged" else 130)

    center_lat = float(plot_df["lat"].mean())
    center_lng = float(plot_df["lng"].mean())

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=plot_df,
        get_position="[lng, lat]",
        get_fill_color="color",
        get_radius="radius",
        pickable=True,
    )

    return pdk.Deck(
        map_provider="carto",
        map_style=pdk.map_styles.CARTO_LIGHT,
        initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lng, zoom=10),
        layers=[layer],
        tooltip={"text": "{label}\n{address}\n{kind}"},
    )


def _render_thinking_analysis(payload: Dict[str, Any]) -> None:
    analysis = payload.get("thinking_analysis")
    if not isinstance(analysis, dict):
        st.info("No thinking analysis found in this run.")
        return

    st.markdown(f"**Summary:** {analysis.get('summary', 'No summary available.')}")

    coverage = analysis.get("coverage", {})
    c1, c2, c3 = st.columns(3)
    c1.metric("Provider Baseline", coverage.get("provider_search_count", "N/A"))
    c2.metric("Investigated Addresses", coverage.get("investigated_address_count", "N/A"))
    c3.metric("Uninvestigated (Est.)", coverage.get("uninvestigated_provider_estimate", "N/A"))

    with st.expander("Signals Considered", expanded=True):
        signals = analysis.get("signals_considered", [])
        if signals:
            st.dataframe(pd.DataFrame(signals), use_container_width=True, hide_index=True)
        else:
            st.write("No signal data.")

    with st.expander("Unsurfaced Leads", expanded=True):
        leads = analysis.get("unsurfaced_leads", [])
        if leads:
            st.dataframe(pd.DataFrame(leads), use_container_width=True, hide_index=True)
        else:
            st.write("No unsurfaced leads.")

    with st.expander("Dropped Paths", expanded=False):
        dropped = analysis.get("dropped_paths", [])
        if dropped:
            st.dataframe(pd.DataFrame(dropped), use_container_width=True, hide_index=True)
        else:
            st.write("No dropped paths.")

    notes = analysis.get("notes", [])
    if notes:
        st.markdown("**Notes**")
        for note in notes:
            st.markdown(f"- {note}")


def main() -> None:
    st.title("Surelock Homes - Streamlit Review Console")
    st.caption("Map + narration + thinking analysis viewer for saved investigation runs.")

    runs = _find_runs(OUTPUT_DIR)
    if not runs:
        st.warning("No saved runs found in output/. Run an investigation first.")
        return

    run_options = {run.name: run for run in runs}
    selected_run_id = st.sidebar.selectbox("Select run", options=list(run_options.keys()))
    selected_run = run_options[selected_run_id]
    payload = _read_json(selected_run / "result.json")

    st.sidebar.markdown("### Run Meta")
    st.sidebar.write(f"**Mode:** {payload.get('mode', 'unknown')}")
    st.sidebar.write(f"**Status:** {payload.get('status', 'unknown')}")
    st.sidebar.write(f"**Query:** {payload.get('query', 'N/A')}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Providers", payload.get("provider_count", "N/A"))
    m2.metric("Flags", len(payload.get("flagged", []) or []))
    m3.metric("Turns", payload.get("turns", "N/A"))
    m4.metric("Tool Calls", len(payload.get("tool_calls", []) or []))

    tab_map, tab_narration, tab_thinking, tab_tools = st.tabs(
        ["Map", "Narration", "Thinking Analysis", "Tool Calls"]
    )

    with tab_map:
        rows = _extract_addresses(payload)
        geocoded_rows = _geocode_rows(rows)
        if not geocoded_rows:
            st.info("No mappable addresses found in this run.")
        else:
            df = pd.DataFrame(geocoded_rows)
            st.pydeck_chart(_build_map(df), use_container_width=True)
            st.dataframe(
                df[["kind", "label", "address", "source", "lat", "lng"]],
                use_container_width=True,
                hide_index=True,
            )

    with tab_narration:
        report = str(payload.get("report_text") or "").strip()
        narration = str(payload.get("narration") or "").strip()
        if report:
            st.markdown("### Final Report")
            st.markdown(report)
        elif narration:
            st.markdown("### Investigation Narration")
            st.markdown(narration)
        else:
            st.info("No narration content available.")

    with tab_thinking:
        _render_thinking_analysis(payload)

    with tab_tools:
        tool_calls = payload.get("tool_calls", []) or []
        if not tool_calls:
            st.info("No tool calls in this payload.")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "tool": tc.get("tool"),
                            "status": tc.get("status"),
                            "arguments": json.dumps(tc.get("arguments") or tc.get("input") or {}, ensure_ascii=False),
                        }
                        for tc in tool_calls
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
            with st.expander("Raw payload JSON", expanded=False):
                st.code(json.dumps(payload, indent=2), language="json")


if __name__ == "__main__":
    main()
