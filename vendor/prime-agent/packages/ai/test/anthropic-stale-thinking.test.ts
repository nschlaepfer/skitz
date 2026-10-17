import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import Anthropic from "@anthropic-ai/sdk";
import type { MessageCreateParamsStreaming } from "@anthropic-ai/sdk/resources/messages.js";
import { beforeEach, describe, expect, it } from "vitest";
import { getModel } from "../src/models.js";
import {
	isStaleThinkingError,
	resetStaleThinkingSessions,
	streamAnthropic,
	withStaleThinkingDropped,
} from "../src/providers/anthropic.js";
import type { Context, Model } from "../src/types.js";

// Claude Opus 5.5 thinks every turn and checks that replayed thinking still matches its conversation.
const model: Model<"anthropic-messages"> = { ...getModel("anthropic", "claude-opus-4-7"), id: "claude-opus-5-5" };

const STALE_MESSAGE =
	"messages.1.content.0: Invalid `signature` in `thinking` block. The block is bound to a different conversation. " +
	'Remove the block, or set `thinking.block_binding.prefix_mismatch_behavior` to "drop_block". ' +
	"The `system` prompt differs from the one this block was created with.";

function apiError(message: string): Error {
	return Anthropic.APIError.generate(
		400,
		{ type: "error", error: { type: "invalid_request_error", message } },
		undefined,
		new Headers(),
	);
}

