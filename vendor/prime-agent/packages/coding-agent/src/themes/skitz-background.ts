// Skitz-only animated backdrop: a soft gradient glow drawn in ASCII characters,
// after the look of React Bits' "Gradient ASCII" background (horizon shape), written
// from scratch for the terminal. Light falls from the top over a dark curved horizon
// with a rim glow; brighter cells use denser glyphs and fill in first; the light drifts,
// glyphs flicker and a little grain breaks up banding.
//
// It only paints empty space, and fades out around text so content stays readable:
// within `halo` columns of a line's content, and on rows within two lines of text, the
// field dims to nothing, so paragraphs sit in a clear pocket. Rows that carry their own
// background color, reverse video, the cursor marker, hyperlinks or images are left
// untouched. SKITZ_BACKGROUND=off (or SKITZ_ANIMATIONS=off) disables it.

import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";

type Rgb = [number, number, number];

export interface SkitzBackgroundOptions {
	/** Colors from the edge of the shadow to the brightest light. */
	colors?: Rgb[];
	/** Glyphs from dimmest to brightest. */
	characters?: string;
	/** Share of cells that show a glyph, 0 to 1; brighter areas fill in first. */
	density?: number;
	/** How bright the backdrop is drawn, 0 to 1, so content stays readable. */
	strength?: number;
	/** How often glyphs swap, 0 to 1. */
	flicker?: number;
	/** Film grain, 0 to 0.4. */
	grain?: number;
	/** Drift speed; 0 holds still. */
	speed?: number;
	/** Columns kept fully clear after nearby content. */
	margin?: number;
	/** Columns over which the field fades back in after the clear margin. */
	halo?: number;
}

// React Bits' default palette, ordered dark to light.
const DEFAULT_COLORS: Rgb[] = [
	[30, 63, 216], // #1e3fd8
	[56, 189, 248], // #38bdf8
	[165, 216, 255], // #a5d8ff
	[246, 248, 255], // #f6f8ff
];
const DEFAULT_CHARACTERS = " =+xX0S8#@";
const LEVELS = 12;
const ESC = "\x1b";
const SGR = new RegExp(`${ESC}\\[([0-9;]*)m`, "g");
const UNTOUCHABLE = [`${ESC}_`, `${ESC}]`, `${ESC}P`];
const ANSI = new RegExp(
	`${ESC}\\[[0-9;?]*[ -/]*[@-~]|${ESC}\\][^\\x07]*(?:\\x07|${ESC}\\\\)|${ESC}_[^\\x07]*\\x07`,
	"g",
);

/** True when a line sets a background color or reverse video (so it paints its own cells). */
export function hasOwnBackground(line: string): boolean {
	for (const match of line.matchAll(SGR)) {
		const params = match[1] === "" ? [0] : match[1].split(";").map(Number);
		for (let i = 0; i < params.length; i++) {
			const p = params[i];
			if (p === 38 || p === 58) {
				// Foreground/underline color: skip its arguments (5;n or 2;r;g;b).
				i += params[i + 1] === 5 ? 2 : params[i + 1] === 2 ? 4 : 0;
			} else if (p === 48 || p === 7 || (p >= 40 && p <= 47) || (p >= 100 && p <= 107)) {
				return true;
			}
		}
	}
	return false;
}

export function skitzBackgroundEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
	const off = (value: string | undefined) => ["off", "0", "false", "no"].includes((value ?? "on").toLowerCase());
	return !off(env.SKITZ_BACKGROUND) && !off(env.SKITZ_ANIMATIONS);
}

/** Deterministic 0..1 hash of a cell (and a time step), so glyphs are stable between frames. */
function hash(x: number, y: number, step = 0): number {
	let h = (x * 374761393 + y * 668265263 + step * 2246822519) | 0;
	h = Math.imul(h ^ (h >>> 13), 1274126177);
	return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
}

function smoothstep(edge0: number, edge1: number, x: number): number {
	const t = Math.min(Math.max((x - edge0) / (edge1 - edge0), 0), 1);
	return t * t * (3 - 2 * t);
}

/**
 * Light at a cell, 0..1. `u` runs 0..1 across, `v` 0..1 down, `t` in seconds.
 * A glow from the top over a dark arched horizon, with a bright rim just above it.
 */
export function skitzLightAt(u: number, v: number, t: number): number {
	const x = u * 2 - 1;
	const horizon = 0.84 - 0.22 * (1 - x * x) + 0.025 * Math.sin(x * 3.1 + t * 0.4);
	if (v > horizon + 0.04) return 0;
	const above = Math.max(0, horizon - v) / horizon;
	const wave =
		0.5 +
		0.25 * Math.sin(u * 7.3 + t * 0.55 + Math.sin(v * 4.1 - t * 0.33) * 1.6) +
		0.25 * Math.sin(v * 9.7 - t * 0.47 + u * 2.3);
	const fall = 0.25 + 0.75 * above ** 1.6;
	const rim = Math.exp(-(((v - horizon) / 0.035) ** 2));
	// Fade the light in over the first stretch above the horizon, so the dark curve reads.
	const lift = smoothstep(0, 0.12, horizon - v);
	return Math.min(1, Math.max(0, fall * (0.6 + 0.4 * wave) * lift + rim * 0.85));
}

