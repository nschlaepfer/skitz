import { afterEach, describe, expect, it, vi } from "vitest";
import { equalizerFrames, spectrumRows, visualizerLines } from "../../../../../apps/cli/skitz-visuals.js";
import {
	skitzAnimationsEnabled,
	skitzGradientAt,
	skitzShimmerLine,
	skitzSweepAt,
} from "../src/themes/skitz-shimmer.js";

const strip = (text: string) => text.replace(/\x1b\[[0-9;]*m/g, "");

afterEach(() => vi.unstubAllEnvs());

describe("Skitz shimmer header", () => {
	it("runs a gradient from magenta to cyan", () => {
		expect(skitzGradientAt(0)).toEqual([217, 70, 239]);
		expect(skitzGradientAt(1)).toEqual([34, 211, 238]);
	});

	it("keeps the logo's characters and only adds color", () => {
		const line = " / ___|| |/ /_ _|";
		const painted = skitzShimmerLine(line, line.length, 0.5);
		expect(strip(painted)).toBe(line);
		expect(painted).toContain("\x1b[38;2;");
	});

	it("brightens characters near the sweep", () => {
		const glowing = skitzShimmerLine("#", 1, 0);
		const plain = skitzShimmerLine("#", 1, -1);
		expect(glowing).not.toBe(plain);
	});

	it("sweeps only part of the time and can be turned off", () => {
		expect(skitzSweepAt(Date.now() + 6000)).toBe(-1);
		vi.stubEnv("SKITZ_ANIMATIONS", "off");
		expect(skitzAnimationsEnabled()).toBe(false);
	});
});

describe("Skitz visuals extension", () => {
	it("makes a bouncing four-bar equalizer loader", () => {
		const frames = equalizerFrames();
		expect(frames).toHaveLength(12);
		for (const frame of frames) expect([...strip(frame)]).toHaveLength(4);
		expect(new Set(frames.map(strip)).size).toBeGreaterThan(6);
	});

	it("draws block bars top row first", () => {
		expect(spectrumRows([100, 50, 0], 2).map(strip)).toEqual(["█  ", "██ "]);
	});

	it("shows the frame for the current playback time with a clock", () => {
		const start = 1_000_000;
		const state = { pid: 1, title: "song.wav", started_at: start, fps: 10, seconds: 3, frames: [[0], [100], [0]] };
		const lines = visualizerLines(state, (start + 0.15) * 1000).map(strip);
		expect(lines).toHaveLength(5);
		expect(lines[0]).toContain("██");
		expect(lines[4]).toContain("♪ song.wav  0:00 / 0:03");
	});
});
