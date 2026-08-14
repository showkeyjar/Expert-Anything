"""Smart concept cards for ExpertAnything.

Provides an intelligent, proactive concept display that adapts to the learner's
state — showing mastery, priority, and recommended next steps at a glance.
"""
from __future__ import annotations

import flet as ft

from expert_anything.core.i18n import t


# ── colour palette (consistent with graph_widget) ────────────────────────────
_MASTERY_COLORS = {
    "mastered": (197, 230, 198),     # green
    "partial": (253, 235, 206),      # amber
    "weak": (250, 214, 202),         # orange
    "unstudied": (225, 228, 232),    # grey
    "anomaly": (255, 224, 178),      # light orange
}

_BORDER_COLORS = {
    "mastered": (46, 125, 50),
    "partial": (251, 140, 0),
    "weak": (206, 74, 27),
    "unstudied": (176, 190, 197),
    "anomaly": (230, 120, 40),
}

_TAG_COLORS = {
    "weak": (206, 74, 27),
    "anom": (230, 120, 40),
    "foundation": (2, 132, 199),
    "ready": (46, 125, 50),
    "blocked": (120, 144, 156),
    "path": (100, 116, 139),
}


def _mastery_level(m: float) -> str:
    if m >= 0.6:
        return "mastered"
    if m >= 0.3:
        return "partial"
    if m < 0.001:
        return "unstudied"
    return "weak"


def _chip_color(tag: str) -> tuple[int, int, int]:
    return _TAG_COLORS.get(tag, (120, 144, 156))


def _chip_bg(tag: str) -> str:
    r, g, b = _chip_color(tag)
    return f"#{r:02X}{g:02X}{b:02X}20"  # 20% opacity


def _mastery_bar(m: float, width: int = 80) -> ft.ProgressBar:
    color = ft.Colors.GREEN if m >= 0.6 else (ft.Colors.AMBER if m >= 0.3 else ft.Colors.ORANGE)
    return ft.ProgressBar(value=m, width=width, color=color, bgcolor=ft.Colors.GREY_200, height=6)


def concept_card(
    concept_name: str,
    mastery: float | None = None,
    tags: list[str] | None = None,
    is_top_recommendation: bool = False,
    has_anomaly: bool = False,
    on_click=None,
) -> ft.Control:
    """Render a single smart concept card.

    Parameters
    ----------
    concept_name : str
        Display name of the concept.
    mastery : float | None
        0..1 mastery level; None means unknown.
    tags : list[str] | None
        Reason tags like "weak", "anom", "foundation", etc.
    is_top_recommendation : bool
        If True, highlight as the #1 recommended next concept.
    has_anomaly : bool
        If True, add an orange border to indicate system anomaly.
    on_click : callable | None
        Called with the concept name when clicked.

    Returns
    -------
    ft.Container
        A card-style container with mastery indicator, tags, and actions.
    """
    level = _mastery_level(mastery or 0.0)
    fill_rgb = _MASTERY_COLORS[level]
    border_rgb = _BORDER_COLORS[level]
    hex_fill = f"#{fill_rgb[0]:02X}{fill_rgb[1]:02X}{fill_rgb[2]:02X}"
    hex_border = f"#{border_rgb[0]:02X}{border_rgb[1]:02X}{border_rgb[2]:02X}"

    # Tag chips
    tag_chips = []
    if tags:
        for tag in tags:
            if tag == "weak":
                tag_chips.append(ft.Container(
                    content=ft.Text("薄弱", size=9, color=(206, 74, 27)),
                    padding=ft.Padding(4, 2, 4, 2),
                    border_radius=4,
                    bgcolor="#CE4A1B20",
                ))
            elif tag == "anom":
                tag_chips.append(ft.Container(
                    content=ft.Text("存疑", size=9, color=(230, 120, 40)),
                    padding=ft.Padding(4, 2, 4, 2),
                    border_radius=4,
                    bgcolor="#E6782820",
                ))
            elif tag == "foundation":
                tag_chips.append(ft.Container(
                    content=ft.Text("基础", size=9, color=(2, 132, 199)),
                    padding=ft.Padding(4, 2, 4, 2),
                    border_radius=4,
                    bgcolor="#0284C720",
                ))
            elif tag == "ready":
                tag_chips.append(ft.Container(
                    content=ft.Text("可学", size=9, color=(46, 125, 50)),
                    padding=ft.Padding(4, 2, 4, 2),
                    border_radius=4,
                    bgcolor="#2E7D3220",
                ))
            elif tag == "blocked":
                tag_chips.append(ft.Container(
                    content=ft.Text("阻塞", size=9, color=(120, 144, 156)),
                    padding=ft.Padding(4, 2, 4, 2),
                    border_radius=4,
                    bgcolor="#78909C20",
                ))
            elif tag == "path":
                tag_chips.append(ft.Container(
                    content=ft.Text("路径", size=9, color=(100, 116, 139)),
                    padding=ft.Padding(4, 2, 4, 2),
                    border_radius=4,
                    bgcolor="#64748B20",
                ))

    # Mastery bar or indicator
    mastery_parts = []
    if mastery is not None:
        mastery_parts.append(_mastery_bar(mastery, width=100))
    elif is_top_recommendation:
        mastery_parts.append(ft.Text("新", size=9, color=ft.Colors.BLUE_700))

    # Border radius and shadow based on priority
    border_radius = 12 if is_top_recommendation else 8
    border_width = 2 if is_top_recommendation or has_anomaly else 1
    border_color = hex_border
    if has_anomaly:
        border_color = "#E67828"
    if is_top_recommendation:
        border_color = "#0284C7"

    card = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text(
                    concept_name,
                    size=13,
                    weight=ft.FontWeight.W_500 if is_top_recommendation else ft.FontWeight.W_400,
                    color=ft.Colors.GREY_900,
                    expand=True,
                    tooltip=concept_name,
                ),
                *tag_chips[-3:],  # max 3 tags
            ], spacing=6, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            *mastery_parts,
            ft.Row([
                ft.ElevatedButton(
                    t("learn_concept"),
                    icon=ft.Icons.SCHOOL,
                    height=26,
                    style=ft.ButtonStyle(
                        color=ft.Colors.WHITE,
                        bgcolor=ft.Colors.BLUE_600 if is_top_recommendation else ft.Colors.BLUE_400,
                        padding=ft.Padding.symmetric(horizontal=12, vertical=4),
                    ),
                    on_click=on_click,
                ),
            ], spacing=8, alignment=ft.MainAxisAlignment.END),
        ], spacing=6),
        padding=ft.Padding.symmetric(horizontal=12, vertical=10),
        border=ft.Border.all(border_width, border_color),
        border_radius=border_radius,
        bgcolor=hex_fill if not is_top_recommendation else "#E3F2FD",
        shadow=ft.BoxShadow(
            blur_radius=4 if is_top_recommendation else 2,
            color=(0, 0, 0, 0.1),
            offset=ft.Offset(0, 2),
        ),
        on_click=on_click,
    )
    return card


