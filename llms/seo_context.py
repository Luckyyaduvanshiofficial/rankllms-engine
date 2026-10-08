"""
SEO context builders for RankLLMs pages.

The leaderboard/catalog pages render their tables from JavaScript after
load. Search crawlers increasingly execute JS, but a server-rendered row
set guarantees the content exists in the initial HTML — and gives every
page real, keyword-relevant body copy instead of a "Loading..." placeholder.

Each template has its own column layout, so each gets its own renderer.
All three read the same merged ``rankindex`` table the API serves, so
crawlable HTML and the live API never disagree.
"""

from math import isfinite

from django.utils.html import escape

from llms.models import RankIndex


def _esc(value):
    """HTML-escape one cell value."""
    return escape(str(value)) if value not in (None, "") else "—"


def _fmt_price(value):
    if value is None or value == "":
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"${num:.2f}" if isfinite(num) and num >= 0 else "—"


def _fmt_ctx(value):
    if value is None or value <= 0:
        return "—"
    if value >= 1_000_000:
        return f"{float(value) / 1_000_000:.1f}M"
    return f"{round(float(value) / 1000)}k"


def _fmt_pct(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "—"
    if not isfinite(num):
        return "—"
    return f"{(num * 100 if num <= 1.0 else num):.1f}%"


def _medal(rank):
    if rank is None:
        return "—"
    if rank == 1:
        return '<span class="lb-medal medal-1">#1</span>'
    if rank == 2:
        return '<span class="lb-medal medal-2">#2</span>'
    if rank == 3:
        return '<span class="lb-medal medal-3">#3</span>'
    return f'<span class="lb-medal">#{rank}</span>'


def _fmt_score(value):
    if value is None or value == "":
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "—"
    if not isfinite(num):
        return "—"
    return f"{num:.1f}"


def _score_cell(value, cls="score"):
    return f'<td class="{cls}">{_fmt_score(value)}</td>'


def _src_badges(sources):
    badges = {
        "openrouter": '<wa-badge appearance="outlined" pill>OR</wa-badge>',
        "artificial-analysis": '<wa-badge appearance="outlined" pill>AA</wa-badge>',
        "design-arena": '<wa-badge appearance="outlined" pill>Arena</wa-badge>',
    }
    seen = []
    for s in sources or []:
        if s in badges and s not in seen:
            seen.append(s)
    return " ".join(badges[s] for s in seen)


def _base_rows(limit):
    """Shared field set from the merged rankindex, best-ranked first."""
    return RankIndex.objects.order_by("rank_overall", "-rankllms_index").values(
        "rank_overall",
        "name",
        "provider",
        "canonical_slug",
        "openrouter_id",
        "rankllms_index",
        "intelligence_index",
        "coding_index",
        "agentic_index",
        "terminalbench_hard",
        "gpqa_diamond",
        "context_length",
        "max_output_tokens",
        "tokens_per_second",
        "release_date",
        "prompt_price_per_1m",
        "completion_price_per_1m",
        "is_free",
        "is_open_weight",
        "has_openrouter",
        "has_artificial_analysis",
        "has_design_arena",
        "sources",
    )[:limit]


def leaderboard_rows(limit=50):
    """
    Top N rows rendered as <tr> HTML matching the client-side render()
    output in llm_leaderboard.html (10 columns).
    """
    out = []
    for m in _base_rows(limit):
        price = (
            '<span class="price-free">Free</span>'
            if m["is_free"]
            else _fmt_price(m["prompt_price_per_1m"])
        )
        open_badge = (
            ' <wa-badge variant="success" appearance="outlined" pill>Open</wa-badge>'
            if m["is_open_weight"]
            else ""
        )

        out.append(
            f"""<tr>
  <td class="num">{_medal(m['rank_overall'])}</td>
  <td class="model-cell">{_esc(m['name'])}{open_badge}
    <span class="slug">{_esc(m['canonical_slug'] or m['openrouter_id'])}</span>
  </td>
  <td class="provider">{_esc(m['provider'])}</td>
  {_score_cell(m['rankllms_index'], 'score score-index')}
  {_score_cell(m['intelligence_index'])}
  {_score_cell(m['coding_index'], 'score score-code')}
  <td class="score">{_fmt_pct(m['gpqa_diamond'])}</td>
  <td class="num">{_fmt_ctx(m['context_length'])}</td>
  <td class="num" style="text-align: right;">{price}</td>
  <td class="num">{_src_badges(m['sources']) or '—'}</td>
</tr>"""
        )
    return "\n".join(out)


def rankindex_rows(limit=10):
    """
    Top N rows for rankindex.html (9 columns: model & provider combined,
    single in/out price cell). Mirrors the client-side renderTable() there.
    """
    out = []
    for m in _base_rows(limit):
        price_str = (
            '<span class="price-free">Free</span>'
            if m["is_free"]
            else f"{_fmt_price(m['prompt_price_per_1m'])} / {_fmt_price(m['completion_price_per_1m'])}"
        )
        open_badge = (
            ' <wa-badge appearance="outlined" pill>Open-Weight</wa-badge>'
            if m["is_open_weight"]
            else ""
        )
        tb = _fmt_pct(m["terminalbench_hard"])
        if tb != "—":
            code_str = f"<strong>{tb} TB</strong>"
        elif m["coding_index"] is not None:
            code_str = f'<span class="score-code">{float(m["coding_index"]):.1f}</span>'
        else:
            code_str = "-"

        out.append(
            f"""<tr>
  <td class="num lb-rank">{_medal(m['rank_overall'])}</td>
  <td class="model-cell">{_esc(m['name'])}{open_badge}<span class="slug">{_esc(m['provider'])} &bull; {_esc(m['canonical_slug'] or m['openrouter_id'])}</span></td>
  <td class="score score-index">{_fmt_score(m['rankllms_index'])}</td>
  <td class="score">{_fmt_score(m['intelligence_index'])}</td>
  <td class="score">{code_str}</td>
  <td class="score">{_fmt_pct(m['gpqa_diamond'])}</td>
  <td class="num">{_fmt_ctx(m['context_length'])}</td>
  <td class="num" style="text-align: right;">{price_str}</td>
  <td class="num">{_src_badges(m['sources']) or '—'}</td>
</tr>"""
        )
    return "\n".join(out)


def models_rows(limit=50):
    """
    Top N rows for rankllms_models.html (15-column full catalog). Mirrors
    the client-side renderTable() there, including max output, speed and
    release date columns.
    """
    out = []
    for m in _base_rows(limit):
        p_in = _fmt_price(m["prompt_price_per_1m"])
        p_out = _fmt_price(m["completion_price_per_1m"])
        speed = f"{round(float(m['tokens_per_second']))}" if m["tokens_per_second"] is not None else "—"
        released = (
            str(m["release_date"])[:10] if m["release_date"] else "—"
        )
        max_out = (
            f"{round(m['max_output_tokens'] / 1000)}k"
            if m["max_output_tokens"]
            else "—"
        )
        flags = []
        if m["is_open_weight"]:
            flags.append('<wa-badge variant="success" appearance="outlined" pill>Open</wa-badge>')
        if m["is_free"]:
            flags.append('<wa-badge variant="neutral" appearance="outlined" pill>Free</wa-badge>')
        if m["has_openrouter"]:
            flags.append('<wa-badge appearance="outlined" pill>OR</wa-badge>')
        if m["has_artificial_analysis"]:
            flags.append('<wa-badge appearance="outlined" pill>AA</wa-badge>')
        if m["has_design_arena"]:
            flags.append('<wa-badge appearance="outlined" pill>Arena</wa-badge>')

        out.append(
            f"""<tr>
  <td class="num lb-rank">{_medal(m['rank_overall'])}</td>
  <td class="model-cell">{_esc(m['name'])}<span class="slug">{_esc(m['canonical_slug'] or m['openrouter_id'])}</span></td>
  <td class="provider">{_esc(m['provider'])}</td>
  <td class="score score-index">{_fmt_score(m['rankllms_index'])}</td>
  {_score_cell(m['intelligence_index'])}
  {_score_cell(m['coding_index'], 'score score-code')}
  {_score_cell(m['agentic_index'])}
  <td class="score">{_fmt_pct(m['gpqa_diamond'])}</td>
  <td class="num">{_fmt_ctx(m['context_length'])}</td>
  <td class="num">{max_out}</td>
  <td class="num" style="text-align: right;">{p_in if not m['is_free'] else '<span class="price-free">Free</span>'}</td>
  <td class="num" style="text-align: right;">{p_out if not m['is_free'] else '<span class="price-free">Free</span>'}</td>
  <td class="score">{speed}</td>
  <td class="num">{released}</td>
  <td class="num">{' '.join(flags) or '<span class="provider">—</span>'}</td>
</tr>"""
        )
    return "\n".join(out)


def item_list_jsonld(limit=10):
    """
    Structured JSON-LD for the leaderboard ItemList — real ranked entries
    with position, so the markup stays valid even before JS hydrates.
    """
    items = []
    for position, m in enumerate(_base_rows(limit), start=1):
        items.append(
            {
                "@type": "ListItem",
                "position": position,
                "name": m["name"] or "—",
            }
        )
    return items


def get_seo_context(page):
    """
    Per-page SEO context. Shared by every template so titles, descriptions
    and JSON-LD stay consistent between the rendered HTML and the API.
    """
    pages = {
        "llm-leaderboard": {
            "title": "LLM Leaderboard — Free AI Model Rankings by Intelligence, Coding & Value | RankLLMs",
            "description": "Free LLM leaderboard ranked by the RankLLMs composite index. Compare AI models by intelligence, coding, reasoning, value, context, and price — powered by the merged rankindex source of truth.",
            "h1": "LLM Leaderboard",
            "lede": "The RankLLMs leaderboard ranks AI models by intelligence, coding, and value. Every score is merged from OpenRouter, Artificial Analysis, and Design Arena into one source of truth — free, no signup.",
        },
        "rankllms": {
            "title": "RankLLMs — AI Models Ranking & LLM Leaderboard by Intelligence, Coding & Benchmarks",
            "description": "RankLLMs ranks AI models with a composite index built from OpenRouter, Artificial Analysis, Design Arena and models.dev. AI model rankings, benchmark matrix, pricing, and open-weight flags.",
            "h1": "RankLLMs — AI Models Ranking & LLM Leaderboard",
            "lede": "The RankLLMs index ranks AI models on intelligence, coding, reasoning and value. Merged from OpenRouter, Artificial Analysis, Design Arena and models.dev — one source of truth, free to browse.",
        },
        "rankllms-models": {
            "title": "All AI Models — Full Catalog with Rankings, Pricing & Specs | RankLLMs",
            "description": "Browse every AI model in the RankLLMs source of truth: ranks, intelligence/coding scores, context, pricing, speed, and open-weight flags — all in one sortable catalog.",
            "h1": "All AI Models",
            "lede": "Every model in the merged RankLLMs source of truth, with full ranking, benchmark, pricing, and capability data. Sort by any column.",
        },
    }
    ctx = dict(pages.get(page, {}))
    ctx["page_key"] = page
    return ctx
