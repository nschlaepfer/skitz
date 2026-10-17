import { setKeybindings, TUI, visibleWidth } from "@earendil-works/pi-tui";
import stripAnsi from "strip-ansi";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { VirtualTerminal } from "../../tui/test/virtual-terminal.js";
import { formatTopLevelHelp } from "../src/cli/command-registry.js";
import { APP_NAME, APP_TITLE, CONFIG_DIR_NAME, ENV_AGENT_DIR, ENV_SESSION_DIR } from "../src/config.js";
import { AuthStorage } from "../src/core/auth-storage.js";
import { KeybindingsManager } from "../src/core/keybindings.js";
import { ModelRegistry } from "../src/core/model-registry.js";
import { ProviderAuthFlows } from "../src/modes/interactive/auth-flows.js";
import { OAuthSelectorComponent } from "../src/modes/interactive/components/oauth-selector.js";
import { FEATURE_HINTS } from "../src/modes/interactive/feature-hints.js";
import { BrandSplashHeader } from "../src/modes/interactive/interactive-mode.js";
import { shouldRunOnboarding } from "../src/modes/interactive/onboarding.js";
import { initTheme } from "../src/modes/interactive/theme/theme.js";

const originalProduct = vi.hoisted(() => {
	const original = process.env.SKITZ_PRODUCT;
	process.env.SKITZ_PRODUCT = "1";
	return original;
});

afterAll(() => {
	if (originalProduct === undefined) delete process.env.SKITZ_PRODUCT;
	else process.env.SKITZ_PRODUCT = originalProduct;
});

beforeAll(() => {
	initTheme("dark");
	setKeybindings(new KeybindingsManager());
});

describe("Skitz presentation identity", () => {
	it("changes product identity without changing existing runtime override names", () => {
		expect(APP_NAME).toBe("skitz");
		expect(APP_TITLE).toBe("Skitz");
		expect(CONFIG_DIR_NAME).toBe(".skitz/agent");
		expect(ENV_AGENT_DIR).toBe("PRIME_AGENT_CODING_AGENT_DIR");
		expect(ENV_SESSION_DIR).toBe("PRIME_AGENT_SESSION_DIR");
	});

	it("advertises only supported authentication in help", () => {
		const help = formatTopLevelHelp();
		expect(help).toContain("skitz agent [options]");
		expect(help).toContain("ChatGPT subscription");
		expect(help).not.toMatch(/Prime|AI coding|--api-key|--provider|--models/);
	});

	it("renders the Skitz mark within desktop and narrow terminal bounds", () => {
		const header = new BrandSplashHeader(
			"0.9.4",
			() => "gpt-5.5",
			() => "/music",
		);
		for (const width of [24, 40, 80, 120]) {
			const lines = header.render(width);
			expect(stripAnsi(lines.join("\n"))).toContain("S K I T Z");
			expect(stripAnsi(lines.join("\n"))).not.toMatch(/Prime|PRIME/);
			for (const line of lines) expect(visibleWidth(line)).toBeLessThanOrEqual(width);
		}
	});

	it("offers ChatGPT subscription login without Prime or API-key options", () => {
		const storage = AuthStorage.inMemory();
		const registry = ModelRegistry.inMemory(storage);
		const flows = new ProviderAuthFlows({
			ui: new TUI(new VirtualTerminal()),
			modelRegistry: registry,
			showStatus: () => {},
			showError: () => {},
			getAvailableModels: async () => [],
		});
		const options = flows.getLoginProviderOptions();
		expect(options.map((option) => option.id)).toEqual(["openai-codex"]);
		expect(flows.getLoginProviderOptions("api_key")).toEqual([]);
		const selector = new OAuthSelectorComponent(
			"login",
			storage,
			options,
			() => {},
			() => {},
		);
		const rendered = stripAnsi(selector.render(80).join("\n"));
		expect(rendered).toContain("ChatGPT subscription");
		expect(rendered).not.toMatch(/Prime|API key/);
	});

	it("does not run upstream onboarding or promote upstream trace sharing", () => {
		expect(
			shouldRunOnboarding({
				settingsManager: { getOnboardingShown: () => false },
				model: undefined,
				modelRegistry: {
					refresh: () => {},
					hasConfiguredAuth: () => false,
					getProviderAuthStatus: () => ({ configured: false }),
				},
			}),
		).toBe(false);
		const hints = FEATURE_HINTS.map((hint) =>
			hint.getText({ getKeybinding: () => undefined, isResidentSession: false }),
		);
		expect(hints.join("\n")).not.toMatch(/Prime|\/traces/);
	});
});