def smart_concept_list(
    concepts: list[dict],
    on_concept_click=None,
    title: str = "",
) -> ft.Control:
    """Render a list of concept cards with optional title.

    Parameters
    ----------
    concepts : list[dict]
        Each dict should have keys: 'name', 'mastery', 'tags', 'is_top'.
    on_concept_click : callable | None
        Called with (concept_name) when a card is clicked.
    title : str
        Optional section title.

    Returns
    -------
    ft.Column
        A column containing the title (if provided) and all concept cards.
    """
    cards = []
    for c in concepts:
        card = concept_card(
            concept_name=c["name"],
            mastery=c.get("mastery"),
            tags=c.get("tags"),
            is_top_recommendation=c.get("is_top", False),
            has_anomaly="anom" in (c.get("tags") or []),
            on_click=on_concept_click and (lambda e, name=c["name"]: on_concept_click(name)),
        )
        cards.append(card)
        cards.append(ft.Divider(height=4, color=ft.Colors.TRANSPARENT))  # spacing

    if not cards:
        empty = ft.Text(t("no_records"), size=12, color=ft.Colors.GREY_600, italic=True)
        return ft.Column([empty], horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    content = ft.Column(cards, spacing=0)
    if title:
        return ft.Column([
            ft.Text(title, size=14, weight=ft.FontWeight.W_600, color=ft.Colors.GREY_800),
            content,
        ], spacing=8)
    return content


def adaptive_queue_view(
    items: list[dict],
    on_concept_click=None,
) -> ft.Control:
    """Render the adaptive learning path as a ranked list of concept cards.

    Parameters
    ----------
    items : list[dict]
        Each dict should have keys: 'name', 'mastery', 'tags', 'cid'.
    on_concept_click : callable | None
        Called with (concept_id) when a card is clicked.

    Returns
    -------
    ft.Column
        A column with the title and all ranked concept cards.
    """
    if not items:
        return ft.Text(t("adaptive_path_empty"), size=12, color=ft.Colors.GREY_600)

    cards = []
    for rank, item in enumerate(items, start=1):
        is_top = rank == 1
        cid = item.get("cid", "")
        card = concept_card(
            concept_name=item["name"],
            mastery=item.get("mastery"),
            tags=item.get("tags", []),
            is_top_recommendation=is_top,
            has_anomaly="anom" in item.get("tags", []),
            on_click=on_concept_click and (lambda e, c=cid: on_concept_click(c)),
        )
        cards.append(card)

    header = ft.Row([
        ft.Text(t("recommend_next"), size=14, weight=ft.FontWeight.W_600, color=ft.Colors.GREY_800, expand=True),
        ft.Text(f"{len(items)} " + t("concepts"), size=12, color=ft.Colors.GREY_600),
    ], spacing=8)

    return ft.Column([header, *cards], spacing=0, tight=True)
