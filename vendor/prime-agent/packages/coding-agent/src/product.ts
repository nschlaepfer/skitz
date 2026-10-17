// Presentation identity is separate from protocol, package and environment names.
export const IS_SKITZ = process.env.SKITZ_PRODUCT === "1";
export const PRODUCT_LABEL = IS_SKITZ ? "Skitz" : "Prime Agent";
export const PRODUCT_DESCRIPTION = IS_SKITZ
	? "Music composition and editing with your ChatGPT subscription"
	: "AI coding assistant with a Python REPL tool";
