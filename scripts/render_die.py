"""Render the hardened Proteus-1 layout to PNG with KLayout.

Run inside WSL (KLayout is installed there):

    klayout -z -r scripts/render_die.py \
        -rd input=<in.gds> -rd output=<out.png> [-rd width=2400]

The stream-out carries layer numbers only, so the IHP SG13G2 stack is rebuilt
here by number. Only the four metal levels are drawn. At die scale the
transistor, contact and via layers are sub-pixel noise: 2.4 million contact
squares alias into a grey wash that hides the routing, so they are hidden and
the image reads as what it is, a standard-cell core with its power grid.
Colour follows height, light at Metal1 to dark at Metal4, so the upper routing
and the grid stand out from the cell texture underneath.
"""
import sys
import pya


def props():
    """((layer, datatype), fill hex). Order in the list is draw order."""
    return [
        # metal stack only, light to dark with height; order is draw order
        ((8, 0), "DFDDD6"),     # Metal1: cell interconnect, the texture
        ((10, 0), "B9C3CB"),    # Metal2
        ((30, 0), "87979F"),    # Metal3
        ((50, 0), "4A5C6B"),    # Metal4: power grid and long routes
    ]


def main():
    # KLayout injects -rd values as globals; fall back to argv for a plain run.
    g = globals()
    if "input" in g:
        src, out = g["input"], g["output"]
        width = int(g["width"]) if "width" in g else 2400
    else:
        argv = sys.argv[1:]
        src, out = argv[0], argv[1]
        width = int(argv[2]) if len(argv) > 2 else 2400

    lv = pya.LayoutView()
    lv.load_layout(src, 0)
    lv.max_hier()

    # LayerProperties wants 0xRRGGBB integers, not hex strings.
    plan = {k: int(v, 16) for k, v in props()}
    li = lv.begin_layers()
    while not li.at_end():
        p = li.current()
        key = (p.source_layer, p.source_datatype)
        p.visible = key in plan
        if p.visible:
            p.fill_color = plan[key]
            p.frame_color = plan[key]
            p.dither_pattern = 0
            p.width = 0
        li.next()
    lv.end_layers()

    lv.set_config("background-color", "#FBFAF7")
    lv.set_config("grid-visible", "false")
    lv.set_config("text-visible", "false")
    lv.zoom_fit()

    bbox = lv.active_cellview().layout().top_cell().bbox()
    aspect = bbox.height() / bbox.width() if bbox.width() else 0.55
    height = max(1, int(round(width * aspect)))
    lv.save_image(out, width, height)
    print(f"wrote {out} {width}x{height} from {bbox}")


main()
