// Colour wheel: 12 blades, each one tagged with its own colour.
// The converter turns every colour() scope into a separate part and picks a
// filament blend for it.
segments = 12;
height = 2;

function hsv_to_rgb(h, s, v) =
    let (i = floor(h * 6), f = h * 6 - i,
         p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s))
    i % 6 == 0 ? [v, t, p] :
    i % 6 == 1 ? [q, v, p] :
    i % 6 == 2 ? [p, v, t] :
    i % 6 == 3 ? [p, q, v] :
    i % 6 == 4 ? [t, p, v] : [v, p, q];

for (index = [0 : segments - 1]) {
    color(hsv_to_rgb(index / segments, 1, 1))
        rotate(index * 360 / segments)
            rotate_extrude(angle = 360 / segments)
                translate([50, 0])
                    square([10, height]);
}
