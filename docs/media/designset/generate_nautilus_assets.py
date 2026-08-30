"""Generate the reusable NemoFold Nautilus lockup and platform thumbnails."""

# The SVG template and drawing coordinates remain intentionally explicit.
# ruff: noqa: E501

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent
SOURCE_DIR = BASE_DIR / "sources"
BRAND_DIR = BASE_DIR / "brand"

YOUTUBE_SIZE = (1280, 720)
DEVPOST_SIZE = (1200, 900)

DEEP_TEAL = "#073B49"
MID_TEAL = "#0B4A59"
IVORY = "#F7F1E7"
CORAL = "#FF6B4A"
CYAN = "#5AD2D0"
EMERALD = "#1F9D72"

SANS_BOLD = (
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "DejaVuSans-Bold.ttf",
)
SANS_REGULAR = (
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "DejaVuSans.ttf",
)
SERIF_BOLD = (
    "C:/Windows/Fonts/georgiab.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/Library/Fonts/Georgia Bold.ttf",
    "DejaVuSerif-Bold.ttf",
)

FOLD_MARK_POLYGONS = (
    ((6, 8), (30, 0), (52, 18), (27, 30)),
    ((27, 30), (52, 18), (46, 49), (20, 56)),
    ((6, 8), (27, 30), (20, 56), (0, 31)),
)
FOLD_MARK_COLORS = (CORAL, CYAN, EMERALD)
FOLD_RING_PADDING = 7
FOLD_ARC_PADDING = 13
FOLD_ARC_START = 210
FOLD_ARC_END = 354


@dataclass(frozen=True)
class Concept:
    identifier: str
    source: str
    headline: tuple[str, str]
    brand_hook: str
    accent_line: int
    alt: str


CONCEPTS = (
    Concept(
        identifier="nautilus-descent",
        source="nautilus-descent-master.png",
        headline=("DIVE INTO", "YOUR DOCUMENTS"),
        brand_hook="Dive into your documents.",
        accent_line=1,
        alt=(
            "The Nautilus descends into a teal archive trench while Captain Nemo stands "
            "inside its illuminated observation window."
        ),
    ),
    Concept(
        identifier="captain-nemo-observatory",
        source="captain-nemo-observatory-master.png",
        headline=("YOUR FILES.", "YOUR RULES."),
        brand_hook="Your files. Your rules.",
        accent_line=1,
        alt=(
            "Captain Nemo watches the Nautilus dive past ordered document layers through "
            "a circular observation window."
        ),
    ),
    Concept(
        identifier="fold-depth",
        source="fold-depth-master.png",
        headline=("DIVE DEEP.", "STAY LOCAL."),
        brand_hook="Dive deep. Stay local.",
        accent_line=1,
        alt=(
            "The Nautilus crosses a luminous document fold inside a protected teal trust "
            "boundary, with a narrow evidence path returning locally."
        ),
    ),
)


