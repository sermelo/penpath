"""Hand-made layered SVGs in the penpath layer format (Inkscape layers, mm, stroke colour)."""
import sys
import vpype as vp


def P(*pts):
    return [complex(x, y) for x, y in pts]

def make(path, w=150, h=100):
    doc = vp.Document()
    doc.page_size = (w * 96 / 25.4, h * 96 / 25.4)
    k = 96 / 25.4
    red = vp.LineCollection()
    red.append(P((10 * k, 10 * k), (140 * k, 10 * k), (140 * k, 90 * k), (10 * k, 90 * k), (10 * k, 10 * k)))
    for i in range(12, 90, 3):
        red.append(P((12 * k, i * k), (60 * k, i * k)))
    green = vp.LineCollection()
    green.append(P((75 * k, 20 * k), (125 * k, 20 * k), (100 * k, 75 * k), (75 * k, 20 * k)))
    for i in range(0, 12):
        green.append(P((75 * k, (25 + i * 4) * k), (95 * k, (25 + i * 4) * k)))
    doc.add(red, 1)
    doc.add(green, 2)
    doc.layers[1].set_property(vp.METADATA_FIELD_NAME, "stabilo_88_red")
    doc.layers[1].set_property(vp.METADATA_FIELD_COLOR, vp.Color("#d02020"))
    doc.layers[2].set_property(vp.METADATA_FIELD_NAME, "stabilo_88_green")
    doc.layers[2].set_property(vp.METADATA_FIELD_COLOR, vp.Color("#208040"))
    with open(path, "w") as f:
        vp.write_svg(f, doc, source_string="test", show_pen_up=False)

make(sys.argv[1] if len(sys.argv) > 1 else "svg_tests/two_layers.svg")
