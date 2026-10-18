"""Generate every SVG under `images/` from the data files, deterministically (SPEC M17).

Usage: `python tools/make_images.py [--out DIR]` (default: the mock's `images/` folder).
Standard library only. A re-run writes byte-identical files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT = "system-ui,-apple-system,'Segoe UI',Roboto,sans-serif"
SHADOW = '<filter id="{id}" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="6" stdDeviation="7" flood-color="#0b1020" flood-opacity=".22"/></filter>'
TIERS = {"starter": ("#7aa7d9", "#4f7fc0", 2), "plus": ("#8fc9a8", "#3f9a73", 3),
         "max": ("#c7a0e0", "#8a5cc2", 4), "student": ("#f2c27b", "#d98a3d", 0)}
ADDON_COLOURS = {"shield": ("#6fb3e0", "#3a6fb5"), "case": ("#9fd1c0", "#3f8f7a"), "charger": ("#f3c77a", "#d4893a"),
                 "earbuds": ("#c9b3ec", "#7f5cc4"), "watch": ("#f0a3a3", "#c95c6e"), "router": ("#8fc9e6", "#3d86b8"),
                 "play": ("#f4a98a", "#d0603f"), "plane": ("#9ec4f0", "#4a78c9"), "battery": ("#a9dc93", "#4f9a3f")}


def rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(hex_colour: str, other: str, t: float) -> str:
    """Blend two `#rrggbb` colours; `t=0` is the first, `t=1` the second."""
    a, b = rgb(hex_colour), rgb(other)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def svg(width: int, height: int, title: str, defs: list[str], body: list[str]) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="t">'
            f'<title id="t">{esc(title)}</title><defs>{"".join(defs)}</defs>{"".join(body)}</svg>\n')


def grad(gid: str, a: str, b: str, x2: str = "1", y2: str = "1") -> str:
    return (f'<linearGradient id="{gid}" x1="0" y1="0" x2="{x2}" y2="{y2}">'
            f'<stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient>')


def phone_parts(p: str, x: float, y: float, w: float, h: float, colour: str, cutout: str, *,
                crease: str | None = None, show_time: bool = True, radius: float | None = None,
                screen: bool = True, accent: str = "#8ab4ff") -> tuple[list[str], list[str]]:
    """Defs and shapes for one phone face: body, screen wallpaper, glass sheen, time and camera cut-out.

    Returns:
        `(defs, shapes)` with ids prefixed by `p` so several phones can share one file.
    Parameters:
        p: Id prefix.
        x, y, w, h: Body box.
        colour: Body colour `#rrggbb`.
        cutout: `pill`, `punch`, `notch` or `none`.
        crease: `v` or `h` for an open foldable's hinge line.
        show_time: Draw the `9:41` lock screen.
        radius: Corner radius; defaults to 15% of the width.
        screen: Draw a screen at all (a closed flip's cover has its own).
        accent: Brand colour blended into the wallpaper.
    """
    r = radius if radius is not None else round(w * 0.15, 1)
    inset = 7
    sx, sy, sw, sh, sr = x + inset, y + inset, w - 2 * inset, h - 2 * inset, max(r - inset, 4)
    wall_a, wall_b = mix(accent, "#ffffff", 0.45), mix(mix(colour, accent, 0.6), "#ffffff", 0.2)
    defs = [grad(f"{p}b", mix(colour, "#ffffff", 0.18), mix(colour, "#000000", 0.28)),
            grad(f"{p}w", wall_a, wall_b, "0.4", "1"),
            '<linearGradient id="{0}g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" '
            'stop-opacity=".38"/><stop offset=".42" stop-color="#fff" stop-opacity="0"/></linearGradient>'.format(p),
            f'<clipPath id="{p}c"><rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="{sr}"/></clipPath>']
    shapes = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="url(#{p}b)" filter="url(#s)"/>',
              f'<rect x="{x + w - 1.5}" y="{y + h * 0.22}" width="3" height="{round(h * 0.09, 1)}" rx="1.5" '
              f'fill="{mix(colour, "#000000", 0.35)}"/>']
    if not screen:
        lens = mix(colour, "#000000", 0.55)
        shapes += [f'<rect x="{x + 12}" y="{y + 12}" width="{round(w * 0.42, 1)}" height="{round(w * 0.42, 1)}" '
                   f'rx="12" fill="{mix(colour, "#000000", 0.18)}"/>',
                   f'<circle cx="{x + 12 + w * 0.12}" cy="{y + 12 + w * 0.12}" r="{round(w * 0.07, 1)}" fill="{lens}"/>',
                   f'<circle cx="{x + 12 + w * 0.3}" cy="{y + 12 + w * 0.12}" r="{round(w * 0.07, 1)}" fill="{lens}"/>',
                   f'<circle cx="{x + 12 + w * 0.12}" cy="{y + 12 + w * 0.3}" r="{round(w * 0.07, 1)}" fill="{lens}"/>',
                   f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="url(#{p}g)"/>']
        return defs, shapes
    cx = x + w / 2
    shapes += [f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="{sr}" fill="url(#{p}w)"/>',
               f'<g clip-path="url(#{p}c)">'
               f'<circle cx="{round(sx + sw * 0.15, 1)}" cy="{round(sy + sh * 0.78, 1)}" r="{round(sw * 0.55, 1)}" '
               f'fill="{mix(colour, "#ffffff", 0.3)}" opacity=".45"/>'
               f'<circle cx="{round(sx + sw * 0.95, 1)}" cy="{round(sy + sh * 0.55, 1)}" r="{round(sw * 0.4, 1)}" '
               f'fill="#ffffff" opacity=".35"/>'
               f'<path d="M{sx} {sy}h{round(sw * 0.75, 1)}L{sx} {round(sy + sh * 0.6, 1)}z" fill="url(#{p}g)"/></g>']
    if crease == "v":
        shapes.append(f'<rect x="{cx - 0.75}" y="{sy}" width="1.5" height="{sh}" fill="#ffffff" opacity=".45"/>')
    elif crease == "h":
        shapes.append(f'<rect x="{sx}" y="{y + h / 2 - 0.75}" width="{sw}" height="1.5" fill="#ffffff" opacity=".45"/>')
    if show_time:
        size = round(min(sw * 0.26, 46), 1)
        ty = round(sy + sh * (0.2 if crease != "h" else 0.16) + size, 1)
        shapes.append(f'<text x="{cx}" y="{ty}" font-family="{FONT}" font-size="{size}" font-weight="300" '
                      f'text-anchor="middle" fill="#ffffff" fill-opacity=".95">9:41</text>')
        shapes.append(f'<text x="{cx}" y="{round(ty + size * 0.42, 1)}" font-family="{FONT}" '
                      f'font-size="{round(size * 0.27, 1)}" text-anchor="middle" fill="#ffffff" '
                      f'fill-opacity=".85">Sunday, October 18</text>')
    ink = "#0d0f14"
    if cutout == "pill":
        shapes.append(f'<rect x="{round(cx - sw * 0.17, 1)}" y="{sy + 9}" width="{round(sw * 0.34, 1)}" height="15" '
                      f'rx="7.5" fill="{ink}"/>')
    elif cutout == "punch":
        shapes.append(f'<circle cx="{cx}" cy="{sy + 15}" r="6" fill="{ink}"/>')
    elif cutout == "notch":
        shapes.append(f'<path d="M{round(cx - sw * 0.22, 1)} {sy}h{round(sw * 0.44, 1)}v4a12 12 0 0 1-12 12h'
                      f'{round(-sw * 0.44 + 24, 1)}a12 12 0 0 1-12-12z" fill="{ink}"/>')
    shapes.append(f'<rect x="{round(cx - sw * 0.18, 1)}" y="{round(sy + sh - 11, 1)}" '
                  f'width="{round(sw * 0.36, 1)}" height="4" rx="2" fill="#ffffff" fill-opacity=".8"/>')
    return defs, shapes


CUTOUTS = {"Aurora": "pill", "Lumen": "punch", "Kestrel": "punch", "Nimbus": "notch"}
ACCENTS = {"Aurora": "#f59e8b", "Lumen": "#6fcfc2", "Kestrel": "#8ab4ff", "Nimbus": "#b49cff"}


def device_svg(dev: dict, colour: dict) -> str:
    title = f"{dev['name']} in {colour['name']}"
    hexc = colour["hex"]
    cut, acc = CUTOUTS[dev["brand"]], ACCENTS[dev["brand"]]
    defs = [SHADOW.format(id="s")]
    body: list[str] = []
    if dev["form_factor"] != "foldable":
        d, s = phone_parts("a", 20, 14, 200, 448, hexc, cut, accent=acc)
        return svg(240, 480, title, defs + d, s)
    if dev.get("fold_style") == "flip":
        # Closed: a compact square with a round cover screen. Open: a tall phone with a hinge across.
        d1, s1 = phone_parts("a", 36, 150, 150, 165, hexc, "none", show_time=False, radius=30, screen=False)
        lens = mix(hexc, "#000000", 0.55)
        s1 = s1[:2] + [f'<circle cx="111" cy="215" r="44" fill="#151821"/>',
                       f'<circle cx="111" cy="215" r="38" fill="{mix(acc, "#ffffff", 0.3)}"/>',
                       f'<text x="111" y="224" font-family="{FONT}" font-size="24" font-weight="300" '
                       f'text-anchor="middle" fill="#ffffff">9:41</text>',
                       f'<circle cx="67" cy="280" r="8" fill="{lens}"/><circle cx="90" cy="280" r="8" fill="{lens}"/>',
                       s1[-1]]
        d2, s2 = phone_parts("b", 236, 70, 190, 360, hexc, cut, crease="h", radius=30, accent=acc)
        return svg(480, 480, title + ", closed and open", defs + d1 + d2, body + s1 + s2)
    # Book foldable: closed (cover screen, narrow) and open (wide inner screen with a vertical crease).
    d1, s1 = phone_parts("a", 30, 80, 150, 320, hexc, cut, radius=24, accent=acc)
    d2, s2 = phone_parts("b", 206, 80, 250, 320, hexc, cut, crease="v", radius=24, accent=acc)
    return svg(480, 480, title + ", closed and open", defs + d1 + d2, body + s1 + s2)


def bars(x: float, y: float, filled: int) -> str:
    out = []
    for i in range(4):
        h = 10 + i * 8
        op = "1" if i < filled else ".35"
        out.append(f'<rect x="{x + i * 12}" y="{y - h}" width="8" height="{h}" rx="2" fill="#ffffff" opacity="{op}"/>')
    return "".join(out)


def plan_svg(plan: dict) -> str:
    a, b, level = TIERS[plan["id"]]
    defs = [SHADOW.format(id="s"), grad("band", a, b, "1", "0"),
            '<clipPath id="tile"><rect x="16" y="14" width="368" height="204" rx="22"/></clipPath>']
    if level:
        icon = bars(318, 70, level)
    else:
        icon = ('<path d="M346 38l30 13-30 13-30-13z" fill="#ffffff"/>'
                '<path d="M328 56v11c0 5 8 9 18 9s18-4 18-9v-11l-18 8z" fill="#ffffff" opacity=".85"/>')
    data = "Unlimited premium data" if plan["premium_data_gb"] is None else f"{plan['premium_data_gb']} GB premium data"
    body = [
        '<rect x="16" y="14" width="368" height="204" rx="22" fill="#ffffff" filter="url(#s)"/>',
        '<g clip-path="url(#tile)"><rect x="16" y="14" width="368" height="80" fill="url(#band)"/>'
        f'<circle cx="80" cy="14" r="70" fill="#ffffff" opacity=".12"/></g>',
        icon,
        f'<text x="40" y="70" font-family="{FONT}" font-size="34" font-weight="600" fill="#ffffff">{esc(plan["name"])}</text>',
        f'<text x="40" y="132" font-family="{FONT}" font-size="17" fill="#1d2433">{esc(data)}</text>',
        f'<text x="40" y="160" font-family="{FONT}" font-size="17" fill="#1d2433">{plan["hotspot_gb"]} GB hotspot</text>',
        f'<text x="40" y="196" font-family="{FONT}" font-size="14" fill="#5b6475">{esc(plan["tagline"])}</text>',
    ]
    return svg(400, 240, f"{plan['name']} plan", defs, body)


ICONS = {
    "shield": '<path d="M120 62l44 16v32c0 30-19 54-44 66-25-12-44-36-44-66v-32z" fill="#fff"/>'
              '<path d="M102 118l13 13 25-27" fill="none" stroke="{c}" stroke-width="9" stroke-linecap="round" '
              'stroke-linejoin="round"/>',
    "case": '<rect x="86" y="54" width="68" height="132" rx="18" fill="none" stroke="#fff" stroke-width="10"/>'
            '<circle cx="108" cy="78" r="7" fill="#fff"/>',
    "charger": '<rect x="88" y="66" width="64" height="74" rx="14" fill="#fff"/>'
               '<rect x="104" y="46" width="8" height="24" rx="3" fill="#fff"/><rect x="128" y="46" width="8" '
               'height="24" rx="3" fill="#fff"/><path d="M120 140v26c0 12 12 18 26 18" fill="none" stroke="#fff" '
               'stroke-width="8" stroke-linecap="round"/><path d="M124 84l-14 22h12l-6 20 16-25h-12z" fill="{c}"/>',
    "earbuds": '<circle cx="94" cy="100" r="24" fill="#fff"/><rect x="86" y="108" width="16" height="66" rx="8" '
               'fill="#fff"/><circle cx="146" cy="100" r="24" fill="#fff"/><rect x="138" y="108" width="16" '
               'height="66" rx="8" fill="#fff"/>',
    "watch": '<rect x="98" y="44" width="44" height="152" rx="14" fill="#fff" opacity=".55"/>'
             '<rect x="82" y="78" width="76" height="84" rx="22" fill="#fff"/><path d="M120 98v22l14 10" '
             'fill="none" stroke="{c}" stroke-width="7" stroke-linecap="round"/>',
    "router": '<rect x="64" y="124" width="112" height="48" rx="14" fill="#fff"/><circle cx="90" cy="148" r="6" '
              'fill="{c}"/><circle cx="110" cy="148" r="6" fill="{c}"/><path d="M92 106a40 40 0 0 1 56 0M78 '
              '90a60 60 0 0 1 84 0" fill="none" stroke="#fff" stroke-width="9" stroke-linecap="round"/>',
    "play": '<rect x="62" y="66" width="116" height="100" rx="20" fill="#fff"/><path d="M108 94v44l36-22z" '
            'fill="{c}"/><rect x="90" y="176" width="60" height="8" rx="4" fill="#fff"/>',
    "plane": '<path d="M120 52c7 0 11 8 11 18v30l48 28v14l-48-14v30l14 11v11l-25-7-25 7v-11l14-11v-30l-48 14'
             'v-14l48-28v-30c0-10 4-18 11-18z" fill="#fff"/>',
    "battery": '<rect x="70" y="84" width="92" height="72" rx="14" fill="none" stroke="#fff" stroke-width="10"/>'
               '<rect x="166" y="106" width="10" height="28" rx="4" fill="#fff"/><rect x="84" y="98" width="46" '
               'height="44" rx="6" fill="#fff"/>',
}


def addon_svg(addon: dict) -> str:
    a, b = ADDON_COLOURS[addon["icon"]]
    if addon["id"] == "bundle-sound":
        a, b = "#b3c7f2", "#5a6fc9"
    defs = [SHADOW.format(id="s"), grad("bg", a, b)]
    body = ['<rect x="20" y="16" width="200" height="200" rx="40" fill="url(#bg)" filter="url(#s)"/>',
            '<path d="M20 70a40 40 0 0 1 40-54h120a40 40 0 0 1 12 2L28 172a40 40 0 0 1-8-12z" fill="#fff" '
            'opacity=".12"/>',
            ICONS[addon["icon"]].replace("{c}", b)]
    return svg(240, 240, f"{addon['name']} icon", defs, body)


PEOPLE = [("#f6b39b", "#e07a5f"), ("#a8c8f0", "#5b7fc9"), ("#b6dcb0", "#5f9e66"), ("#d6b8f0", "#9068c6"),
          ("#f3d38c", "#d29b37"), ("#9fd6d6", "#3f9393")]


def person_svg(line: dict, index: int) -> str:
    a, b = PEOPLE[index % len(PEOPLE)]
    name = line["person"]["first_name"]
    defs = [grad("bg", a, b)]
    body = ['<circle cx="48" cy="48" r="46" fill="url(#bg)"/>',
            '<path d="M14 30a46 46 0 0 1 60-22" fill="none" stroke="#fff" stroke-width="3" opacity=".3"/>',
            f'<text x="48" y="60" font-family="{FONT}" font-size="34" font-weight="600" text-anchor="middle" '
            f'fill="#ffffff">{esc(name[:2] if len(name) > 1 else name)}</text>']
    return svg(96, 96, f"{name}, avatar", defs, body)


def build(out: Path) -> list[Path]:
    """Write every image into `out`, mirroring the paths used in `data/*.json`.

    Behavior:
        Devices: one 240x480 front view per colour (480x480 open and closed for foldables).
        Plans: 400x240 tiles. Add-ons: 240x240 icons. People: 96x96 initials. Files are written
        as UTF-8 with `\\n` line endings, in sorted order, with no timestamps.
    Returns:
        The written paths.
    Parameters:
        out: Destination folder (the `images/` level).
    """
    data = ROOT / "data"
    devices = json.loads((data / "devices.json").read_text(encoding="utf-8"))["devices"]
    plans = json.loads((data / "plans.json").read_text(encoding="utf-8"))["plans"]
    addons = json.loads((data / "addons.json").read_text(encoding="utf-8"))["addons"]
    customers = json.loads((data / "customers.json").read_text(encoding="utf-8"))["customers"]
    files: dict[str, str] = {}
    for dev in devices:
        for colour in dev["colours"]:
            files[colour["image"]] = device_svg(dev, colour)
    for plan in plans:
        files[plan["image"]] = plan_svg(plan)
    for addon in addons:
        files[addon["image"]] = addon_svg(addon)
    for customer in customers:
        for i, line in enumerate(customer["lines"]):
            files[line["person"]["avatar"]] = person_svg(line, i)
    written = []
    for rel in sorted(files):
        path = out / Path(rel).relative_to("images")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(files[rel].encode("utf-8"))
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "images", help="Output folder (default: images/).")
    args = parser.parse_args(argv)
    written = build(args.out)
    print(f"wrote {len(written)} images to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
