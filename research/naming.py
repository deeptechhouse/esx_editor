# Camelot wheel <-> classical key (a bijection)
CAMELOT = {
    "1A": ("Abm", "G#m"),
    "1B": ("B", "B"),
    "2A": ("Ebm", "D#m"),
    "2B": ("F#", "F#"),
    "3A": ("Bbm", "A#m"),
    "3B": ("Db", "C#"),
    "4A": ("Fm", "Fm"),
    "4B": ("Ab", "G#"),
    "5A": ("Cm", "Cm"),
    "5B": ("Eb", "D#"),
    "6A": ("Gm", "Gm"),
    "6B": ("Bb", "A#"),
    "7A": ("Dm", "Dm"),
    "7B": ("F", "F"),
    "8A": ("Am", "Am"),
    "8B": ("C", "C"),
    "9A": ("Em", "Em"),
    "9B": ("G", "G"),
    "10A": ("Bm", "Bm"),
    "10B": ("D", "D"),
    "11A": ("F#m", "F#m"),
    "11B": ("A", "A"),
    "12A": ("C#m", "C#m"),
    "12B": ("E", "E"),
}


def classical(cam, style):
    flat, _ = CAMELOT[cam]
    minor = cam.endswith("A")
    root = flat[:-1] if minor else flat
    if style == "long":
        return root + ("min" if minor else "maj")
    if style == "short":
        return root + ("m" if minor else "")
    raise ValueError


def build(name, cam, style, limit=8):
    letter = cam[-1].lower()
    num = cam[:-1].zfill(2)
    prefix = letter + num  # "a08"  (a/b in front, zero-padded)
    key = classical(cam, style)
    head = prefix + key
    room = limit - len(head)
    tail = name[-room:].upper() if room > 0 else ""
    return head + tail, room


NAME = "kickdrum"
for style in ("long", "short"):
    print(f"\n=== classical style: {style}  (name='{NAME}') ===")
    print(f"{'Camelot':>8} {'result':>10} {'name chars kept':>16}")
    for cam in ["8B", "8A", "12A", "11A", "10B", "3B"]:
        out, room = build(NAME, cam, style)
        flag = (
            ""
            if room >= 2
            else ("  <-- NOTHING LEFT" if room <= 0 else "  <-- 1 char only")
        )
        print(f"{cam:>8} {out:>10} {max(room,0):>16}{flag}")
print(
    "\n=== Camelot only (classical dropped; the two encode identical information) ==="
)
for cam in ["8B", "8A", "12A", "11A"]:
    letter = cam[-1].lower()
    num = cam[:-1].zfill(2)
    head = letter + num
    print(f"{cam:>8} {head+NAME[-(8-len(head)):].upper():>10} {8-len(head):>16}")