function sse(transformations?: unknown[]): Response {
	const events = [
		{
			type: "message_start",
			message: {
				id: "msg_test",
				usage: { input_tokens: 10, output_tokens: 0 },
				...(transformations ? { input_transformations: transformations } : {}),
			},
		},
		{ type: "content_block_start", index: 0, content_block: { type: "text", text: "" } },
		{ type: "content_block_delta", index: 0, delta: { type: "text_delta", text: "ok" } },
		{ type: "content_block_stop", index: 0 },
		{ type: "message_delta", delta: { stop_reason: "end_turn" }, usage: { output_tokens: 1 } },
		{ type: "message_stop" },
	];
	const body = events.map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n`).join("\n");
	return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

type Reply = Response | Error;

/** A client that answers each request with the next reply and records what was sent. */
function fakeClient(replies: Reply[]) {
	const calls: { body: MessageCreateParamsStreaming; headers?: Record<string, string> }[] = [];
	const client = {
		messages: {
			create(body: MessageCreateParamsStreaming, options?: { headers?: Record<string, string> }) {
				calls.push({ body, headers: options?.headers });
				const reply = replies.shift();
				return {
					asResponse: async () => {
						if (!reply) throw new Error("unexpected request");
						if (reply instanceof Error) throw reply;
						return reply;
					},
				};
			},
		},
	} as unknown as Anthropic;
	return { client, calls };
}

// A conversation whose earlier assistant turn carries a signed thinking block.
const context: Context = {
	systemPrompt: "You are Skitz. (re-rendered after a refinement)",
	messages: [
		{ role: "user", content: "Make a beat", timestamp: 1 },
		{
			role: "assistant",
			content: [
				{ type: "thinking", thinking: "Plan the drums first.", thinkingSignature: "sig-1" },
				{ type: "text", text: "Starting with the drums." },
			],
			api: "anthropic-messages",
			provider: "anthropic",
			model: "claude-opus-5-5",
			usage: {
				input: 0,
				output: 0,
				cacheRead: 0,
				cacheWrite: 0,
				totalTokens: 0,
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
			},
			stopReason: "stop",
			timestamp: 2,
		},
		{ role: "user", content: "Keep going", timestamp: 3 },
	],
};

const dropBlock = { prefix_mismatch_behavior: "drop_block" };

describe("Anthropic stale thinking recovery", () => {
	beforeEach(() => resetStaleThinkingSessions());

	it("recognizes only the stale-thinking 400", () => {
		expect(isStaleThinkingError(apiError(STALE_MESSAGE))).toBe(true);
		expect(isStaleThinkingError(apiError("max_tokens: must be at most 128000"))).toBe(false);
		expect(isStaleThinkingError(new Error("bound to a different conversation"))).toBe(false); // no status
	});

	it("drops stale blocks on retry and keeps doing so for the session", async () => {
		const { client, calls } = fakeClient([
			apiError(STALE_MESSAGE),
			sse([{ type: "thinking_dropped", path: "messages.1.content.0", reason: "prefix_binding_mismatch" }]),
			sse([{ type: "thinking_dropped", path: "messages.1.content.0", reason: "prefix_binding_mismatch" }]),
		]);
		const options = { client, sessionId: "session-a", thinkingEnabled: true };

		const first = await streamAnthropic(model, context, options).result();
		expect(first.stopReason).toBe("stop");
		expect(first.content).toEqual([{ type: "text", text: "ok" }]);
		expect(calls).toHaveLength(2);
		expect(calls[0].headers).toBeUndefined();
		expect((calls[0].body.thinking as { block_binding?: unknown }).block_binding).toBeUndefined();
		expect(calls[1].headers).toEqual({ "anthropic-beta": "thinking-binding-controls-2026-08-01" });
		expect(calls[1].body.thinking).toMatchObject({ type: "adaptive", block_binding: dropBlock });
		// The history itself goes out unchanged; the API decides which blocks are stale.
		expect(calls[1].body.messages).toEqual(calls[0].body.messages);
		expect(calls[1].body.system).toEqual(calls[0].body.system);
		expect(first.diagnostics).toEqual([
			expect.objectContaining({
				type: "anthropic_stale_thinking_dropped",
				details: { retried: true, droppedBlocks: 1 },
			}),
		]);

		// The next turn of the same session sends drop_block straight away: one request, no failure.
		const second = await streamAnthropic(model, context, options).result();
		expect(second.stopReason).toBe("stop");
		expect(calls).toHaveLength(3);
		expect(calls[2].body.thinking).toMatchObject({ block_binding: dropBlock });
		expect(second.diagnostics).toEqual([expect.objectContaining({ details: { retried: false, droppedBlocks: 1 } })]);
	});

	it("leaves other sessions and other errors alone", async () => {
		const stale = fakeClient([apiError(STALE_MESSAGE), sse([])]);
		await streamAnthropic(model, context, { client: stale.client, sessionId: "session-a" }).result();

		const other = fakeClient([sse()]);
		await streamAnthropic(model, context, { client: other.client, sessionId: "session-b" }).result();
		expect(other.calls[0].headers).toBeUndefined();

		const failing = fakeClient([apiError("max_tokens: must be at most 128000")]);
		const result = await streamAnthropic(model, context, { client: failing.client, sessionId: "session-c" }).result();
		expect(result.stopReason).toBe("error");
		expect(failing.calls).toHaveLength(1);
	});

	it("does not retry twice when the recovery request is rejected too", async () => {
		const { client, calls } = fakeClient([apiError(STALE_MESSAGE), apiError(STALE_MESSAGE)]);
		const result = await streamAnthropic(model, context, { client, sessionId: "session-a" }).result();
		expect(result.stopReason).toBe("error");
		expect(calls).toHaveLength(2);
	});

	it("extends the client's own beta header through the real SDK", async () => {
		const seen: { beta?: string; body: { thinking?: unknown } }[] = [];
		const server = createServer((request, response) => {
			let raw = "";
			request.on("data", (chunk) => {
				raw += chunk;
			});
			request.on("end", async () => {
				seen.push({ beta: request.headers["anthropic-beta"] as string | undefined, body: JSON.parse(raw) });
				if (seen.length === 1) {
					response.writeHead(400, { "content-type": "application/json" });
					response.end(
						JSON.stringify({ type: "error", error: { type: "invalid_request_error", message: STALE_MESSAGE } }),
					);
					return;
				}
				const reply = sse([]);
				response.writeHead(200, { "content-type": "text/event-stream" });
				response.end(await reply.text());
			});
		});
		await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
		try {
			const { port } = server.address() as AddressInfo;
			const local = { ...model, baseUrl: `http://127.0.0.1:${port}` };
			const result = await streamAnthropic(local, context, {
				apiKey: "test-key",
				sessionId: "session-real",
				headers: { "anthropic-beta": "example-beta-2026-01-01" },
			}).result();
			expect(result.stopReason).toBe("stop");
			expect(seen.map((request) => request.beta)).toEqual([
				"example-beta-2026-01-01",
				"example-beta-2026-01-01,thinking-binding-controls-2026-08-01",
			]);
			expect(seen[1].body.thinking).toMatchObject({ block_binding: dropBlock });
		} finally {
			server.close();
		}
	});

	it("adds the binding control to whichever thinking configuration the request has", () => {
		const base: MessageCreateParamsStreaming = {
			model: "claude-opus-5-5",
			max_tokens: 10,
			messages: [],
			stream: true,
		};
		// Always-on models omit `thinking` when thinking is "off"; the API default is adaptive.
		expect(withStaleThinkingDropped(base)?.thinking).toEqual({ type: "adaptive", block_binding: dropBlock });
		expect(
			withStaleThinkingDropped({ ...base, thinking: { type: "adaptive", display: "summarized" } })?.thinking,
		).toEqual({ type: "adaptive", display: "summarized", block_binding: dropBlock });
		expect(withStaleThinkingDropped({ ...base, thinking: { type: "disabled" } })).toBeUndefined();
	});
});
