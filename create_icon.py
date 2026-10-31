"""Generate extension/icon.png — run once during build."""
from PIL import Image, ImageDraw

img = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.ellipse([2, 2, 46, 46], fill="#e94560")
d.rectangle([12, 16, 20, 24], fill="white")
d.rectangle([28, 16, 36, 24], fill="white")
d.rectangle([15, 32, 33, 37], fill="white")
img.save("extension/icon.png")
print("icon.png written")
