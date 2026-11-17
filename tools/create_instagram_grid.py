from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


source = Path(sys.argv[1])
output = Path(sys.argv[2])
output.mkdir(parents=True, exist_ok=True)
tile_size = 1080
labels = [
    ("FREQUENCY GYM", "O ritmo certo para sua academia"),
    ("ALUNOS", "Cadastros simples e completos"),
    ("PLANOS", "Controle de planos e vencimentos"),
    ("PAGAMENTOS", "Tudo organizado em um só lugar"),
    ("ACESSOS", "Entrada rápida e segura"),
    ("DADOS", "Relatórios para decidir melhor"),
    ("OFFLINE", "Continue trabalhando mesmo sem internet"),
    ("EM QUALQUER TELA", "Celular · tablet · desktop"),
    ("EXPERIMENTE", "7 dias para conhecer o Frequency Gym"),
]

master = Image.open(source).convert("RGB").resize((tile_size * 3, tile_size * 3), Image.Resampling.LANCZOS)
master.save(output / "frequency-grid-master.png", optimize=True)
font_candidates = [
    Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("C:/Windows/Fonts/segoeuib.ttf"),
]
regular_candidates = [Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/segoeui.ttf")]
bold_path = next(path for path in font_candidates if path.exists())
regular_path = next(path for path in regular_candidates if path.exists())
title_font = ImageFont.truetype(bold_path, 58)
subtitle_font = ImageFont.truetype(regular_path, 34)
number_font = ImageFont.truetype(bold_path, 24)

for index, (title, subtitle) in enumerate(labels):
    row, column = divmod(index, 3)
    tile = master.crop((column * tile_size, row * tile_size, (column + 1) * tile_size, (row + 1) * tile_size)).convert("RGBA")
    overlay = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    panel_top = int(tile_size * 0.74)
    draw.rectangle((0, panel_top, tile_size, tile_size), fill=(4, 30, 23, 205))
    draw.line((76, int(tile_size * 0.76), 240, int(tile_size * 0.76)), fill=(181, 255, 73, 230), width=9)
    draw.text((76, int(tile_size * 0.79)), title, font=title_font, fill=(181, 255, 73, 255))
    draw.text((76, int(tile_size * 0.87)), subtitle, font=subtitle_font, fill=(250, 249, 239, 235))
    draw.text((950, int(tile_size * 0.92)), f"{index + 1:02d}", font=number_font, fill=(250, 249, 239, 235))
    tile = Image.alpha_composite(tile, overlay).convert("RGB")
    tile.save(output / f"frequency-grid-{index + 1:02d}.png", optimize=True)

print(f"Criadas 9 peças de {tile_size} x {tile_size} em {output}")
