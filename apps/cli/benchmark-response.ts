import { readFileSync } from "node:fs";
import { getModels } from "../../vendor/prime-agent/packages/ai/src/models.js";
import { completeSimple } from "../../vendor/prime-agent/packages/ai/src/stream.js";
import type { UserMessage } from "../../vendor/prime-agent/packages/ai/src/types.js";
import { AuthStorage } from "../../vendor/prime-agent/packages/coding-agent/src/core/auth-storage.js";

const request = JSON.parse(readFileSync(0, "utf8")) as { prompt: string; model: string; maxTokens: number };
const auth = AuthStorage.create();
if (auth.get("openai-codex")?.type !== "oauth") {
  throw new Error("Sign in to your ChatGPT subscription with skitz login first.");
}
const model = getModels("openai-codex").find((candidate) => candidate.id === request.model);
if (!model) throw new Error("Unknown subscription model. Choose a model in the pinned Prime catalog.");
const access = await auth.getApiKey("openai-codex");
if (!access) throw new Error("Subscription authentication is unavailable. Run skitz login.");
const started = performance.now();
const user: UserMessage = { role: "user", content: request.prompt, timestamp: Date.now() };
const answer = await completeSimple(model, { messages: [user] }, { apiKey: access, maxTokens: request.maxTokens });
console.log(JSON.stringify({
  provider: model.provider, model: model.id, elapsedMs: performance.now() - started,
  text: answer.content.filter((part) => part.type === "text").map((part) => part.text).join("\n"),
  usage: {
    input: answer.usage.input, output: answer.usage.output,
    cacheRead: answer.usage.cacheRead, cacheWrite: answer.usage.cacheWrite,
    totalTokens: answer.usage.totalTokens,
  },
  billing: "chatgpt-subscription", stopReason: answer.stopReason,
}));
