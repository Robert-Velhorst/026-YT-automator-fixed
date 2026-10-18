from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont


STYLES = {
    "modern": {"background": (25, 46, 42), "text": (248, 250, 247), "accent": (238, 100, 83)},
    "bright": {"background": (240, 226, 194), "text": (24, 44, 39), "accent": (36, 116, 96)},
    "bold": {"background": (29, 30, 35), "text": (255, 255, 255), "accent": (246, 196, 76)},
}


def _font(size):
    candidates = (
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _fit_lines(draw, title, max_width, max_lines=4):
    title = " ".join(str(title or "New video").split())
    for size in range(76, 35, -4):
        font = _font(size)
        approximate = max(10, int(max_width / max(1, size * 0.58)))
        lines = wrap(title, width=approximate, break_long_words=True, break_on_hyphens=True)
        if len(lines) <= max_lines and all(draw.textbbox((0, 0), line, font=font)[2] <= max_width for line in lines):
            return font, lines
    return _font(36), wrap(title, width=42, break_long_words=True)[:max_lines]


def generate_thumbnail(output_path, title=None, template_style="modern"):
    style = STYLES.get(template_style, STYLES["modern"])
    width, height = 1280, 720
    image = Image.new("RGB", (width, height), style["background"])
    draw = ImageDraw.Draw(image)

    for y in range(height):
        ratio = y / height
        shade = tuple(max(0, min(255, int(value * (1.04 - ratio * 0.18)))) for value in style["background"])
        draw.line((0, y, width, y), fill=shade)
    draw.rectangle((0, 0, 28, height), fill=style["accent"])
    draw.rectangle((width - 8, 0, width, height), fill=style["accent"])
    draw.ellipse((930, -130, 1370, 310), outline=style["accent"], width=7)

    font, lines = _fit_lines(draw, title, 1050)
    line_height = max(54, font.size + 12 if hasattr(font, "size") else 60)
    block_height = len(lines) * line_height
    y = max(90, (height - block_height) // 2)
    for line in lines:
        draw.text((88, y + 4), line, font=font, fill=(0, 0, 0), stroke_width=2)
        draw.text((84, y), line, font=font, fill=style["text"])
        y += line_height

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.jpg")
    image.save(temporary, "JPEG", quality=90, optimize=True, progressive=True)
    temporary.replace(output)
    return str(output)