def font(candidates: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    errors = []
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")
    tried = "\n  - ".join(errors)
    raise FileNotFoundError(f"No compatible font found. Tried:\n  - {tried}")


def cover_crop(source: Image.Image, size: tuple[int, int], focus_x: float = 0.55) -> Image.Image:
    target_w, target_h = size
    source_ratio = source.width / source.height
    target_ratio = target_w / target_h

    if source_ratio > target_ratio:
        crop_w = round(source.height * target_ratio)
        max_x = source.width - crop_w
        left = round(max_x * focus_x)
        box = (left, 0, left + crop_w, source.height)
    else:
        crop_h = round(source.width / target_ratio)
        max_y = source.height - crop_h
        top = round(max_y * 0.5)
        box = (0, top, source.width, top + crop_h)

    return source.crop(box).resize(size, Image.Resampling.LANCZOS).convert("RGBA")


def add_readability_layers(image: Image.Image) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    pixels = overlay.load()
    for x in range(width):
        progress = x / max(width - 1, 1)
        alpha = round(205 * max(0.0, 1.0 - progress / 0.63) ** 1.55)
        for y in range(height):
            edge = min(y / max(height * 0.16, 1), (height - 1 - y) / max(height * 0.18, 1), 1)
            vignette = round(48 * max(0.0, 1.0 - edge))
            pixels[x, y] = (1, 10, 14, min(235, alpha + vignette))
    image.alpha_composite(overlay)


def draw_fold_mark(draw: ImageDraw.ImageDraw, x: int, y: int, size: int) -> None:
    scale = size / 56

    def point(px: int, py: int) -> tuple[int, int]:
        return round(x + px * scale), round(y + py * scale)
    draw.ellipse(
        (
            x - round(FOLD_RING_PADDING * scale),
            y - round(FOLD_RING_PADDING * scale),
            x + size + round(FOLD_RING_PADDING * scale),
            y + size + round(FOLD_RING_PADDING * scale),
        ),
        outline=CYAN,
        width=max(2, round(2.2 * scale)),
    )
    draw.arc(
        (
            x - round(FOLD_ARC_PADDING * scale),
            y - round(FOLD_ARC_PADDING * scale),
            x + size + round(FOLD_ARC_PADDING * scale),
            y + size + round(FOLD_ARC_PADDING * scale),
        ),
        start=FOLD_ARC_START,
        end=FOLD_ARC_END,
        fill=CORAL,
        width=max(2, round(3 * scale)),
    )
    for polygon, color in zip(FOLD_MARK_POLYGONS, FOLD_MARK_COLORS, strict=True):
        draw.polygon([point(px, py) for px, py in polygon], fill=color)


def draw_wordmark(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    *,
    scale: float,
    light_surface: bool = False,
) -> tuple[int, int]:
    icon_size = round(56 * scale)
    draw_fold_mark(draw, x, y, icon_size)
    product_font = font(SANS_BOLD, round(50 * scale))
    text_x = x + round(82 * scale)
    text_y = y - round(4 * scale)
    nemo_color = DEEP_TEAL if light_surface else IVORY
    fold_color = MID_TEAL if light_surface else CYAN
    draw.text((text_x, text_y), "Nemo", font=product_font, fill=nemo_color)
    nemo_width = round(draw.textlength("Nemo", font=product_font))
    draw.text((text_x + nemo_width, text_y), "Fold", font=product_font, fill=fold_color)
    total_width = text_x + nemo_width + round(draw.textlength("Fold", font=product_font)) - x
    return total_width, max(icon_size, round(60 * scale))


def draw_accent_bar(image: Image.Image) -> None:
    width, _ = image.size
    bar = Image.new("RGBA", (width, 5), (0, 0, 0, 0))
    pixels = bar.load()
    stops = (
        (0.0, (90, 210, 208)),
        (0.55, (31, 157, 114)),
        (1.0, (255, 107, 74)),
    )
    for x in range(width):
        p = x / max(width - 1, 1)
        left, right = stops[0], stops[-1]
        for index in range(len(stops) - 1):
            if stops[index][0] <= p <= stops[index + 1][0]:
                left, right = stops[index], stops[index + 1]
                break
        span = max(right[0] - left[0], 0.0001)
        mix = (p - left[0]) / span
        color = tuple(round(left[1][c] + (right[1][c] - left[1][c]) * mix) for c in range(3))
        pixels[x, 0] = (*color, 255)
        for y in range(1, 5):
            pixels[x, y] = (*color, 255)
    image.alpha_composite(bar, (0, 0))


def draw_eyebrow(draw: ImageDraw.ImageDraw, left: int, top: int, scale: float) -> None:
    eyebrow_font = font(SANS_BOLD, max(15, round(16 * scale)))
    eyebrow = "PRIVATE · PERSISTENT · EVIDENCE-FIRST"
    eyebrow_text_x = round(30 * scale)
    eyebrow_text_box = draw.textbbox((0, 0), eyebrow, font=eyebrow_font)
    eyebrow_text_w = eyebrow_text_box[2] - eyebrow_text_box[0]
    eyebrow_w = eyebrow_text_x + eyebrow_text_w + round(16 * scale)
    eyebrow_h = round(34 * scale)
    draw.rounded_rectangle(
        (left, top, left + eyebrow_w, top + eyebrow_h),
        radius=round(17 * scale),
        fill=(7, 59, 73, 220),
        outline=CYAN,
        width=max(1, round(1.5 * scale)),
    )
    draw.ellipse(
        (left + round(13 * scale), top + round(13 * scale), left + round(21 * scale), top + round(21 * scale)),
        fill=CYAN,
    )
    draw.text((left + eyebrow_text_x, top + round(8 * scale)), eyebrow, font=eyebrow_font, fill=CYAN)


def draw_scope_chip(draw: ImageDraw.ImageDraw, left: int, height: int, scale: float) -> None:
    chip_y = height - round(86 * scale)
    chip_text = "LOCAL AUTHORITY · BOUNDED REASONING"
    chip_font = font(SANS_BOLD, max(16, round(18 * scale)))
    chip_text_box = draw.textbbox((0, 0), chip_text, font=chip_font)
    chip_text_w = chip_text_box[2] - chip_text_box[0]
    chip_text_x = round(38 * scale)
    chip_w = chip_text_x + chip_text_w + round(18 * scale)
    draw.rounded_rectangle(
        (left, chip_y, left + chip_w, chip_y + round(42 * scale)),
        radius=round(21 * scale),
        fill=(4, 30, 38, 220),
        outline=EMERALD,
        width=max(2, round(2 * scale)),
    )
    draw.ellipse(
        (left + round(16 * scale), chip_y + round(15 * scale), left + round(28 * scale), chip_y + round(27 * scale)),
        fill=EMERALD,
    )
    draw.text(
        (left + chip_text_x, chip_y + round(10 * scale)),
        chip_text,
        font=chip_font,
        fill=IVORY,
    )


def draw_campaign_copy(image: Image.Image, concept: Concept, platform: str) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    scale = width / 1280
    left = round(64 * scale)
    top = round(62 * scale)

    draw_eyebrow(draw, left, top, scale)
    draw_wordmark(draw, left, top + round(50 * scale), scale=0.88 * scale)

    headline_size = round((82 if platform == "youtube" else 72) * scale)
    headline_font = font(SERIF_BOLD, headline_size)
    line_gap = round(headline_size * 0.94)
    headline_y = top + round(190 * scale)
    for index, line in enumerate(concept.headline):
        color = CORAL if index == concept.accent_line else IVORY
        draw.text(
            (left, headline_y + index * line_gap),
            line,
            font=headline_font,
            fill=color,
            stroke_width=max(1, round(1.5 * scale)),
            stroke_fill=(2, 17, 23, 180),
        )

    support_y = headline_y + 2 * line_gap + round(38 * scale)
    support_font = font(SANS_REGULAR, max(20, round(23 * scale)))
    draw.text(
        (left, support_y),
        "Local memory. Bounded reasoning. Verifiable results.",
        font=support_font,
        fill="#C8E3E1",
    )

    draw_scope_chip(draw, left, height, scale)
    image.alpha_composite(overlay)


def draw_brand_title_copy(image: Image.Image, concept: Concept) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    scale = width / 1280
    left = round(64 * scale)
    top = round(62 * scale)

    draw_eyebrow(draw, left, top, scale)
    title_y = top + round(190 * scale)
    draw_wordmark(draw, left, title_y, scale=1.8 * scale)

    hook_font = font(SERIF_BOLD, max(30, round(38 * scale)))
    hook_y = title_y + round(135 * scale)
    draw.text(
        (left, hook_y),
        concept.brand_hook,
        font=hook_font,
        fill=IVORY,
        stroke_width=max(1, round(1.2 * scale)),
        stroke_fill=(2, 17, 23, 180),
    )
    rule_y = hook_y + round(60 * scale)
    draw.rounded_rectangle(
        (left, rule_y, left + round(118 * scale), rule_y + max(3, round(4 * scale))),
        radius=max(1, round(2 * scale)),
        fill=CORAL,
    )

    draw_scope_chip(draw, left, height, scale)
    image.alpha_composite(overlay)


def render_thumbnail(concept: Concept, platform: str, size: tuple[int, int], layout: str) -> Path:
    source_path = SOURCE_DIR / concept.source
    with Image.open(source_path) as raw:
        image = cover_crop(raw.convert("RGB"), size)
    add_readability_layers(image)
    draw_accent_bar(image)
    if layout == "campaign":
        draw_campaign_copy(image, concept, platform)
        output_name = f"{concept.identifier}-{platform}.png"
    elif layout == "brand":
        draw_brand_title_copy(image, concept)
        output_name = f"{concept.identifier}-brand-{platform}.png"
    else:
        raise ValueError(f"Unknown layout: {layout}")
    output_path = BASE_DIR / output_name
    image.convert("RGB").save(output_path, optimize=True)
    return output_path


def fold_mark_svg(x: int, y: int, size: int) -> str:
    """Return the vector mark from the same normalized geometry used by Pillow."""
    scale = size / 56
    polygons = []
    for polygon, color in zip(FOLD_MARK_POLYGONS, FOLD_MARK_COLORS, strict=True):
        points = " ".join(f"{px},{py}" for px, py in polygon)
        polygons.append(f'    <polygon points="{points}" fill="{color}"/>')

    center = 28
    ring_radius = center + FOLD_RING_PADDING
    arc_radius = center + FOLD_ARC_PADDING
    start_radians = math.radians(FOLD_ARC_START)
    end_radians = math.radians(FOLD_ARC_END)
    arc_start = (
        center + arc_radius * math.cos(start_radians),
        center + arc_radius * math.sin(start_radians),
    )
    arc_end = (
        center + arc_radius * math.cos(end_radians),
        center + arc_radius * math.sin(end_radians),
    )
    polygon_markup = "\n".join(polygons)
    return f'''  <g transform="translate({x} {y}) scale({scale:.9f})">
    <circle cx="{center}" cy="{center}" r="{ring_radius}" fill="none" stroke="{CYAN}" stroke-width="2.2"/>
    <path d="M{arc_start[0]:.3f} {arc_start[1]:.3f} A{arc_radius} {arc_radius} 0 0 1 {arc_end[0]:.3f} {arc_end[1]:.3f}" fill="none" stroke="{CORAL}" stroke-width="3" stroke-linecap="round"/>
{polygon_markup}
  </g>'''


def lockup_svg(light_surface: bool) -> str:
    nemo = DEEP_TEAL if light_surface else IVORY
    fold = MID_TEAL if light_surface else CYAN
    label = "light-surface" if light_surface else "dark-surface"
    mark = fold_mark_svg(70, 74, 250)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 400" width="1600" height="400" role="img" aria-label="NemoFold logo lockup for {label}">
{mark}
  <text x="380" y="222" font-family="Segoe UI, DejaVu Sans, Arial, sans-serif" font-size="190" font-weight="800" fill="{nemo}">Nemo<tspan fill="{fold}">Fold</tspan></text>
  <text x="392" y="304" font-family="Segoe UI, DejaVu Sans, Arial, sans-serif" font-size="34" font-weight="700" letter-spacing="7" fill="{CYAN}">PRIVATE · PERSISTENT · EVIDENCE-FIRST</text>
</svg>
'''


def render_lockup_png(light_surface: bool) -> Path:
    canvas = Image.new("RGBA", (1600, 400), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw_fold_mark(draw, 70, 74, 250)
    word_font = font(SANS_BOLD, 190)
    label_font = font(SANS_BOLD, 34)
    nemo = DEEP_TEAL if light_surface else IVORY
    fold = MID_TEAL if light_surface else CYAN
    draw.text((380, 76), "Nemo", font=word_font, fill=nemo)
    nemo_width = round(draw.textlength("Nemo", font=word_font))
    draw.text((380 + nemo_width, 76), "Fold", font=word_font, fill=fold)
    draw.text(
        (392, 282),
        "PRIVATE · PERSISTENT · EVIDENCE-FIRST",
        font=label_font,
        fill=CYAN,
    )
    suffix = "light-surface" if light_surface else "dark-surface"
    output = BRAND_DIR / f"nemofold-nautilus-lockup-{suffix}.png"
    canvas.save(output, optimize=True)
    return output


def generate_lockups() -> list[dict[str, object]]:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for light_surface in (False, True):
        suffix = "light-surface" if light_surface else "dark-surface"
        svg_path = BRAND_DIR / f"nemofold-nautilus-lockup-{suffix}.svg"
        svg_path.write_text(lockup_svg(light_surface), encoding="utf-8")
        png_path = render_lockup_png(light_surface)
        with Image.open(png_path) as image:
            actual = image.size
            mode = image.mode
            alpha_extrema = image.getchannel("A").getextrema() if mode == "RGBA" else None
        if actual != (1600, 400) or mode != "RGBA" or alpha_extrema is None or alpha_extrema[0] == 255:
            raise RuntimeError(
                f"Unexpected lockup properties for {png_path}: {actual} {mode} alpha={alpha_extrema}"
            )
        entries.append(
            {
                "surface": suffix,
                "svg": str(svg_path.relative_to(BASE_DIR)).replace("\\", "/"),
                "png": str(png_path.relative_to(BASE_DIR)).replace("\\", "/"),
                "dimensions": f"{actual[0]}x{actual[1]}",
                "png_mode": mode,
            }
        )
    return entries


def main() -> None:
    deliverables = []
    for concept in CONCEPTS:
        outputs = []
        for layout in ("campaign", "brand"):
            for platform, size in (("youtube", YOUTUBE_SIZE), ("devpost", DEVPOST_SIZE)):
                output = render_thumbnail(concept, platform, size, layout)
                with Image.open(output) as image:
                    actual = image.size
                    mode = image.mode
                if actual != size or mode != "RGB":
                    raise RuntimeError(f"Unexpected output properties for {output}: {actual} {mode}")
                outputs.append(
                    {
                        "layout": layout,
                        "platform": platform,
                        "file": output.name,
                        "dimensions": f"{actual[0]}x{actual[1]}",
                        "mode": mode,
                    }
                )
                print(f"Generated {output.name}: {actual[0]}x{actual[1]} ({mode})")
        deliverables.append(
            {
                "id": concept.identifier,
                "source": f"sources/{concept.source}",
                "headline": list(concept.headline),
                "brand_hook": concept.brand_hook,
                "alt": concept.alt,
                "outputs": outputs,
            }
        )

    manifest = {
        "title": "NemoFold Nautilus Brand Extensions",
        "wordmark": "NemoFold",
        "tagline": "Your files. Your rules. Your agent.",
        "generation": {
            "master_art": "OpenAI built-in imagegen",
            "composition": "Fixed-layout Pillow overlays; byte-reproducible on the same pinned host stack",
            "prompt_file": "nautilus-prompts.md",
            "safe_claims": True,
        },
        "lockups": generate_lockups(),
        "concepts": deliverables,
    }
    manifest_path = BASE_DIR / "nautilus-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
