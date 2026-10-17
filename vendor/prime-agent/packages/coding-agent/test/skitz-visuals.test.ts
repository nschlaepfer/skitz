import { afterEach, describe, expect, it, vi } from "vitest";
import { equalizerFrames, spectrumRows, visualizerLines } from "../../../../../apps/cli/skitz-visuals.js";
import { hasOwnBackground, SkitzBackground, skitzBackgroundEnabled } from "../src/themes/skitz-background.js";
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
		expect(lines).toEqual(["  ██", "  ♪ song.wav  0:00 / 0:03"]);
	});

	it("keeps the strip at two rows for the whole song, with or without frames", () => {
		const start = 1_000_000;
		const playing = { pid: 1, title: "song.wav", started_at: start, fps: 10, seconds: 3, frames: [[10], [100]] };
		const heights = [0, 0.15, 2.5, 9].map((t) => visualizerLines(playing, (start + t) * 1000).length);
		expect(new Set(heights)).toEqual(new Set([2]));
		expect(visualizerLines({ pid: 1, title: "x.wav", started_at: start }, start * 1000)).toHaveLength(2);
	});
});

describe("Skitz ASCII background", () => {
	it("tells foreground colors from background colors", () => {
		expect(hasOwnBackground("\x1b[38;2;143;102;247mX\x1b[39m")).toBe(false);
		expect(hasOwnBackground("\x1b[1;38;5;44mX\x1b[0m")).toBe(false);
		expect(hasOwnBackground("\x1b[48;2;40;40;44m box \x1b[49m")).toBe(true);
		expect(hasOwnBackground("\x1b[44m box \x1b[0m")).toBe(true);
		expect(hasOwnBackground("\x1b[7m selected \x1b[27m")).toBe(true);
	});

	it("keeps content and self-painted rows, and fills empty rows", () => {
		const bg = new SkitzBackground();
		const frame = ["", "some text", "\x1b[48;2;1;2;3m box \x1b[49m", "> \x1b_pi:c\x07prompt", ""];
		const out = bg.paint(frame, 80, 5, 0);
		expect(out).toHaveLength(5);
		expect(strip(out[1]).startsWith("some text")).toBe(true);
		expect(out[2]).toBe(frame[2]);
		expect(out[3]).toBe(frame[3]);
	});

	it("keeps a clear zone around text", () => {
		const bg = new SkitzBackground({ density: 1, grain: 0 });
		const text = "x".repeat(30);
		const frame = Array.from({ length: 20 }, (_, i) => (i >= 5 && i <= 8 ? text : ""));
		const out = bg.paint(frame, 100, 20, 0).map(strip);
		for (const row of [5, 6, 7, 8]) {
			expect(out[row].slice(30, 36).trim()).toBe(""); // margin right after text
		}
		expect(out[7].slice(0, 40).replace(/x/g, "").trim()).toBe(""); // nothing between text rows
	});

	it("renders a large screen quickly", () => {
		const bg = new SkitzBackground();
		const frame = new Array(60).fill("");
		const started = performance.now();
		for (let i = 0; i < 10; i++) bg.paint(frame, 200, 60, i * 125);
		expect((performance.now() - started) / 10).toBeLessThan(20);
	});

	it("can be turned off", () => {
		vi.stubEnv("SKITZ_BACKGROUND", "off");
		expect(skitzBackgroundEnabled()).toBe(false);
	});
});
