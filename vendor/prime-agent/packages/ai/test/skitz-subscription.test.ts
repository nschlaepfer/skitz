import { afterEach, describe, expect, it, vi } from "vitest";
import { getModel } from "../src/models.js";
import { stream, streamSimple } from "../src/stream.js";

afterEach(() => vi.unstubAllEnvs());

describe("Skitz subscription boundary", () => {
	it("rejects API-key OpenAI models before dispatch", () => {
		vi.stubEnv("SKITZ_SUBSCRIPTION_ONLY", "1");
		const model = getModel("openai", "gpt-5.4");
		expect(() => stream(model, { messages: [] })).toThrow("ChatGPT subscription");
		expect(() => streamSimple(model, { messages: [] })).toThrow("ChatGPT subscription");
	});

	it("rejects Claude subscription OAuth tokens", () => {
		vi.stubEnv("SKITZ_SUBSCRIPTION_ONLY", "1");
		const model = getModel("anthropic", "claude-opus-5");
		// Built at runtime so no token-shaped literal sits in the repository.
		const oauth = { apiKey: ["sk", "ant", "oat01", "placeholder"].join("-") };
		expect(() => stream(model, { messages: [] }, oauth)).toThrow("Anthropic API key");
		expect(() => streamSimple(model, { messages: [] }, oauth)).toThrow("Anthropic API key");
	});

	it("rejects other providers, including Claude through a reseller", () => {
		vi.stubEnv("SKITZ_SUBSCRIPTION_ONLY", "1");
		const model = getModel("openrouter", "anthropic/claude-opus-4.5");
		expect(() => stream(model, { messages: [] })).toThrow("Anthropic API key (anthropic)");
	});
});
