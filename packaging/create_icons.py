"""Render the repository's simple vector card mark at desktop icon sizes."""

from pathlib import Path

from PIL import Image, ImageDraw


def render_icon(size: int) -> Image.Image:
    scale = 4
    image = Image.new("RGBA", (512 * scale, 512 * scale))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((32, 32, 2016, 2016), radius=448, fill="#8463e9")
    for bounds, angle, color in (
        ((105, 111, 374, 403), 11, "#b4a1ef"),
        ((132, 102, 401, 394), -7, "#e6dffc"),
    ):
        layer = Image.new("RGBA", image.size)
        ImageDraw.Draw(layer).rounded_rectangle(
            tuple(value * scale for value in bounds), radius=30 * scale, fill=color
        )
        image.alpha_composite(layer.rotate(angle, resample=Image.Resampling.BICUBIC))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((500, 464, 1548, 1616), radius=112, fill="#fffaf0")
    for y, end in ((201, 302), (246, 270), (291, 302)):
        draw.line((740, y * scale, end * scale, y * scale), fill="#8463e9", width=76)
        for x in (185, end):
            draw.ellipse(
                ((x - 9.5) * scale, (y - 9.5) * scale, (x + 9.5) * scale, (y + 9.5) * scale),
                fill="#8463e9",
            )
    draw.ellipse((1160, 1180, 1648, 1668), fill="#e7ad57")
    draw.line((1296, 1424, 1372, 1500, 1512, 1340), fill="#352261", width=68, joint="curve")
    for x, y in ((324, 356), (343, 375), (378, 335)):
        draw.ellipse(
            ((x - 8.5) * scale, (y - 8.5) * scale, (x + 8.5) * scale, (y + 8.5) * scale),
            fill="#352261",
        )
    return image.resize((size, size), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    destination = Path(__file__).resolve().parents[1] / "desktop/build"
    (destination / "icons").mkdir(parents=True, exist_ok=True)
    for dimension in (16, 24, 32, 48, 64, 128, 256, 512):
        render_icon(dimension).save(destination / "icons" / f"{dimension}x{dimension}.png")
    render_icon(512).save(destination / "icon.png")
