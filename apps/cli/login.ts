import { spawn } from "node:child_process";
import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";
import { setImmediate } from "node:timers/promises";
import { AuthStorage } from "../../vendor/prime-agent/packages/coding-agent/src/core/auth-storage.js";

const storage = AuthStorage.create();
if (process.argv.includes("--status")) {
  console.log(JSON.stringify({ provider: "openai-codex", signedIn: storage.get("openai-codex")?.type === "oauth" }));
} else {
  const input = createInterface({ input: stdin, output: stdout });
  try {
    // Prime's browser-compatible OAuth module initializes Node builtins asynchronously.
    await setImmediate();
    await storage.login("openai-codex", {
      onAuth({ url }) {
        console.log(`Sign in to ChatGPT to connect your subscription:\n${url}`);
        const command = process.platform === "darwin" ? "open" : "xdg-open";
        const browser = spawn(command, [url], { stdio: "ignore" });
        browser.on("error", () => console.log("Open the sign-in link in your browser."));
      },
      onPrompt: (prompt) => input.question(`${prompt.message} `),
      onProgress: (message) => console.log(message),
    });
    console.log("Skitz is connected to your ChatGPT subscription.");
  } catch {
    console.error("Subscription sign-in did not complete. Run skitz login to retry.");
    process.exitCode = 1;
  } finally {
    input.close();
  }
}
