import assert from "node:assert";
import { describe, it } from "node:test";
import { type Component, TUI } from "../src/tui.js";
import { VirtualTerminal } from "./virtual-terminal.js";

class Lines implements Component {
	constructor(public lines: string[]) {}
	render(): string[] {
		return this.lines;
	}
	invalidate(): void {}
}

describe("TUI background painter", () => {
	it("paints fullscreen frames and keeps their row count", async () => {
		const terminal = new VirtualTerminal(30, 8);
		const tui = new TUI(terminal);
		const chat = new Lines(["hello"]);
		const dock = new Lines(["> prompt"]);
		tui.addChild(chat);
		tui.addChild(dock);
		tui.start();
		await terminal.waitForRender();
		tui.enterFullscreen({ scroll: [chat], dock });
		let calls = 0;
		tui.setBackgroundPainter((frame, width) => {
			calls++;
			return frame.map((line) => (line === "" ? "~".repeat(width) : line));
		}, 0);
		await terminal.waitForRender();
		const view = terminal.getViewport();
		tui.stop();
		assert.ok(calls > 0);
		assert.strictEqual(view.length, 8);
		assert.ok(view.includes("hello"));
		assert.ok(view.some((line) => line.startsWith("> prompt")));
		assert.ok(view.some((line) => line === "~".repeat(30)));
	});

	it("drops a painter that throws instead of crashing", async () => {
		const terminal = new VirtualTerminal(30, 6);
		const tui = new TUI(terminal);
		const chat = new Lines(["still here"]);
		const dock = new Lines(["> prompt"]);
		tui.addChild(chat);
		tui.addChild(dock);
		tui.start();
		await terminal.waitForRender();
		tui.enterFullscreen({ scroll: [chat], dock });
		tui.setBackgroundPainter(() => {
			throw new Error("boom");
		}, 0);
		await terminal.waitForRender();
		const view = terminal.getViewport();
		tui.stop();
		assert.ok(view.includes("still here"));
	});

	it("never paints inline (scrollback) rendering", async () => {
		const terminal = new VirtualTerminal(30, 8);
		const tui = new TUI(terminal);
		tui.addChild(new Lines(["hello", ""]));
		tui.start();
		let calls = 0;
		tui.setBackgroundPainter((frame) => {
			calls++;
			return frame;
		}, 0);
		await terminal.waitForRender();
		tui.stop();
		assert.strictEqual(calls, 0);
	});
});
