/**
 * Skitz visuals: music-themed animation for the agent's terminal screen.
 *
 * - Loader: a four-bar equalizer replaces the spinner while the agent works.
 * - Header: the animated SKITZ mark lives in the runtime's splash header
 *   (themes/skitz-shimmer.ts), because the daemon drops extension headers.
 * - Visualizer: while `skitz play` (or the agent) plays audio, live spectrum bars
 *   above the editor, drawn from the frames Python writes to ~/.skitz/playback.json.
 *   Extensions run in the session daemon, which forwards only plain widget lines, so
 *   the bars are re-sent about 12 times a second while audio plays.
 *
 * Set SKITZ_ANIMATIONS=off to keep the stock screen.
 */

import { appendFileSync, existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type {
	ExtensionAPI,
	ExtensionContext,
} from "../../vendor/prime-agent/packages/coding-agent/src/core/extensions/types.js";
import {
	paintRgb as paint,
	type Rgb,
	skitzAnimationsEnabled as animationsEnabled,
	skitzGradientAt as gradientAt,
} from "../../vendor/prime-agent/packages/coding-agent/src/themes/skitz-shimmer.js";

const BLOCKS = " ▁▂▃▄▅▆▇█";
const VISUALIZER_KEY = "skitz-visualizer";

/** Frames for a four-bar equalizer that bounces like a level meter. */
export function equalizerFrames(count = 12, bars = 4): string[] {
	const frames: string[] = [];
	for (let f = 0; f < count; f++) {
		let frame = "";
		for (let i = 0; i < bars; i++) {
			const wave = Math.sin((2 * Math.PI * f) / count + i * 1.3) * 0.5 + 0.5;
			const level = 1 + Math.round(wave * 7);
			frame += paint(BLOCKS[level], gradientAt(i / Math.max(1, bars - 1)));
		}
		frames.push(frame);
	}
	return frames;
}

/** Block-character rows (top first) for band levels from 0 to 100. */
export function spectrumRows(levels: number[], height: number): string[] {
	const rows: string[] = [];
	for (let row = height - 1; row >= 0; row--) {
		let line = "";
		levels.forEach((level, column) => {
			const filled = (level / 100) * height - row;
			const char = filled >= 1 ? BLOCKS[8] : BLOCKS[Math.max(0, Math.floor(filled * 8))];
			line += char === " " ? char : paint(char, gradientAt(column / Math.max(1, levels.length - 1)));
		});
		rows.push(line);
	}
	return rows;
}

export interface PlaybackState {
	pid: number;
	title: string;
	started_at: number;
	fps?: number;
	seconds?: number;
	frames?: number[][];
}

function playbackFile(): string {
	return join(process.env.SKITZ_STATE ?? join(homedir(), ".skitz"), "playback.json");
}

function readPlayback(): PlaybackState | undefined {
	const path = playbackFile();
	if (!existsSync(path)) return undefined;
	try {
		const state = JSON.parse(readFileSync(path, "utf8")) as PlaybackState;
		// A finished song, or a player that exited (kill(pid, 0) throws), means nothing plays.
		if (state.seconds !== undefined && Date.now() / 1000 - state.started_at > state.seconds + 2) return undefined;
		process.kill(state.pid, 0);
		return state;
	} catch {
		return undefined;
	}
}

function clock(seconds: number): string {
	const whole = Math.max(0, Math.floor(seconds));
	return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function truncate(text: string, width: number): string {
	return text.length <= width ? text : `…${text.slice(text.length - width + 1)}`;
}

/** Widget lines for one moment of playback: 4 rows of bars and a title line. */
export function visualizerLines(state: PlaybackState, now: number = Date.now()): string[] {
	const frames = state.frames ?? [];
	const elapsed = Math.min(now / 1000 - state.started_at, state.seconds ?? Number.POSITIVE_INFINITY);
	const levels = frames[Math.floor(elapsed * (state.fps ?? 20))] ?? new Array(frames[0]?.length ?? 32).fill(0);
	// Two columns per band: 64 columns for the usual 32 bands.
	const wide = levels.flatMap((level) => [level, level]);
	const title = `♪ ${truncate(state.title, 48)}  ${clock(elapsed)} / ${clock(state.seconds ?? 0)}`;
	return [...(frames.length ? spectrumRows(wide, 4).map((row) => `  ${row}`) : []), `  \x1b[2m${title}\x1b[22m`];
}

function debug(message: string): void {
	if (!process.env.SKITZ_VISUALS_DEBUG) return;
	appendFileSync(join(homedir(), ".skitz", "visuals-debug.log"), `${new Date().toISOString()} ${message}\n`);
}

export default function skitzVisuals(pi: ExtensionAPI) {
	debug(`loaded (animations ${animationsEnabled() ? "on" : "off"}, pid ${process.pid})`);
	if (!animationsEnabled()) return;
	let current: ExtensionContext | undefined;
	let poll: NodeJS.Timeout | undefined;
	let draw: NodeJS.Timeout | undefined;

	const stopDrawing = () => {
		if (draw) clearInterval(draw);
		draw = undefined;
		current?.ui.setWidget(VISUALIZER_KEY, undefined);
	};

	pi.on("session_start", async (_event, ctx) => {
		current = ctx;
		debug(`session_start hasUI=${ctx.hasUI}`);
		if (!ctx.hasUI) return;
		ctx.ui.setWorkingIndicator({ frames: equalizerFrames(), intervalMs: 90 });
		let playing: string | undefined;
		poll = setInterval(() => {
			const state = readPlayback();
			const id = state ? `${state.pid}:${state.started_at}` : undefined;
			if (state && id !== playing) {
				playing = id;
				debug(`visualizer start ${state.title} frames=${state.frames?.length ?? 0}`);
				if (draw) clearInterval(draw);
				draw = setInterval(() => current?.ui.setWidget(VISUALIZER_KEY, visualizerLines(state)), 80);
			} else if (!state && playing) {
				playing = undefined;
				stopDrawing();
			}
		}, 500);
	});

	pi.on("agent_start", async (_event, ctx) => {
		current = ctx;
	});

	pi.on("session_shutdown", async () => {
		if (poll) clearInterval(poll);
		stopDrawing();
	});
}
