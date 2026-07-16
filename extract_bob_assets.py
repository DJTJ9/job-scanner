"""Einmaliges Build-Tool: schneidet Bob-der-Job-Bot-Assets aus dem ChatGPT-Moodboard.
Quelle bleibt außerhalb des Repos (/root/obsidian-vault) — Script hier nur zur
Reproduzierbarkeit dokumentiert, kein Teil des App-Runtimes."""
from pathlib import Path
from PIL import Image

SRC = Path("/root/obsidian-vault/chatgpt image 17. juli 2026, 00_10_51.png")
OUT = Path("jobscanner/web/static/img/bob")
BG = (6, 19, 29)
LO, HI = 20, 60


def keyout(tile, bg=BG, lo=LO, hi=HI):
    px = tile.load()
    for y in range(tile.height):
        for x in range(tile.width):
            r, g, b, a = px[x, y]
            d = ((r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2) ** 0.5
            if d <= lo:
                a2 = 0
            elif d >= hi:
                a2 = a
            else:
                a2 = int(a * (d - lo) / (hi - lo))
            px[x, y] = (r, g, b, a2)
    return tile


def grid(im, n, y0, y1, width=930):
    return [im.crop((round(i * width / n), y0, round((i + 1) * width / n), y1)) for i in range(n)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    im = Image.open(SRC).convert("RGBA")

    im.crop((0, 212, 928, 493)).save(OUT / "hero-landscape-full.png")
    im.crop((455, 215, 928, 335)).save(OUT / "hero-landscape-band.png")

    poses = ["winken", "daumen-hoch", "lupe", "laptop", "rakete", "herz", "frage"]
    for name, tile in zip(poses, grid(im, 7, 510, 655)):
        keyout(tile).save(OUT / f"bob-pose-{name}.png")

    emotions = ["hallo", "freude", "nachdenken", "wow", "herz", "suchen", "denken", "fehler"]
    for name, tile in zip(emotions, grid(im, 8, 672, 727)):
        keyout(tile).save(OUT / f"bob-emotion-{name}.png")

    landscape = ["berg-dunkel", "berg-sonne", "wolke-einzeln", "wolke-cluster",
                 "berg-flagge-wolke", "pfad", "busch", "felsen", "tafel"]
    for name, tile in zip(landscape, grid(im, 9, 762, 832)):
        keyout(tile).save(OUT / f"landscape-{name}.png")

    markers = ["start", "profil", "bewerbung", "erfolg", "favorit", "empfehlung", "ziel"]
    for name, tile in zip(markers, grid(im, 7, 862, 924)):
        keyout(tile).save(OUT / f"marker-{name}.png")

    print(f"{len(list(OUT.glob('*.png')))} Assets geschrieben nach {OUT}")


if __name__ == "__main__":
    main()
