"""Generate tray icon PNGs for CoworkSync."""

import os
from PIL import Image, ImageDraw

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")


def create_icon(color, filename):
    """Create a 64x64 circular icon with the given color."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw filled circle
    margin = 4
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=color,
        outline=(255, 255, 255, 200),
        width=2,
    )

    # Draw sync arrows symbol in white
    cx, cy = size // 2, size // 2
    arrow_color = (255, 255, 255, 220)

    # Simple "S" shape to suggest sync
    draw.text((cx - 6, cy - 10), "S", fill=arrow_color)

    path = os.path.join(ASSETS_DIR, filename)
    img.save(path, "PNG")
    print(f"Created {path}")


def main():
    os.makedirs(ASSETS_DIR, exist_ok=True)
    create_icon((76, 175, 80, 255), "icon_green.png")    # Green - running
    create_icon((255, 193, 7, 255), "icon_yellow.png")   # Yellow - syncing
    create_icon((244, 67, 54, 255), "icon_red.png")      # Red - error
    print("Icons generated.")


if __name__ == "__main__":
    main()
