// Skitz-only splash animation: the logo in a magenta-to-cyan gradient with a bright
// band that sweeps across it for SWEEP_MS at startup, then once every PERIOD_MS.
// SKITZ_ANIMATIONS=off keeps it static.

export type Rgb = [number, number, number];

export const SKITZ_GRADIENT: Rgb[] = [
	[217, 70, 239],
	[139, 92, 246],
	[59, 130, 246],
	[34, 211, 238],
];
const SWEEP_MS = 1400;
const PERIOD_MS = 12000;
const startedAt = Date.now();

export function skitzAnimationsEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
	return !["off", "0", "false", "no"].includes((env.SKITZ_ANIMATIONS ?? "on").toLowerCase());
}

export function skitzGradientAt(position: number): Rgb {
	const scaled = Math.min(Math.max(position, 0), 1) * (SKITZ_GRADIENT.length - 1);
	const index = Math.min(Math.floor(scaled), SKITZ_GRADIENT.length - 2);
	const t = scaled - index;
	const a = SKITZ_GRADIENT[index];
	const b = SKITZ_GRADIENT[index + 1];
	return [0, 1, 2].map((c) => Math.round(a[c] + (b[c] - a[c]) * t)) as Rgb;
}

export function paintRgb(text: string, [r, g, b]: Rgb): string {
	return `\x1b[38;2;${r};${g};${b}m${text}\x1b[39m`;
}

/** Sweep position from 0 to 1 while a sweep is running, otherwise -1. */
export function skitzSweepAt(now: number = Date.now()): number {
	const age = (now - startedAt) % PERIOD_MS;
	return age < SWEEP_MS ? age / SWEEP_MS : -1;
}

/** One logo line colored by column across `width`, brightened near `sweep`. */
export function skitzShimmerLine(line: string, width: number, sweep: number): string {
	let out = "";
	for (let column = 0; column < line.length; column++) {
		const char = line[column];
		if (char === " ") {
			out += char;
			continue;
		}
		const position = column / Math.max(1, width - 1);
		const glow = sweep < 0 ? 0 : Math.max(0, 1 - Math.abs(position - sweep) * 6) * 0.75;
		const base = skitzGradientAt(position);
		out += paintRgb(char, base.map((c) => Math.round(c + (255 - c) * glow)) as Rgb);
	}
	return out;
}

/** Redraw while a sweep runs (and once after it ends); idle otherwise. */
export function startSkitzShimmer(requestRender: () => void): NodeJS.Timeout {
	let wasSweeping = true;
	const timer = setInterval(() => {
		const sweeping = skitzSweepAt() >= 0;
		if (sweeping || wasSweeping) requestRender();
		wasSweeping = sweeping;
	}, 60);
	timer.unref?.();
	return timer;
}
