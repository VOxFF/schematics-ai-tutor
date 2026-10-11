// Inventory and wire-palette icons, drawn as SVG with the same style file and color code as
// the grid, so a part looks the same in the inventory and on the board.
import { BAND_COLORS, resistorBands } from "./colorCode.js";
import { WIRE_SHAPES } from "./placement.js";
import { CELL, STYLE } from "./style.js";

const { pin, outline, resistor, battery, meter, wire } = STYLE;

// A part drawn horizontally, pins at x = ±CELL, centered on (0, 0).
export function PartIcon({ item }) {
  const lead = (from, to) => (
    <line x1={from} y1={0} x2={to} y2={0} stroke={pin.color} strokeWidth={pin.lead_thickness} />
  );
  let body;
  if (item.type === "resistor") {
    const half = resistor.length / 2;
    const step = resistor.length / 6;
    body = (
      <>
        {lead(-CELL, -half)}
        {lead(half, CELL)}
        <rect x={-half} y={-resistor.height / 2} width={resistor.length} height={resistor.height}
              fill={resistor.fill} stroke={outline.color} strokeWidth={outline.thickness} />
        {(resistorBands(item.value) ?? []).map((band, i) => (
          <rect key={i} x={-half + step * (i + 1) + (i === 3 ? step * 0.6 : 0) - resistor.band_width / 2}
                y={-resistor.height / 2 + outline.thickness / 2} width={resistor.band_width}
                height={resistor.height - outline.thickness} fill={BAND_COLORS[band]} />
        ))}
      </>
    );
  } else if (item.type === "voltage_source") {
    const half = battery.gap / 2;
    body = (
      <>
        {lead(-CELL, -half)}
        {lead(half, CELL)}
        {/* Drawn as dropped (orientation E): positive plate toward the right-hand pin. */}
        <rect x={half - battery.long_plate_thickness / 2} y={-battery.long_plate / 2}
              width={battery.long_plate_thickness} height={battery.long_plate} fill={battery.positive_color} />
        <rect x={-half - battery.short_plate_thickness / 2} y={-battery.short_plate / 2}
              width={battery.short_plate_thickness} height={battery.short_plate} fill={battery.negative_color} />
      </>
    );
  } else {
    const fill = item.type === "ammeter" ? meter.ammeter_fill : meter.voltmeter_fill;
    body = (
      <>
        {lead(-CELL, -meter.radius)}
        {lead(meter.radius, CELL)}
        <circle r={meter.radius - meter.outline_thickness / 2} fill={fill} stroke={outline.color}
                strokeWidth={meter.outline_thickness} />
        <text textAnchor="middle" dominantBaseline="central" fontSize={meter.letter_size} fontWeight="700">
          {item.type === "ammeter" ? "A" : "V"}
        </text>
      </>
    );
  }
  return (
    <svg viewBox={`${-CELL - 6} -24 ${2 * CELL + 12} 48`} className="part-icon" aria-hidden="true">
      {body}
      <circle cx={-CELL} cy={0} r={pin.connector_radius} fill={pin.color} />
      <circle cx={CELL} cy={0} r={pin.connector_radius} fill={pin.color} />
    </svg>
  );
}

const rotate = ([dx, dy], times) => {
  let v = [dx, dy];
  for (let i = 0; i < times % 4; i++) v = [-v[1], v[0]];
  return v;
};

// A wire piece around its anchor, one grid step per arm.
export function WireIcon({ shape, rotation }) {
  const arms = WIRE_SHAPES[shape].map((arm) => rotate(arm, rotation).map((d) => d * CELL));
  const joint = STYLE.grid.connected_hole_radius * 3; // icons are small: joints scaled up to stay visible
  const ends = arms.map(([x, y]) => <circle key={`${x},${y}`} cx={x} cy={y} r={joint} fill={wire.color} />);
  return (
    <svg viewBox={`${-CELL - 8} ${-CELL - 8} ${2 * CELL + 16} ${2 * CELL + 16}`} className="wire-icon" aria-hidden="true">
      {arms.map(([x, y]) => (
        <line key={`${x},${y}`} x1={0} y1={0} x2={x} y2={y} stroke={wire.color} strokeWidth={wire.thickness * 4}
              strokeLinecap="round" />
      ))}
      <circle r={joint} fill={wire.color} />
      {ends}
    </svg>
  );
}

// Nominal value with a unit: 20 Ω, 4.7 kΩ, 1 MΩ, 9 V.
export function formatValue(item) {
  if (item.value == null) return null;
  if (item.type !== "resistor") return `${item.value} V`;
  const ohms = item.value;
  if (ohms >= 1e6) return `${+(ohms / 1e6).toPrecision(2)} MΩ`;
  if (ohms >= 1e3) return `${+(ohms / 1e3).toPrecision(2)} kΩ`;
  return `${ohms} Ω`;
}

// Caption under a part: its nominal value, or its ID for a meter.
export const partCaption = (item) => formatValue(item) ?? item.id;
export const partName = (item) => [item.id, item.type.replace("_", " "), formatValue(item)].filter(Boolean).join(" ");
