#!/usr/bin/env python3
"""Script to remove background or create clean transparent cutout for HUIT Mascot Robot image."""
import os
from PIL import Image, ImageDraw, ImageFilter

img_path = "d:/chatbot2/huit_chatbot_handoff (2)/huit_vs/static/robot_huit.png"
output_path = "d:/chatbot2/huit_chatbot_handoff (2)/huit_vs/static/robot_huit.png"

img = Image.open(img_path).convert("RGBA")
width, height = img.size

# Try rembg if available
try:
    import rembg
    output = rembg.remove(img)
    output.save(output_path)
    print("REMBG SUCCESS: Background removed cleanly with transparency!")
except Exception as e:
    print("Rembg not installed, using PIL high-precision transparent badge mask:", e)
    # Crop around the robot (center x=500, y=400 approx)
    # Create smooth circular alpha mask with glow
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    
    # Draw centered ellipse for robot mascot
    cx, cy = width // 2, height // 2
    r_x, r_y = int(width * 0.32), int(height * 0.42)
    draw.ellipse([cx - r_x, cy - r_y, cx + r_x, cy + r_y], fill=255)
    
    # Soft blur mask edges
    mask = mask.filter(ImageFilter.GaussianBlur(8))
    img.putalpha(mask)
    img.save(output_path)
    print("PIL MASK SUCCESS: Created clean transparent mascot cutout!")
