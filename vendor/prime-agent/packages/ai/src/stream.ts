import "./providers/register-builtins.js";

import { getApiProvider } from "./api-registry.js";
import type {
	Api,
	AssistantMessage,
	AssistantMessageEventStream,
	Context,
	Model,
	ProviderStreamOptions,
	SimpleStreamOptions,
	StreamOptions,
} from "./types.js";

export { getEnvApiKey } from "./env-api-keys.js";

/**
 * Skitz allows two routes: the ChatGPT subscription (openai-codex) and Claude through
 * the Anthropic Messages API with an Anthropic API key. Claude subscription OAuth
 * tokens (sk-ant-oat...) are rejected: Anthropic does not allow third-party apps to
 * offer claude.ai sign-in without its approval.
 */
function assertSubscriptionProvider(model: Model<Api>, apiKey?: string): void {
	if (typeof process === "undefined" || process.env.SKITZ_SUBSCRIPTION_ONLY !== "1") return;
	if (model.provider === "openai-codex" && model.api === "openai-codex-responses") return;
	if (model.provider === "anthropic" && model.api === "anthropic-messages") {
		if (apiKey?.includes("sk-ant-oat")) {
			throw new Error(
				"Skitz can't use a Claude subscription sign-in. Connect Claude with an Anthropic API key: skitz auth login claude",
			);
		}
		return;
	}
	throw new Error(
		"Skitz uses your ChatGPT subscription (openai-codex) or an Anthropic API key (anthropic). Select one of those models.",
	);
}

function resolveApiProvider(api: Api) {
	const provider = getApiProvider(api);
	if (!provider) {
		throw new Error(`No API provider registered for api: ${api}`);
	}
	return provider;
}

export function stream<TApi extends Api>(
	model: Model<TApi>,
	context: Context,
	options?: ProviderStreamOptions,
): AssistantMessageEventStream {
	assertSubscriptionProvider(model, options?.apiKey);
	const provider = resolveApiProvider(model.api);
	return provider.stream(model, context, options as StreamOptions);
}

export async function complete<TApi extends Api>(
	model: Model<TApi>,
	context: Context,
	options?: ProviderStreamOptions,
): Promise<AssistantMessage> {
	const s = stream(model, context, options);
	return s.result();
}

export function streamSimple<TApi extends Api>(
	model: Model<TApi>,
	context: Context,
	options?: SimpleStreamOptions,
): AssistantMessageEventStream {
	assertSubscriptionProvider(model, options?.apiKey);
	const provider = resolveApiProvider(model.api);
	return provider.streamSimple(model, context, options);
}

export async function completeSimple<TApi extends Api>(
	model: Model<TApi>,
	context: Context,
	options?: SimpleStreamOptions,
): Promise<AssistantMessage> {
	const s = streamSimple(model, context, options);
	return s.result();
}