function colorAt(colors: Rgb[], level: number): Rgb {
	const scaled = Math.min(Math.max(level, 0), 1) * (colors.length - 1);
	const index = Math.min(Math.floor(scaled), colors.length - 2);
	const f = scaled - index;
	return [0, 1, 2].map((c) => Math.round(colors[index][c] + (colors[index + 1][c] - colors[index][c]) * f)) as Rgb;
}

export class SkitzBackground {
	private readonly colors: Rgb[];
	private readonly characters: string[];
	private readonly density: number;
	private readonly strength: number;
	private readonly flicker: number;
	private readonly grain: number;
	private readonly speed: number;
	private readonly margin: number;
	private readonly halo: number;
	private readonly startedAt = Date.now();
	private readonly palette: string[];

	constructor(options: SkitzBackgroundOptions = {}) {
		this.colors = options.colors ?? DEFAULT_COLORS;
		this.characters = [...(options.characters ?? DEFAULT_CHARACTERS)];
		this.density = options.density ?? 0.8;
		this.strength = options.strength ?? 0.4;
		this.flicker = options.flicker ?? 0.2;
		this.grain = options.grain ?? 0.08;
		this.speed = options.speed ?? 1;
		this.margin = options.margin ?? 3;
		this.halo = options.halo ?? 14;
		// Precomputed SGR codes per brightness level, dimmed toward the terminal background.
		this.palette = Array.from({ length: LEVELS }, (_, i) => {
			const [r, g, b] = colorAt(this.colors, i / (LEVELS - 1)).map((c) => Math.round(c * this.strength));
			return `${ESC}[38;2;${r};${g};${b}m`;
		});
	}

	/**
	 * One row of backdrop glyphs from column `from` to `width`. `reach` is how far
	 * content extends on this and nearby rows; the field fades in after it.
	 */
	row(y: number, height: number, from: number, width: number, now: number = Date.now(), reach = 0): string {
		const t = ((now - this.startedAt) / 1000) * this.speed;
		const step = Math.floor(t * 6);
		let out = "";
		let current = -1;
		let spaces = 0;
		for (let x = from; x < width; x++) {
			let light = skitzLightAt(x / Math.max(1, width - 1), y / Math.max(1, height - 1), t);
			light += (hash(x, y, step) - 0.5) * this.grain;
			if (reach > 0) light *= smoothstep(reach + this.margin, reach + this.margin + this.halo, x);
			const visible = light > 0.04 && hash(x, y) * (1 - light * 0.6) < this.density * light + 0.05;
			if (!visible) {
				spaces++;
				continue;
			}
			// Flicker: some cells borrow a neighbor's brightness for a beat.
			const flick = hash(x, y, step + 7) < this.flicker * 0.25 ? (hash(x + 1, y, step) - 0.5) * 0.3 : 0;
			const level = Math.min(1, Math.max(0, light + flick));
			const glyph =
				this.characters[Math.min(this.characters.length - 1, 1 + Math.floor(level * (this.characters.length - 1)))];
			const shade = Math.min(LEVELS - 1, Math.floor(level * LEVELS));
			if (spaces) {
				out += " ".repeat(spaces);
				spaces = 0;
			}
			if (shade !== current) {
				out += this.palette[shade];
				current = shade;
			}
			out += glyph;
		}
		if (spaces) out += " ".repeat(spaces);
		return current === -1 ? out : `${out}${ESC}[39m`;
	}

	/** Paint the backdrop into empty space of a full-screen frame. */
	paint(frame: string[], width: number, height: number, now: number = Date.now()): string[] {
		// How wide each row's content is; rows that paint themselves are left alone.
		const rows = frame.map((line) => {
			const fixed = UNTOUCHABLE.some((marker) => line.includes(marker)) || hasOwnBackground(line);
			const plain = line.replace(ANSI, "").trimEnd();
			return { fixed, used: plain.length === 0 ? 0 : visibleWidth(plain) };
		});
		// Content reach around each row: two rows of text above and below, and one row
		// next to a self-painted block (like the input box), counts as nearby.
		const reachAt = (y: number) => {
			let reach = 0;
			for (let dy = -2; dy <= 2; dy++) {
				const neighbor = rows[y + dy];
				if (!neighbor) continue;
				if (neighbor.fixed) {
					if (Math.abs(dy) <= 1) reach = Math.max(reach, neighbor.used);
				} else {
					reach = Math.max(reach, neighbor.used);
				}
			}
			return reach;
		};
		return frame.map((line, y) => {
			const { fixed, used } = rows[y];
			if (fixed) return line;
			const from = used === 0 ? 0 : Math.min(width, used + this.margin);
			if (from >= width) return line;
			const prefix = used === 0 ? "" : `${truncateToWidth(line, from, "", true)}${ESC}[0m`;
			return prefix + this.row(y, height, from, width, now, reachAt(y));
		});
	}
}
