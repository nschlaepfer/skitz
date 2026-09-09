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
});
