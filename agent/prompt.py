from pathlib import Path
from typing import Optional

from config import current_utc_date


def load_system_prompt(
    *,
    target_state: Optional[str] = None,
    target_zip: Optional[str] = None,
    max_turns: Optional[int] = None,
) -> str:
    path = Path(__file__).resolve().parents[1] / "surelock-homes-system-prompt.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("{dynamic_date}", current_utc_date())

    # Inject geographic scope anchor when a target area is known
    if target_state:
        scope_parts = [f"state={target_state}"]
        if target_zip:
            scope_parts.append(f"ZIP={target_zip}")
        scope_str = ", ".join(scope_parts)
        scope_block = (
            f"\n\n<investigation_scope>\n"
            f"TARGET AREA: {scope_str}\n"
            f"All provider searches and tool calls MUST use state=\"{target_state}\". "
            f"Do not search for or investigate providers in other states unless you "
            f"find a specific, documented cross-state connection (e.g., same registered "
            f"agent or owner operating in both states). If you pursue a cross-state lead, "
            f"note it explicitly and return to {scope_str} immediately after.\n"
            f"</investigation_scope>"
        )
        text += scope_block

    # Inject turn budget so the LLM can plan its investigation up front
    if max_turns and max_turns > 0:
        budget_block = (
            f"\n\n<turn_budget>\n"
            f"TURN BUDGET: You have {max_turns} turns for investigation. "
            f"Each turn = one LLM response (which may include multiple tool calls).\n"
            f"The final report will be generated AUTOMATICALLY after your investigation "
            f"turns are complete — do NOT write the report yourself.\n\n"
            f"MANDATORY PLANNING STEP — before calling any investigation tools:\n"
            f"1. First call search_childcare_providers to see all providers in the area\n"
            f"2. Count providers by type: DCC/Child Care Center (deep investigation) vs "
            f"DCH/Family (quick triage) vs GDC/Group (quick triage)\n"
            f"3. Plan your turn budget:\n"
            f"   - ALL {max_turns} turns are for investigation — no need to reserve turns "
            f"for the report\n"
            f"   - Each turn can include MULTIPLE tool calls — batch property lookups "
            f"and capacity calcs for 3-5 providers per turn\n"
            f"4. Choose your strategy based on DCC count:\n"
            f"   - Under 10 DCCs: Deep investigation each (property, capacity, places, "
            f"licensing, business reg, street view)\n"
            f"   - 10-25 DCCs: Property + capacity + licensing for all; deep dive only "
            f"flagged ones\n"
            f"   - 25+ DCCs: Batch screening — property + capacity for all in batches "
            f"of 5-8 per turn; deep dive only anomalies\n"
            f"   - DCH/GDC: Quick capacity check only (DCH ≤ 12, GDC ≤ 16); skip "
            f"unless capacity exceeds type limits\n"
            f"5. State your plan in the narration before starting tool calls\n\n"
            f"EFFICIENCY RULES:\n"
            f"- Call multiple tools per turn — don't waste a turn on a single tool call\n"
            f"- Don't call get_street_view until you've identified providers worth "
            f"deep investigation via property + capacity screening\n"
            f"- Don't call check_business_registration for every provider — only for "
            f"flagged ones\n"
            f"- Track progress after each batch: \"Investigated X of Y DCCs, Z turns "
            f"remaining\"\n"
            f"- Do NOT write the final report — it will be generated separately after "
            f"your investigation\n"
            f"</turn_budget>"
        )
        text += budget_block

    return text

