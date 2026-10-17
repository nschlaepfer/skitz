import { type Component, Container, visibleWidth } from "@earendil-works/pi-tui";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { InteractiveMode } from "../src/modes/interactive/interactive-mode.js";
import { initTheme } from "../src/modes/interactive/theme/theme.js";

function callPrivate(mode: object, name: string, ...args: unknown[]): unknown {
	return Reflect.get(InteractiveMode.prototype, name).call(mode, ...args);
}

function createWidgetMode() {
	const mode = Object.assign(Object.create(InteractiveMode.prototype), {
		extensionWidgetsAbove: new Map(),
		extensionWidgetsBelow: new Map(),
		extensionWidgetsPinned: new Map(),
		widgetContainerAbove: new Container(),
		widgetContainerBelow: new Container(),
		widgetContainerPinned: new Container(),
		headerContainer: new Container(),
		mainViewContainer: new Container(),
		recapContainer: new Container(),
		featureHintContainer: new Container(),
		queuedMessagesContainer: new Container(),
		sideQuestionContainer: new Container(),
		editorContainer: new Container(),
		subagentSummaryLine: new Container(),
		footerSlot: new Container(),
		promptDock: new Container(),
		ui: { requestRender: vi.fn(), enterFullscreen: vi.fn() },
	});
	// A getter on the class; give this stripped-down mode its own value.
	Object.defineProperty(mode, "settingsManager", { value: { getFullscreenMouse: () => false } });
	return mode as WidgetMode;
}

interface WidgetMode {
	extensionWidgetsAbove: Map<string, Component>;
	extensionWidgetsBelow: Map<string, Component>;
	extensionWidgetsPinned: Map<string, Component>;
	widgetContainerAbove: Container;
	widgetContainerPinned: Container;
	editorContainer: Container;
	promptDock: Container;
	ui: { enterFullscreen: ReturnType<typeof vi.fn> };
}

const strip = (line: string) => line.replace(/\x1b\[[0-9;]*m/g, "");

describe("pinned extension widgets", () => {
	beforeAll(() => initTheme("dark"));
	afterEach(() => vi.restoreAllMocks());

	it("renders in the pinned slot, one row per line at any width", () => {
		const mode = createWidgetMode();
		const title = "♪ a song title long enough to wrap in a narrow terminal  0:42 / 3:10";
		callPrivate(mode, "setExtensionWidget", "viz", ["  ▂▅▇█▆▃", `  ${title}`], { placement: "pinned" });

		const rows = mode.widgetContainerPinned.render(30);
		expect(rows).toHaveLength(2);
		for (const row of rows) expect(visibleWidth(row)).toBeLessThanOrEqual(30);
		expect(strip(rows[0])).toContain("▂▅▇█▆▃");
		// Nothing landed in the transcript-side widget slots.
		expect(mode.extensionWidgetsAbove.size).toBe(0);
		expect(mode.extensionWidgetsBelow.size).toBe(0);
	});

	it("keeps pinned widgets in the fullscreen dock, not the scrolling transcript", () => {
		const mode = createWidgetMode();
		const tty = Object.getOwnPropertyDescriptor(process.stdout, "isTTY");
		Object.defineProperty(process.stdout, "isTTY", { value: true, configurable: true });
		try {
			callPrivate(mode, "applyFullscreen", true);
		} finally {
			if (tty) Object.defineProperty(process.stdout, "isTTY", tty);
			else delete (process.stdout as { isTTY?: boolean }).isTTY;
		}

		const { scroll, dock } = mode.ui.enterFullscreen.mock.calls[0][0] as { scroll: Component[]; dock: Component };
		expect(scroll).not.toContain(mode.widgetContainerPinned);
		expect(scroll).toContain(mode.widgetContainerAbove);
		expect(dock).toBe(mode.promptDock);
		const dockParts = callPrivate(mode, "getPromptDockComponents") as Component[];
		expect(dockParts[0]).toBe(mode.widgetContainerPinned);
		expect(dockParts[1]).toBe(mode.editorContainer);
	});

	it("takes no rows once cleared, and moves when re-sent with another placement", () => {
		const mode = createWidgetMode();
		callPrivate(mode, "setExtensionWidget", "viz", ["bars", "title"], { placement: "pinned" });
		callPrivate(mode, "setExtensionWidget", "viz", undefined);
		expect(mode.widgetContainerPinned.render(40)).toEqual([]);

		callPrivate(mode, "setExtensionWidget", "viz", ["bars"], { placement: "pinned" });
		callPrivate(mode, "setExtensionWidget", "viz", ["bars"]);
		expect(mode.extensionWidgetsPinned.size).toBe(0);
		expect(mode.extensionWidgetsAbove.size).toBe(1);
	});
});
